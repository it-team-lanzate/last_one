"""Feed: get OHLCV from cache or download and cache."""
import logging
from pathlib import Path

import pandas as pd

from .cache import cache_ohlcv, get_cached_ohlcv
from .downloader import download_ohlcv_range

log = logging.getLogger(__name__)
DEFAULT_CACHE_DIR = Path("data/cache")


def _symbol_ccxt(symbol: str) -> str:
    if symbol == "BTCUSDT":
        return "BTC/USDT:USDT"
    if "USDT" in symbol and "/" not in symbol:
        base = symbol.replace("USDT", "")
        return f"{base}/USDT:USDT"
    return symbol


def get_ohlcv_feed(
    symbol: str = "BTCUSDT",
    timeframe: str = "4h",
    start_date: str | None = None,
    end_date: str | None = None,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Return OHLCV DataFrame: from cache if present and use_cache=True,
    else download and cache.
    """
    cache_dir = Path(cache_dir)
    if use_cache and start_date and end_date:
        cached = get_cached_ohlcv(symbol, timeframe, start_date, end_date, cache_dir)
        if cached is not None and not cached.empty:
            return cached
    ccxt_symbol = _symbol_ccxt(symbol)
    try:
        df = download_ohlcv_range(
            symbol=ccxt_symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        log.error("get_ohlcv_feed: error descargando OHLCV: %s", e)
        raise
    if df.empty:
        return df
    if use_cache and start_date and end_date:
        cache_ohlcv(df, symbol, timeframe, start_date, end_date, cache_dir)
    return df
