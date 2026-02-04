"""Bollinger Bands, Keltner Channels, ATR, TrueRange."""
import pandas as pd
import numpy as np


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (middle, upper, lower)."""
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return middle, upper, lower


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """ATR(period)."""
    tr = true_range(high, low, close)
    return tr.rolling(period).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """ATR(period)."""
    return atr_series(high, low, close, period)


def keltner_channels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
    atr_mult: float = 1.5,
    atr_period: int | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (middle, upper, lower). KC middle = EMA(close, period), width = atr_mult * ATR."""
    if atr_period is None:
        atr_period = period
    middle = close.ewm(span=period, adjust=False).mean()
    atr_val = atr_series(high, low, close, atr_period)
    upper = middle + atr_mult * atr_val
    lower = middle - atr_mult * atr_val
    return middle, upper, lower
