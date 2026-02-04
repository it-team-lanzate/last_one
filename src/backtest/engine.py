"""
Event-driven backtest engine: Squeeze Breakout LONG-only.
Entry: buy-stop at range_high + 0.10*ATR. Optional quality filter.
Stop: min(range_low - 0.10*ATR, entry - 1.5*ATR).
TP1: +1R close 50%. Rest: Chandelier trail. Time stop: 6 bars no +0.5R -> close.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from src.strategy.signals import compute_signals
from src.strategy.squeeze import SqueezeRange
from src.execution.paper_broker import PaperBroker
from src.execution.fees import apply_fees_slippage


class ExitReason(str, Enum):
    TP1 = "tp1"
    TRAIL = "trail"
    TIME_STOP = "time_stop"
    STOP_HIT = "stop_hit"


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_fill: float
    exit_fill: float
    qty: float
    r_value: float
    r_realized: float  # (exit_fill - entry_fill) / r_value for full close; partials combined
    fee_entry: float
    fee_exit: float
    slippage_entry: float
    slippage_exit: float
    exit_reason: str
    pnl: float
    pnl_net: float  # after fees


@dataclass
class BacktestResult:
    run_id: int | None = None
    run_type: str = "backtest"
    config: dict[str, Any] = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    n_trades: int = 0
    n_wins: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)
    n_squeeze_ranges: int = 0  # diagnostic when 0 trades
    n_bars: int = 0


def _tp1_level(entry_fill: float, r_value: float, tp1_r: float) -> float:
    return entry_fill + tp1_r * r_value


def _chandelier_trail(high_22: float, atr_14: float, mult: float) -> float:
    return high_22 - mult * atr_14


def run_backtest(
    df: pd.DataFrame,
    config: dict[str, Any],
    run_id: int | None = None,
) -> BacktestResult:
    """
    Event-driven backtest. df must have OHLCV columns.
    """
    strat = config.get("strategy", {})
    risk = config.get("risk", {})
    bt = config.get("backtest", config.get("paper_live", {}))
    initial_capital = float(bt.get("initial_capital", 10000.0))
    quality_filter = strat.get("quality_filter", False)
    entry_require_close_above = strat.get("entry_require_close_above", True)
    trend_filter = strat.get("trend_filter", True)
    trend_period = int(strat.get("trend_period", 200))
    min_r_atr_mult = float(strat.get("min_r_atr_mult", 0.5))
    tp1_r = strat.get("tp1_r", 1.0)
    tp1_close_pct = strat.get("tp1_close_pct", 0.5)
    chandelier_lookback = strat.get("chandelier_lookback", 22)
    chandelier_atr_mult = strat.get("chandelier_atr_mult", 3.0)
    trail_activation_r = float(strat.get("trail_activation_r", 0.0))
    time_stop_bars = strat.get("time_stop_bars", 6)
    time_stop_min_r = strat.get("time_stop_min_r", 0.5)

    df = compute_signals(df, config)
    ranges: list[SqueezeRange] = df.attrs.get("squeeze_ranges", [])
    if "atr_14" not in df.columns:
        raise ValueError("compute_signals must add atr_14")
    df["high_22"] = df["high"].rolling(chandelier_lookback).max()
    if trend_filter and "trend_sma" not in df.columns:
        df["trend_sma"] = df["close"].rolling(trend_period).mean()

    broker = PaperBroker(config, initial_capital)
    trades: list[Trade] = []
    # Index of next range to consider for entry (ranges that have ended)
    next_range_idx = 0
    # Bars since squeeze end to consider this range "active" for buy-stop (we only enter once per range)
    entered_ranges: set[int] = set()

    for i in range(len(df)):
        bar = df.iloc[i]
        ts = bar["open_time"]
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]
        atr_14 = bar["atr_14"]
        high_22 = bar["high_22"]
        tr = bar.get("tr")
        sma_tr_20 = bar.get("sma_tr_20")

        broker.portfolio.snapshot_equity(ts)

        pos = broker.portfolio.position

        if pos is not None:
            pos.bars_in_trade += 1
            # Breakeven: after +0.5R move stop to entry so we don't give back profit
            current_r = (close - pos.entry_fill) / pos.r_value if pos.r_value else 0
            if current_r >= 0.5 and pos.stop < pos.entry_fill:
                pos.stop = pos.entry_fill
            # --- In position: check exit order ---
            # 1) Stop
            if low <= pos.stop:
                exit_price = pos.stop
                pnl, fee_exit, exit_fill = broker.close_long(bar, exit_price)
                r_realized = (exit_fill - pos.entry_fill) / pos.r_value if pos.r_value else 0
                trades.append(
                    Trade(
                        entry_time=pos.entry_time,
                        exit_time=ts,
                        entry_fill=pos.entry_fill,
                        exit_fill=exit_fill,
                        qty=pos.qty,
                        r_value=pos.r_value,
                        r_realized=r_realized,
                        fee_entry=0,
                        fee_exit=fee_exit,
                        slippage_entry=0,
                        slippage_exit=0,
                        exit_reason=ExitReason.STOP_HIT.value,
                        pnl=pnl + fee_exit,
                        pnl_net=pnl,
                    )
                )
                continue
            # 2) TP1 (partial): high >= tp1_level and not tp1_done
            tp1_level = _tp1_level(pos.entry_fill, pos.r_value, tp1_r)
            if not pos.tp1_done and high >= tp1_level:
                close_qty = pos.qty * tp1_close_pct
                _, _, fee_tp1, _ = apply_fees_slippage(
                    pos.entry_fill, tp1_level, close_qty, broker.fee_params
                )
                pnl_tp1 = broker.reduce_position(close_qty, tp1_level, fee_tp1)
                trades.append(
                    Trade(
                        entry_time=pos.entry_time,
                        exit_time=ts,
                        entry_fill=pos.entry_fill,
                        exit_fill=tp1_level,
                        qty=close_qty,
                        r_value=pos.r_value,
                        r_realized=tp1_r,
                        fee_entry=0,
                        fee_exit=fee_tp1,
                        slippage_entry=0,
                        slippage_exit=0,
                        exit_reason=ExitReason.TP1.value,
                        pnl=pnl_tp1 + fee_tp1,
                        pnl_net=pnl_tp1,
                    )
                )
                continue
            # 3) Chandelier trail (only active after +trail_activation_r to avoid cutting small winners)
            current_r_pos = (close - pos.entry_fill) / pos.r_value if pos.r_value else 0
            if pd.notna(high_22) and pd.notna(atr_14) and current_r_pos >= trail_activation_r:
                trail = _chandelier_trail(high_22, atr_14, chandelier_atr_mult)
                if close < trail:
                    exit_price = max(close, pos.stop)
                    pnl, fee_exit, exit_fill = broker.close_long(bar, exit_price)
                    r_realized = (exit_fill - pos.entry_fill) / pos.r_value if pos.r_value else 0
                    trades.append(
                        Trade(
                            entry_time=pos.entry_time,
                            exit_time=ts,
                            entry_fill=pos.entry_fill,
                            exit_fill=exit_fill,
                            qty=pos.qty,
                            r_value=pos.r_value,
                            r_realized=r_realized,
                            fee_entry=0,
                            fee_exit=fee_exit,
                            slippage_entry=0,
                            slippage_exit=0,
                            exit_reason=ExitReason.TRAIL.value,
                            pnl=pnl + fee_exit,
                            pnl_net=pnl,
                        )
                    )
                    continue
            # 4) Time stop
            if pos.bars_in_trade >= time_stop_bars:
                current_r = (close - pos.entry_fill) / pos.r_value if pos.r_value else 0
                if current_r < time_stop_min_r:
                    exit_price = max(close, pos.stop)
                    pnl, fee_exit, exit_fill = broker.close_long(bar, exit_price)
                    r_realized = (exit_fill - pos.entry_fill) / pos.r_value if pos.r_value else 0
                    trades.append(
                        Trade(
                            entry_time=pos.entry_time,
                            exit_time=ts,
                            entry_fill=pos.entry_fill,
                            exit_fill=exit_fill,
                            qty=pos.qty,
                            r_value=pos.r_value,
                            r_realized=r_realized,
                            fee_entry=0,
                            fee_exit=fee_exit,
                            slippage_entry=0,
                            slippage_exit=0,
                            exit_reason=ExitReason.TIME_STOP.value,
                            pnl=pnl + fee_exit,
                            pnl_net=pnl,
                        )
                    )
                    continue
            continue
        # --- No position: check entry ---
        for ri, sr in enumerate(ranges):
            if sr.end_idx >= i:
                break
            if ri in entered_ranges:
                continue
            if high < sr.entry_level:
                continue
            if entry_require_close_above and close <= sr.entry_level:
                continue
            if trend_filter and "trend_sma" in df.columns:
                trend_sma = bar.get("trend_sma")
                if pd.isna(trend_sma) or close <= trend_sma:
                    continue
            r_val = sr.entry_level - sr.stop_level
            if atr_14 and pd.notna(atr_14) and atr_14 > 0 and r_val < min_r_atr_mult * atr_14:
                continue
            if quality_filter and tr is not None and sma_tr_20 is not None and pd.notna(sma_tr_20) and sma_tr_20 > 0:
                if tr <= 1.1 * sma_tr_20:
                    continue
            pos = broker.open_long(
                bar=bar,
                entry_level=sr.entry_level,
                stop=sr.stop_level,
                tp1_level=sr.entry_level + (sr.entry_level - sr.stop_level),
                entry_bar_idx=i,
                chandelier_lookback=chandelier_lookback,
                chandelier_atr_mult=chandelier_atr_mult,
                time_stop_bars=time_stop_bars,
                time_stop_min_r=time_stop_min_r,
            )
            if pos is not None:
                entered_ranges.add(ri)
            break

    # Build result
    equity_curve = broker.portfolio.equity_curve
    final_equity = broker.portfolio.equity
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100 if initial_capital else 0
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t.pnl_net > 0)
    win_rate = n_trades and (n_wins / n_trades * 100) or 0
    gross_profit = sum(t.pnl_net for t in trades if t.pnl_net > 0)
    gross_loss = abs(sum(t.pnl_net for t in trades if t.pnl_net < 0))
    profit_factor = gross_loss and (gross_profit / gross_loss) or (gross_profit and float("inf") or 0)
    peak = initial_capital
    max_dd = 0.0
    for _, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak else 0
        if dd > max_dd:
            max_dd = dd

    return BacktestResult(
        run_id=run_id,
        run_type="backtest",
        config=config,
        start_date=str(df["open_time"].iloc[0].date()) if len(df) else "",
        end_date=str(df["open_time"].iloc[-1].date()) if len(df) else "",
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        n_trades=n_trades,
        n_wins=n_wins,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        trades=trades,
        equity_curve=equity_curve,
        n_squeeze_ranges=len(ranges),
        n_bars=len(df),
    )


class BacktestEngine:
    """Thin wrapper around run_backtest for API consistency."""
    @staticmethod
    def run(df: pd.DataFrame, config: dict[str, Any], run_id: int | None = None) -> BacktestResult:
        return run_backtest(df, config, run_id=run_id)
