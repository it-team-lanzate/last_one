"""
Paper live con órdenes reales en Bybit Futures Testnet.
Cada cierre de vela 4H: evalúa entrada/salida y coloca market orders en Bybit Testnet.
Estado en data/paper_live_state.json. Posiciones visibles en https://testnet.bybit.com/
Notificaciones por Telegram al abrir/cerrar y resumen semanal.
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import load_config
from src.data.downloader import download_ohlcv
from src.strategy.signals import compute_signals
from src.strategy.squeeze import SqueezeRange
from src.execution.bybit_testnet_broker import BybitTestnetBroker
from src.notifications.telegram import (
    is_configured as telegram_configured,
    notify_position_opened,
    notify_position_closed,
    notify_weekly_summary,
)

log = logging.getLogger(__name__)

# Símbolo CCXT
SYMBOL_CCXT = "BTC/USDT:USDT"
OHLCV_LIMIT = 350
STATE_PATH = Path("data/paper_live_state.json")


def _symbol_to_ccxt(symbol: str) -> str:
    if symbol == "BTCUSDT":
        return "BTC/USDT:USDT"
    if ":" in symbol:
        return symbol
    return symbol.replace("USDT", "/USDT:USDT") if symbol.endswith("USDT") else symbol


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("No se pudo cargar state: %s", e)
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _tp1_level(entry: float, r_val: float, tp1_r: float) -> float:
    return entry + tp1_r * r_val


def _chandelier_trail(high_22: float, atr_14: float, mult: float) -> float:
    return high_22 - mult * atr_14


def _append_closed_trade(state: dict, exit_time: str, entry_price: float, exit_price: float, qty: float, pnl_net: float, exit_reason: str) -> None:
    state.setdefault("closed_trades", [])
    state["closed_trades"].append({
        "exit_time": exit_time,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": qty,
        "pnl_net": pnl_net,
        "exit_reason": exit_reason,
    })
    # Mantener solo últimos 365 días de trades para no inflar el archivo
    cutoff = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
    state["closed_trades"] = [t for t in state["closed_trades"] if (t.get("exit_time") or "")[:10] >= cutoff]


def _weekly_stats_from_trades(trades: list[dict]) -> dict[str, Any]:
    """Calcula n_trades, n_wins, win_rate_pct, total_pnl, profit_factor a partir de lista de trades."""
    n = len(trades)
    n_wins = sum(1 for t in trades if (t.get("pnl_net") or 0) > 0)
    total_pnl = sum(t.get("pnl_net", 0) for t in trades)
    win_rate = (n_wins / n * 100) if n else 0
    gross_profit = sum(t["pnl_net"] for t in trades if t.get("pnl_net", 0) > 0)
    gross_loss = abs(sum(t["pnl_net"] for t in trades if t.get("pnl_net", 0) < 0))
    pf = (gross_profit / gross_loss) if gross_loss else (float("inf") if gross_profit else 0)
    return {"n_trades": n, "n_wins": n_wins, "win_rate_pct": win_rate, "total_pnl": total_pnl, "profit_factor": pf}


def send_weekly_report_manual(state_path: Path | None = None, symbol: str = "BTCUSDT") -> bool:
    """Envía por Telegram el resumen de los últimos 7 días (para cron o ejecución manual)."""
    path = state_path or STATE_PATH
    state = _load_state() if path == STATE_PATH else {}
    if path != STATE_PATH and path.exists():
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    trades = [t for t in state.get("closed_trades", []) if (t.get("exit_time") or "")[:10] >= cutoff]
    stats = _weekly_stats_from_trades(trades)
    return notify_weekly_summary(stats, symbol)


def _maybe_send_weekly(state: dict, symbol: str) -> bool:
    """Si es viernes 10:00 AM Argentina (13:00 UTC) y no se envió esta semana, envía resumen de últimos 7 días."""
    if not telegram_configured():
        return False
    now = datetime.utcnow()
    if now.weekday() != 4:  # no es viernes
        return False
    if now.hour < 13:  # esperar a las 13:00 UTC (10:00 AM Argentina)
        return False
    week_key = now.strftime("%Y-W%W")
    if state.get("last_weekly_sent") == week_key:
        return False
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    trades = [t for t in state.get("closed_trades", []) if (t.get("exit_time") or "")[:10] >= cutoff]
    stats = _weekly_stats_from_trades(trades)
    if notify_weekly_summary(stats, symbol):
        state["last_weekly_sent"] = week_key
        return True
    return False


def _notify_close_and_save(state: dict, broker: Any, pos: dict, exit_reason: str, symbol: str) -> None:
    """Obtiene precio de salida, calcula PnL, guarda trade en state y notifica por Telegram."""
    exit_price = broker.get_last_price()
    entry_price = float(pos["entry_price"])
    qty = float(pos["qty"])
    pnl_net = (exit_price - entry_price) * qty
    bar_ts_str = state.get("last_candle_time", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))
    _append_closed_trade(state, bar_ts_str, entry_price, exit_price, qty, pnl_net, exit_reason)
    notify_position_closed(entry_price, exit_price, qty, pnl_net, exit_reason, symbol=symbol)


def run_live_loop(
    config_path: str | Path,
    poll_interval_seconds: int = 60,
    state_path: Path | None = None,
) -> None:
    """
    Bucle principal: cada poll_interval_seconds comprueba si cerró una vela 4H.
    Si cerró: descarga OHLCV, calcula señales, evalúa entrada/salida y simula órdenes.
    """
    global STATE_PATH
    if state_path is not None:
        STATE_PATH = state_path

    config = load_config(config_path)
    strat = config.get("strategy", {})
    risk = config.get("risk", {})
    pl = config.get("paper_live", config.get("backtest", {}))
    symbol_ccxt = _symbol_to_ccxt(config.get("symbol", "BTCUSDT"))
    timeframe = config.get("timeframe", "4h")
    initial_capital = float(pl.get("initial_capital", 10000.0))

    quality_filter = strat.get("quality_filter", False)
    entry_require_close_above = strat.get("entry_require_close_above", True)
    trend_filter = strat.get("trend_filter", True)
    trend_period = int(strat.get("trend_period", 200))
    min_r_atr_mult = float(strat.get("min_r_atr_mult", 0.5))
    tp1_r = strat.get("tp1_r", 1.5)
    tp1_close_pct = strat.get("tp1_close_pct", 0.4)
    chandelier_lookback = strat.get("chandelier_lookback", 30)
    chandelier_atr_mult = strat.get("chandelier_atr_mult", 2.0)
    trail_activation_r = float(strat.get("trail_activation_r", 0.5))
    time_stop_bars = strat.get("time_stop_bars", 15)
    time_stop_min_r = float(strat.get("time_stop_min_r", 0.5))
    risk_pct = float(risk.get("risk_pct", 0.009))

    broker = BybitTestnetBroker(config)
    symbol_label = config.get("symbol", "BTCUSDT")
    log.info("Paper live (Bybit Testnet) iniciado. Símbolo=%s. Poll=%ss. Ctrl+C para parar.", symbol_ccxt, poll_interval_seconds)

    while True:
        try:
            state = _load_state()
            if _maybe_send_weekly(state, symbol_label):
                _save_state(state)
            last_candle_time = state.get("last_candle_time")
            entered_ranges = state.get("entered_ranges", [])
            position = state.get("position")

            # Sincronizar posición con Bybit Testnet (fuente de verdad)
            bybit_pos = broker.get_position()
            if position is not None and bybit_pos is None:
                log.warning("State dice posición abierta pero Bybit no tiene. Limpiando state.")
                state.pop("position", None)
                position = None
                _save_state(state)
            elif position is None and bybit_pos is not None:
                log.warning("Bybit tiene posición abierta pero state no. Registrando en state (solo qty/entry_price).")
                state["position"] = {
                    "entry_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                    "entry_price": bybit_pos["entry_price"],
                    "stop": 0.0,
                    "r_value": 0.0,
                    "qty": bybit_pos["qty"],
                    "bars_in_trade": 0,
                    "tp1_done": False,
                    "tp1_r": tp1_r,
                    "tp1_close_pct": tp1_close_pct,
                    "chandelier_lookback": chandelier_lookback,
                    "chandelier_atr_mult": chandelier_atr_mult,
                    "trail_activation_r": trail_activation_r,
                    "time_stop_bars": time_stop_bars,
                    "time_stop_min_r": time_stop_min_r,
                }
                position = state["position"]
                _save_state(state)

            # Datos OHLCV recientes (Binance producción, datos públicos)
            df = download_ohlcv(symbol=symbol_ccxt, timeframe=timeframe, limit=OHLCV_LIMIT)
            if df.empty or len(df) < 100:
                log.warning("Pocos datos OHLCV, reintentando más tarde")
                time.sleep(poll_interval_seconds)
                continue

            df = df.sort_values("open_time").reset_index(drop=True)
            df = compute_signals(df, config)
            ranges: list[SqueezeRange] = df.attrs.get("squeeze_ranges", [])
            if "atr_14" not in df.columns:
                time.sleep(poll_interval_seconds)
                continue

            df["high_22"] = df["high"].rolling(chandelier_lookback).max()
            if trend_filter:
                df["trend_sma"] = df["close"].rolling(trend_period).mean()

            last_bar = df.iloc[-1]
            bar_ts = last_bar["open_time"]
            bar_ts_str = pd.Timestamp(bar_ts).strftime("%Y-%m-%dT%H:%M:%S")
            high = float(last_bar["high"])
            low = float(last_bar["low"])
            close = float(last_bar["close"])
            atr_14 = last_bar.get("atr_14")
            high_22 = last_bar.get("high_22")
            tr = last_bar.get("tr")
            sma_tr_20 = last_bar.get("sma_tr_20")

            # Evitar procesar dos veces la misma vela
            if last_candle_time == bar_ts_str:
                balance = broker.get_balance_usdt()
                pos_status = "EN POSICIÓN" if position else "SIN POSICIÓN"
                log.info(
                    "Heartbeat | Vela %s ya procesada | %s | Balance: %.2f USDT | Precio: %.2f | Próximo check en %ss",
                    bar_ts_str, pos_status, balance, close, poll_interval_seconds,
                )
                time.sleep(poll_interval_seconds)
                continue

            log.info(">>> Nueva vela detectada: %s | Close=%.2f | Ranges=%d", bar_ts_str, close, len(ranges))
            state["last_candle_time"] = bar_ts_str
            i = len(df) - 1

            # --- Tenemos posición: evaluar salidas ---
            if position is not None:
                pos = position
                pos["bars_in_trade"] = pos.get("bars_in_trade", 0) + 1
                entry_price = float(pos["entry_price"])
                stop = float(pos["stop"])
                r_val = float(pos["r_value"])
                qty = float(pos["qty"])
                current_r = (close - entry_price) / r_val if r_val else 0

                # Breakeven
                if current_r >= 0.5 and stop < entry_price:
                    pos["stop"] = entry_price
                    stop = entry_price

                # 1) Stop
                if low <= stop:
                    broker.market_sell(qty)
                    state["balance_usdt"] = broker.get_balance_usdt()
                    _notify_close_and_save(state, broker, pos, "stop_hit", symbol_label)
                    state.pop("position", None)
                    state["entered_ranges"] = list(entered_ranges)
                    _save_state(state)
                    log.info("Salida por STOP")
                    time.sleep(poll_interval_seconds)
                    continue

                # 2) TP1 parcial
                tp1_level = _tp1_level(entry_price, r_val, pos.get("tp1_r", tp1_r))
                if not pos.get("tp1_done") and high >= tp1_level:
                    close_qty = round(qty * pos.get("tp1_close_pct", tp1_close_pct), 5)
                    if close_qty > 0:
                        broker.market_sell(close_qty)
                        state["balance_usdt"] = broker.get_balance_usdt()
                    pos["qty"] = round(qty - close_qty, 5)
                    pos["tp1_done"] = True
                    state["position"] = pos
                    _save_state(state)
                    log.info("TP1 parcial: vendido %s, resto %s", close_qty, pos["qty"])
                    time.sleep(poll_interval_seconds)
                    continue

                # 3) Trail
                if pd.notna(high_22) and pd.notna(atr_14) and current_r >= trail_activation_r:
                    trail = _chandelier_trail(high_22, atr_14, pos.get("chandelier_atr_mult", chandelier_atr_mult))
                    if close < trail:
                        broker.market_sell(qty)
                        state["balance_usdt"] = broker.get_balance_usdt()
                        _notify_close_and_save(state, broker, pos, "trail", symbol_label)
                        state.pop("position", None)
                        _save_state(state)
                        log.info("Salida por TRAIL")
                        time.sleep(poll_interval_seconds)
                        continue

                # 4) Time stop
                if pos["bars_in_trade"] >= pos.get("time_stop_bars", time_stop_bars):
                    if current_r < pos.get("time_stop_min_r", time_stop_min_r):
                        broker.market_sell(qty)
                        state["balance_usdt"] = broker.get_balance_usdt()
                        _notify_close_and_save(state, broker, pos, "time_stop", symbol_label)
                        state.pop("position", None)
                        _save_state(state)
                        log.info("Salida por TIME STOP")
                        time.sleep(poll_interval_seconds)
                        continue

                state["position"] = pos
                _save_state(state)
                time.sleep(poll_interval_seconds)
                continue

            # --- Sin posición: evaluar entrada ---
            equity = broker.get_balance_usdt()
            for ri, sr in enumerate(ranges):
                if sr.end_idx >= i:
                    break
                if ri in entered_ranges:
                    continue
                if high < sr.entry_level:
                    continue
                if entry_require_close_above and close <= sr.entry_level:
                    continue
                if trend_filter and "trend_sma" in df.columns:
                    trend_sma = last_bar.get("trend_sma")
                    if pd.isna(trend_sma) or close <= trend_sma:
                        continue
                r_val = sr.entry_level - sr.stop_level
                if pd.isna(atr_14) or atr_14 <= 0 or r_val < min_r_atr_mult * atr_14:
                    continue
                if quality_filter and tr is not None and sma_tr_20 is not None and pd.notna(sma_tr_20) and sma_tr_20 > 0:
                    if tr <= 1.1 * sma_tr_20:
                        continue

                risk_usd = equity * risk_pct
                if r_val <= 0:
                    break
                qty_btc = risk_usd / r_val
                if qty_btc <= 0:
                    break
                try:
                    broker.market_buy(qty_btc)
                    state["balance_usdt"] = broker.get_balance_usdt()
                    state["position"] = {
                        "entry_time": bar_ts_str,
                        "entry_price": close,
                        "stop": sr.stop_level,
                        "r_value": r_val,
                        "qty": qty_btc,
                        "bars_in_trade": 0,
                        "tp1_done": False,
                        "tp1_r": tp1_r,
                        "tp1_close_pct": tp1_close_pct,
                        "chandelier_lookback": chandelier_lookback,
                        "chandelier_atr_mult": chandelier_atr_mult,
                        "trail_activation_r": trail_activation_r,
                        "time_stop_bars": time_stop_bars,
                        "time_stop_min_r": time_stop_min_r,
                    }
                    state["entered_ranges"] = list(entered_ranges) + [ri]
                    _save_state(state)
                    notify_position_opened(close, sr.stop_level, qty_btc, symbol=symbol_label)
                    log.info("ENTRADA LONG: qty=%s @ ~%s, stop=%s, balance=%.2f", qty_btc, close, sr.stop_level, state["balance_usdt"])
                except Exception as e:
                    log.exception("Error al abrir posición: %s", e)
                break

            if state.get("position") is None and position is None:
                log.info("Sin señal de entrada en esta vela. Balance: %.2f USDT. Esperando próxima vela...", equity)
            _save_state(state)
        except KeyboardInterrupt:
            log.info("Paper live detenido por el usuario")
            break
        except Exception as e:
            log.exception("Error en bucle paper live: %s", e)
        time.sleep(poll_interval_seconds)
