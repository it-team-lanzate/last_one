"""
Portfolio state: capital, equity, open position, drawdown.
Risk: risk_pct per trade, qty = risk_usd / (entry_fill - stop).
Max 1 open position. Guardrails: max_drawdown_stop, max_consecutive_losses.
"""
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Position:
    entry_time: pd.Timestamp
    entry_fill: float
    stop: float
    qty: float
    tp1_level: float
    tp1_done: bool
    bars_in_trade: int
    entry_bar_idx: int
    chandelier_lookback: int
    chandelier_atr_mult: float
    time_stop_bars: int
    time_stop_min_r: float
    r_value: float  # entry_fill - stop


@dataclass
class Portfolio:
    initial_capital: float
    cash: float
    equity: float
    position: Position | None = None
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    max_drawdown_stop_pct: float | None = None
    max_consecutive_losses: int | None = None

    def __post_init__(self) -> None:
        self.cash = float(self.initial_capital)
        self.equity = float(self.initial_capital)
        self.peak_equity = self.equity

    def can_open(self, config: dict[str, Any]) -> bool:
        risk = config.get("risk", {})
        if self.position is not None:
            return False
        max_dd = risk.get("max_drawdown_stop_pct") or self.max_drawdown_stop_pct
        if max_dd is not None and self.peak_equity > 0:
            dd = (self.peak_equity - self.equity) / self.peak_equity
            if dd >= max_dd:
                return False
        max_cl = risk.get("max_consecutive_losses") or self.max_consecutive_losses
        if max_cl is not None and self.consecutive_losses >= max_cl:
            return False
        return True

    def open_position(
        self,
        entry_time: pd.Timestamp,
        entry_fill: float,
        stop: float,
        qty: float,
        tp1_level: float,
        chandelier_lookback: int,
        chandelier_atr_mult: float,
        time_stop_bars: int,
        time_stop_min_r: float,
        entry_bar_idx: int,
    ) -> None:
        r_value = entry_fill - stop
        self.position = Position(
            entry_time=entry_time,
            entry_fill=entry_fill,
            stop=stop,
            qty=qty,
            tp1_level=tp1_level,
            tp1_done=False,
            bars_in_trade=0,
            entry_bar_idx=entry_bar_idx,
            chandelier_lookback=chandelier_lookback,
            chandelier_atr_mult=chandelier_atr_mult,
            time_stop_bars=time_stop_bars,
            time_stop_min_r=time_stop_min_r,
            r_value=r_value,
        )
        # Cash reduced at fill (entry cost + fees applied by broker)
        # We don't deduct here; broker records the fill and we update on close.

    def close_position(self, pnl: float, is_win: bool) -> None:
        self.position = None
        self.cash += pnl
        self.equity = self.cash
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

    def snapshot_equity(self, ts: pd.Timestamp) -> None:
        if self.position is not None:
            # Unrealized PnL not applied until close; equity = cash + unrealized
            # For simplicity we keep equity = cash when no position, and on close we set equity = cash
            pass
        self.equity_curve.append((ts, self.equity))
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
