"""Local cache for OHLCV (Parquet) keyed by symbol, timeframe, start, end."""
from pathlib import Path

import pandas as pd

DEFAULT_CACHE_DIR = Path("data/cache")


def _cache_path(
    cache_dir: Path,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> Path:
    safe = f"{symbol.replace('/', '_')}_{timeframe}_{start_date}_{end_date}.parquet"
    return cache_dir / safe


def get_cached_ohlcv(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> pd.DataFrame | None:
    path = _cache_path(
        Path(cache_dir), symbol, timeframe, start_date, end_date
    )
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def cache_ohlcv(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> Path:
    path = _cache_path(
        Path(cache_dir), symbol, timeframe, start_date, end_date
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path
