"""Unit tests: squeeze detection."""
import pandas as pd
import pytest

from src.strategy.squeeze import detect_squeeze
from src.strategy.indicators import bollinger_bands, keltner_channels, atr


@pytest.fixture
def sample_ohlcv():
    """Sample OHLCV: 100 bars with a clear squeeze (BB inside KC for 8 bars)."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    # Create a volatility squeeze: narrow range for bars 40-50
    high = 100.0 + pd.Series(range(n)) * 0.1 + pd.Series([0.5] * n).sample(frac=1).values
    low = high - 1.0
    close = (high + low) / 2
    # Squeeze: make BB inside KC by having low volatility
    for i in range(40, 48):
        high.iloc[i] = 104.0
        low.iloc[i] = 103.5
        close.iloc[i] = 103.75
    df = pd.DataFrame({
        "open_time": idx,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": [1000.0] * n,
    })
    return df


def test_detect_squeeze_returns_series_and_ranges(sample_ohlcv):
    squeeze_bool, ranges = detect_squeeze(
        sample_ohlcv,
        bb_period=20,
        bb_std=2.0,
        kc_period=20,
        kc_atr_mult=1.5,
        atr_period=14,
        squeeze_min_bars=6,
    )
    assert isinstance(squeeze_bool, pd.Series)
    assert len(squeeze_bool) == len(sample_ohlcv)
    assert isinstance(ranges, list)


def test_squeeze_range_has_entry_and_stop(sample_ohlcv):
    _, ranges = detect_squeeze(
        sample_ohlcv,
        squeeze_min_bars=6,
        entry_atr_mult=0.10,
        stop_range_atr_mult=0.10,
        stop_entry_atr_mult=1.5,
    )
    for r in ranges:
        assert hasattr(r, "entry_level")
        assert hasattr(r, "stop_level")
        assert r.entry_level > r.stop_level
        assert r.range_high >= r.range_low
