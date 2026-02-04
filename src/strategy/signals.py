"""
Signal state and entry/exit levels.
Entry: buy-stop at range_high + 0.10*ATR(14).
Optional quality filter: TrueRange > 1.1 * SMA(TrueRange, 20) at entry.
TP1: +1R close 50%. Rest: Chandelier trail = highest_high(22) - 3*ATR(14). Time stop: 6 bars no +0.5R.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from .indicators import atr, true_range
from .squeeze import SqueezeRange, detect_squeeze


class ExitReason(str, Enum):
    TP1 = "tp1"
    TRAIL = "trail"
    TIME_STOP = "time_stop"
    STOP_HIT = "stop_hit"


@dataclass
class SignalState:
    """Per-bar state for backtest: entry/stop/tp1/trail levels and active squeeze range."""
    entry: float | None = None
    stop: float | None = None
    tp1_level: float | None = None
    tp1_done: bool = False
    squeeze_range: SqueezeRange | None = None
    bars_in_trade: int = 0
    entry_bar_idx: int | None = None


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def compute_signals(
    df: pd.DataFrame,
    params: dict[str, Any],
) -> pd.DataFrame:
    """
    Add strategy columns to df:
    - bb_*, kc_*, atr_14, tr, sma_tr_20
    - squeeze (bool)
    - For each bar we don't compute full state machine here; backtest engine will use
      detect_squeeze ranges + levels for entry/exit.
    This function adds indicator columns and a column 'squeeze_ranges' as list of
    (end_idx, range_high, range_low, entry_level, stop_level) for ranges that end at or before row.
    Actually we only need indicators + squeeze bool; engine will compute entry/stop from ranges.
    So we add: atr_14, tr, sma_tr_20 (for quality filter), squeeze.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    ind = params.get("indicators", {})
    strat = params.get("strategy", {})

    bb_p = ind.get("bb_period", 20)
    bb_std = ind.get("bb_std", 2.0)
    kc_p = ind.get("kc_period", 20)
    kc_atr_mult = ind.get("kc_atr_mult", 1.5)
    atr_p = ind.get("atr_period", 14)
    atr_stops = ind.get("atr_period_stops", 14)

    from .indicators import bollinger_bands, keltner_channels
    bb_m, bb_u, bb_l = bollinger_bands(close, bb_p, bb_std)
    kc_m, kc_u, kc_l = keltner_channels(high, low, close, kc_p, kc_atr_mult, atr_p)
    atr_14 = atr(high, low, close, atr_stops)
    tr = true_range(high, low, close)
    sma_tr_20 = _sma(tr, 20)

    squeeze_bool, ranges = detect_squeeze(
        df,
        bb_period=bb_p,
        bb_std=bb_std,
        kc_period=kc_p,
        kc_atr_mult=kc_atr_mult,
        atr_period=atr_p,
        squeeze_min_bars=strat.get("squeeze_min_bars", 6),
        entry_atr_mult=strat.get("entry_atr_mult", 0.10),
        stop_range_atr_mult=strat.get("stop_range_atr_mult", 0.10),
        stop_entry_atr_mult=strat.get("stop_entry_atr_mult", 1.5),
        squeeze_mode=strat.get("squeeze_mode", "width"),
        squeeze_width_ratio=float(strat.get("squeeze_width_ratio", 1.5)),
        squeeze_percentile_max=strat.get("squeeze_percentile_max"),
        squeeze_percentile_lookback=int(strat.get("squeeze_percentile_lookback", 100)),
    )

    out = df.copy()
    out["bb_mid"] = bb_m
    out["bb_upper"] = bb_u
    out["bb_lower"] = bb_l
    out["kc_upper"] = kc_u
    out["kc_lower"] = kc_l
    out["atr_14"] = atr_14
    out["tr"] = tr
    out["sma_tr_20"] = sma_tr_20
    out["squeeze"] = squeeze_bool
    # Trend filter: SMA(close, trend_period) - only long when close > trend_sma
    trend_period = int(strat.get("trend_period", 200))
    out["trend_sma"] = close.rolling(trend_period).mean()

    # Store ranges as list of dicts per row: for bar i, which squeeze range (if any) is "active"
    # for breakout (i.e. range ended at i-1 or earlier, entry above range_high). Engine will use
    # ranges list directly; we attach it to df as a global attribute for convenience.
    out.attrs["squeeze_ranges"] = ranges
    return out
