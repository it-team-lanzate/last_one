"""
Download OHLCV from Binance USD-M Futures.
Usa API pública (fetch_ohlcv no requiere keys). Con reintentos para errores de red.
"""
import logging
import time
from typing import Any

import ccxt
import pandas as pd

log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos entre reintentos


def _get_binance_exchange(sandbox: bool = False) -> ccxt.Exchange:
    """Binance USD-M Futures. OHLCV es público, no requiere API keys."""
    exchange = ccxt.binance({"options": {"defaultType": "future"}})
    if sandbox:
        exchange.set_sandbox_mode(True)
    return exchange


def _retry_ohlcv(fn, description: str = "fetch_ohlcv") -> Any:
    """Reintenta fn() ante RequestTimeout, NetworkError."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
            if attempt < MAX_RETRIES:
                log.warning(
                    "%s: intento %d/%d falló (%s). Reintentando en %ds...",
                    description, attempt, MAX_RETRIES, type(e).__name__, RETRY_DELAY,
                )
                time.sleep(RETRY_DELAY)
            else:
                log.error("%s: %d intentos agotados.", description, MAX_RETRIES)
                raise


def _to_dataframe(raw: list) -> pd.DataFrame:
    """Convierte [[ts,o,h,l,c,v],...] a DataFrame."""
    df = pd.DataFrame(
        raw,
        columns=["open_time", "open", "high", "low", "close", "volume"],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def download_ohlcv(
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "4h",
    since: int | None = None,
    limit: int = 1000,
    config_path: str | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV. Usa Binance producción (público); si falla, intenta testnet.
    symbol: ccxt format e.g. BTC/USDT:USDT
    Returns DataFrame con columnas: open_time, open, high, low, close, volume
    """
    def _fetch(ex: ccxt.Exchange) -> pd.DataFrame:
        raw = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        return _to_dataframe(raw)

    # 1) Intentar Binance producción (sin sandbox) - datos públicos
    try:
        exchange = _get_binance_exchange(sandbox=False)
        df = _retry_ohlcv(lambda: _fetch(exchange), "download_ohlcv (prod)")
        if not df.empty:
            return df
    except Exception as e:
        log.warning("Binance producción falló: %s. Intentando testnet...", e)

    # 2) Fallback: Binance testnet (por si prod tiene restricciones)
    try:
        exchange = _get_binance_exchange(sandbox=True)
        return _retry_ohlcv(lambda: _fetch(exchange), "download_ohlcv (testnet)")
    except Exception as e:
        log.error("download_ohlcv falló tras reintentos: %s", e)
        raise


def download_ohlcv_range(
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "4h",
    start_date: str | None = None,
    end_date: str | None = None,
    limit_per_request: int = 1000,
) -> pd.DataFrame:
    """Download OHLCV for a date range by paginating. Con reintentos por request."""
    all_dfs = []
    since = None
    if start_date:
        since = int(pd.Timestamp(start_date).tz_localize("UTC").value // 1_000_000)

    while True:
        try:
            df = download_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=limit_per_request,
            )
        except Exception as e:
            log.error("Error en download_ohlcv_range durante paginación: %s", e)
            break
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
