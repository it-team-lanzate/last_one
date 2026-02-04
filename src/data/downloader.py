"""Download OHLCV from Binance USD-M Futures Testnet via ccxt."""
import os

import ccxt
import pandas as pd

from dotenv import load_dotenv
load_dotenv()

BINANCE_FUTURES_TESTNET = {
    "apiKey": os.getenv("BINANCE_FUTURES_TESTNET_API_KEY", ""),
    "secret": os.getenv("BINANCE_FUTURES_TESTNET_SECRET", ""),
    "options": {"defaultType": "future"},
    "urls": {
        "api": {
            "fapiPublic": "https://testnet.binancefuture.com/fapi/v1",
            "fapiPrivate": "https://testnet.binancefuture.com/fapi/v1",
        }
    },
}


def get_exchange() -> ccxt.Exchange:
    """Return ccxt Binance Futures Testnet exchange (read-only for fetch_ohlcv)."""
    exchange = ccxt.binance(
        {
            "apiKey": BINANCE_FUTURES_TESTNET["apiKey"],
            "secret": BINANCE_FUTURES_TESTNET["secret"],
            "options": {"defaultType": "future"},
            "urls": {
                "api": {
                    "fapiPublic": "https://testnet.binancefuture.com/fapi/v1",
                    "fapiPrivate": "https://testnet.binancefuture.com/fapi/v1",
                }
            },
        }
    )
    exchange.set_sandbox_mode(True)
    return exchange


def download_ohlcv(
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "4h",
    since: int | None = None,
    limit: int = 1000,
    config_path: str | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV from Binance Futures Testnet.
    symbol: ccxt format e.g. BTC/USDT:USDT
    Returns DataFrame with columns: open_time, open, high, low, close, volume
    """
    exchange = get_exchange()
    # ccxt returns [[timestamp, o, h, l, c, v], ...]
    raw = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    df = pd.DataFrame(
        raw,
        columns=["open_time", "open", "high", "low", "close", "volume"],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def download_ohlcv_range(
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "4h",
    start_date: str | None = None,
    end_date: str | None = None,
    limit_per_request: int = 1000,
) -> pd.DataFrame:
    """Download OHLCV for a date range by paginating."""
    all_dfs = []
    since = None
    if start_date:
        since = int(pd.Timestamp(start_date).tz_localize("UTC").value // 1_000_000)
    while True:
        df = download_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            limit=limit_per_request,
        )
        if df.empty:
            break
        all_dfs.append(df)
        since = int(df["open_time"].iloc[-1].value // 1_000_000) + 1
        if end_date and df["open_time"].iloc[-1] >= pd.Timestamp(end_date).tz_localize("UTC"):
            break
        if len(df) < limit_per_request:
            break
    if not all_dfs:
        return pd.DataFrame(
            columns=["open_time", "open", "high", "low", "close", "volume"]
        )
    out = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=["open_time"])
    out = out.sort_values("open_time").reset_index(drop=True)
    if end_date:
        end_ts = pd.Timestamp(end_date).tz_localize("UTC")
        out = out[out["open_time"] <= end_ts]
    if start_date:
        start_ts = pd.Timestamp(start_date).tz_localize("UTC")
        out = out[out["open_time"] >= start_ts]
    return out
