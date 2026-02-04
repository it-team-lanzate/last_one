"""
Squeeze: BB inside KC for >= squeeze_min_bars.
range_high = max(high) over squeeze, range_low = min(low) over squeeze.
"""
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .indicators import bollinger_bands, keltner_channels, atr


@dataclass
class SqueezeRange:
    start_idx: int
    end_idx: int
    range_high: float
    range_low: float
    entry_level: float
    stop_level: float


def detect_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_atr_mult: float = 1.5,
    atr_period: int = 14,
    squeeze_min_bars: int = 6,
    entry_atr_mult: float = 0.10,
    stop_range_atr_mult: float = 0.10,
    stop_entry_atr_mult: float = 1.5,
    squeeze_mode: str = "width",
    squeeze_width_ratio: float = 1.5,
    squeeze_percentile_max: int | None = None,
    squeeze_percentile_lookback: int = 100,
) -> tuple[pd.Series, list[SqueezeRange]]:
    """
    Returns (squeeze_bool series, list of SqueezeRange for each squeeze block).
    squeeze_mode: "inside" = BB inside KC (strict). "width" = BB width < KC width * ratio. "relative" = BB width < SMA(BB width, 50).
    squeeze_width_ratio: in "width" mode only; squeeze when bb_width < kc_width * ratio.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    _, bb_upper, bb_lower = bollinger_bands(close, bb_period, bb_std)
    _, kc_upper, kc_lower = keltner_channels(
        high, low, close, kc_period, kc_atr_mult, atr_period
    )
    atr_14 = atr(high, low, close, atr_period)

    bb_width = bb_upper - bb_lower
    kc_width = kc_upper - kc_lower

    if squeeze_mode == "inside":
        bb_inside = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    elif squeeze_mode == "relative":
        # Squeeze when BB width below its own rolling mean (or below percentile for stronger contraction)
        if squeeze_percentile_max is not None and squeeze_percentile_lookback >= 20:
            # Stronger: only when BB width in bottom X% of last lookback (e.g. 40 = bottom 40%)
            q = squeeze_percentile_max / 100.0
            bb_width_pct = bb_width.rolling(squeeze_percentile_lookback, min_periods=50).quantile(q)
            bb_inside = (bb_width < bb_width_pct) & bb_width.notna() & bb_width_pct.notna()
        else:
            bb_width_ma = bb_width.rolling(50, min_periods=20).mean()
            bb_inside = (bb_width < bb_width_ma) & bb_width.notna() & bb_width_ma.notna()
    else:
        # width: squeeze when BB width < KC width * ratio
        threshold = kc_width * squeeze_width_ratio
        bb_inside = (bb_width < threshold) & bb_width.notna() & threshold.notna()

    # Consecutive squeeze: mark runs of True with length >= squeeze_min_bars
    squeeze_bool = pd.Series(False, index=df.index)
    ranges: list[SqueezeRange] = []

    i = 0
    n = len(df)
    while i < n:
        if not bb_inside.iloc[i]:
            i += 1
            continue
        start_idx = i
        while i < n and bb_inside.iloc[i]:
            i += 1
        end_idx = i - 1
        run_len = end_idx - start_idx + 1
        if run_len < squeeze_min_bars:
            continue
        # Mark this run as squeeze
        squeeze_bool.iloc[start_idx : end_idx + 1] = True
        # Range over squeeze bars (use .iloc for slice)
        range_high = high.iloc[start_idx : end_idx + 1].max()
        range_low = low.iloc[start_idx : end_idx + 1].min()
        atr_val = atr_14.iloc[end_idx]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        entry_level = range_high + entry_atr_mult * atr_val
        stop_a = range_low - stop_range_atr_mult * atr_val
        stop_b = entry_level - stop_entry_atr_mult * atr_val
        stop_level = min(stop_a, stop_b)
        ranges.append(
            SqueezeRange(
                start_idx=start_idx,
                end_idx=end_idx,
                range_high=float(range_high),
                range_low=float(range_low),
                entry_level=float(entry_level),
                stop_level=float(stop_level),
            )
        )
    return squeeze_bool, ranges


def squeeze_ranges(
    df: pd.DataFrame,
    params: dict[str, Any],
) -> tuple[pd.Series, list[SqueezeRange]]:
    """Convenience: run detect_squeeze with params dict (from config)."""
    ind = params.get("indicators", {})
    strat = params.get("strategy", {})
    return detect_squeeze(
        df,
        bb_period=ind.get("bb_period", 20),
        bb_std=ind.get("bb_std", 2.0),
        kc_period=ind.get("kc_period", 20),
        kc_atr_mult=ind.get("kc_atr_mult", 1.5),
        atr_period=ind.get("atr_period", 14),
        squeeze_min_bars=strat.get("squeeze_min_bars", 6),
        entry_atr_mult=strat.get("entry_atr_mult", 0.10),
        stop_range_atr_mult=strat.get("stop_range_atr_mult", 0.10),
        stop_entry_atr_mult=strat.get("stop_entry_atr_mult", 1.5),
        squeeze_mode=strat.get("squeeze_mode", "width"),
        squeeze_width_ratio=float(strat.get("squeeze_width_ratio", 1.5)),
        squeeze_percentile_max=strat.get("squeeze_percentile_max"),
        squeeze_percentile_lookback=int(strat.get("squeeze_percentile_lookback", 100)),
    )
