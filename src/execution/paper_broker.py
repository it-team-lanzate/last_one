"""
Paper broker: no real orders. Simulate fills with OHLCV + slippage.
Used by backtest and paper-live. For paper-live we poll 4H close and simulate.
"""
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .fees import FeeSlippageParams, apply_fees_slippage
from .portfolio import Portfolio, Position


@dataclass
class Fill:
    side: str  # "buy" | "sell"
    price: float
    qty: float
    fee: float
    timestamp: pd.Timestamp
    is_entry: bool


def size_position(
    risk_pct: float,
    capital: float,
    entry_fill: float,
    stop: float,
) -> float:
    """qty = risk_usd / (entry_fill - stop). risk_usd = capital * risk_pct."""
    risk_usd = capital * risk_pct
    r_dist = entry_fill - stop
    if r_dist <= 0:
        return 0.0
    return risk_usd / r_dist


class PaperBroker:
    def __init__(
        self,
        config: dict[str, Any],
        initial_capital: float,
    ) -> None:
        self.config = config
        self.fee_params = FeeSlippageParams.from_config(config)
        self.portfolio = Portfolio(
            initial_capital=initial_capital,
            cash=initial_capital,
            equity=initial_capital,
        )
        risk = config.get("risk", {})
        self.portfolio.max_drawdown_stop_pct = risk.get("max_drawdown_stop_pct")
        self.portfolio.max_consecutive_losses = risk.get("max_consecutive_losses")
        self.risk_pct = risk.get("risk_pct", 0.01)
        self.risk_use_initial_capital = risk.get("risk_use_initial_capital", False)

    def can_open(self) -> bool:
        return self.portfolio.can_open(self.config)

    def open_long(
        self,
        bar: pd.Series,
        entry_level: float,
        stop: float,
        tp1_level: float,
        entry_bar_idx: int,
        chandelier_lookback: int,
        chandelier_atr_mult: float,
        time_stop_bars: int,
        time_stop_min_r: float,
    ) -> Position | None:
        if not self.can_open():
            return None
        entry_fill, _, fee_entry, _ = apply_fees_slippage(
            entry_level, entry_level, 1.0, self.fee_params
        )
        capital = self.portfolio.initial_capital if self.risk_use_initial_capital else self.portfolio.equity
        qty = size_position(
            self.risk_pct,
            capital,
            entry_fill,
            stop,
        )
        if qty <= 0:
            return None
        _, _, fee_e, _ = apply_fees_slippage(entry_fill, entry_fill, qty, self.fee_params)
        cost = entry_fill * qty + fee_e
        if cost > self.portfolio.cash:
            return None
        self.portfolio.cash -= cost
        self.portfolio.open_position(
            entry_time=bar["open_time"],
            entry_fill=entry_fill,
            stop=stop,
            qty=qty,
            tp1_level=tp1_level,
            chandelier_lookback=chandelier_lookback,
            chandelier_atr_mult=chandelier_atr_mult,
            time_stop_bars=time_stop_bars,
            time_stop_min_r=time_stop_min_r,
            entry_bar_idx=entry_bar_idx,
        )
        return self.portfolio.position

    def close_long(
        self,
        bar: pd.Series,
        exit_price: float,
    ) -> tuple[float, float, float]:
        """Returns (pnl_net, fee_exit, exit_fill). Al cerrar sumamos ingresos (exit_fill*qty - fee_exit) a cash."""
        pos = self.portfolio.position
        if pos is None:
            return 0.0, 0.0, exit_price
        entry_fill, exit_fill, fee_entry, fee_exit = apply_fees_slippage(
            pos.entry_fill, exit_price, pos.qty, self.fee_params
        )
        proceeds = exit_fill * pos.qty - fee_exit
        pnl_net = (exit_fill - entry_fill) * pos.qty - fee_entry - fee_exit
        is_win = pnl_net > 0
        self.portfolio.close_position(proceeds, is_win)
        return pnl_net, fee_exit, exit_fill

    def reduce_position(self, close_qty: float, exit_price: float, fee_exit: float) -> float:
        """Partial close (e.g. TP1 50%). Returns pnl_net for the closed part."""
        pos = self.portfolio.position
        if pos is None or close_qty <= 0 or close_qty >= pos.qty:
            return 0.0
        pnl_net = (exit_price - pos.entry_fill) * close_qty - fee_exit
        self.portfolio.cash += pnl_net + pos.entry_fill * close_qty
        pos.qty -= close_qty
        pos.tp1_done = True
        return pnl_net
