"""
Bot de Telegram interactivo para monitorear el estado del paper-live.
Usa long-polling (getUpdates) sin dependencias extra.

Comandos soportados:
  /status  - Estado actual de LONG y SHORT (posición, balance, precio)
  /trades  - Últimos 5 trades cerrados
  /equity  - Resumen de equity y rendimiento
  /help    - Lista de comandos

Ejecutar: python cli.py telegram-bot
"""
import html
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_LONG = Path("data/paper_live_state.json")
STATE_SHORT = Path("data/paper_live_state_short.json")

POLL_TIMEOUT = 30  # segundos de long-polling


def _escape(s: str) -> str:
    return html.escape(str(s))


def _api_call(method: str, params: dict | None = None) -> dict:
    """Llamada genérica a la API de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    if params:
        body = urllib.parse.urlencode(params).encode("utf-8")
    else:
        body = b""
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _send(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    try:
        params = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        _api_call("sendMessage", params)
        return True
    except Exception as e:
        log.warning("Error enviando mensaje: %s", e)
        return False


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_bybit_price() -> float | None:
    """Obtiene precio actual de BTC/USDT desde Bybit (público, sin auth)."""
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("result", {}).get("list", [])
            if items:
                return float(items[0].get("lastPrice", 0))
    except Exception as e:
        log.debug("Error obteniendo precio Bybit público: %s", e)
    return None


def _get_bybit_balance() -> float | None:
    """Obtiene balance de Bybit Testnet si hay claves configuradas."""
    try:
        from src.execution.bybit_testnet_broker import BybitTestnetBroker
        broker = BybitTestnetBroker()
        return broker.get_balance_usdt()
    except Exception as e:
        log.debug("Error obteniendo balance Bybit: %s", e)
    return None


def _format_position(state: dict, label: str, price: float | None) -> str:
    """Formatea el estado de una posición (LONG o SHORT)."""
    pos = state.get("position")
    if pos is None:
        return f"  <b>{label}</b>: Sin posición abierta"

    entry = float(pos.get("entry_price", 0))
    stop = float(pos.get("stop", 0))
    qty = float(pos.get("qty", 0))
    r_val = float(pos.get("r_value", 0))
    bars = pos.get("bars_in_trade", 0)
    tp1_done = pos.get("tp1_done", False)
    entry_time = pos.get("entry_time", "?")

    lines = [f"  <b>{label}</b>: EN POSICIÓN"]
    lines.append(f"  • Entrada: {entry:,.2f} USDT @ {entry_time}")
    lines.append(f"  • Stop: {stop:,.2f} USDT")
    lines.append(f"  • Qty: {qty:.5f} BTC")
    lines.append(f"  • Velas en trade: {bars}")
    lines.append(f"  • TP1 parcial: {'Sí' if tp1_done else 'No'}")

    if price and r_val > 0:
        if label == "SHORT":
            current_r = (entry - price) / r_val
            pnl = (entry - price) * qty
        else:
            current_r = (price - entry) / r_val
            pnl = (price - entry) * qty
        emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        lines.append(f"  • R actual: {current_r:.2f}R")
        lines.append(f"  • PnL flotante: {emoji} {pnl_str} USDT")

    return "\n".join(lines)


def _handle_status(chat_id: str) -> None:
    """Comando /status: estado de ambas estrategias."""
    state_long = _load_state(STATE_LONG)
    state_short = _load_state(STATE_SHORT)
    price = _get_bybit_price()
    balance = _get_bybit_balance()

    lines = ["📊 <b>Estado actual</b>\n"]

    if price:
        lines.append(f"💰 BTC/USDT: <b>{price:,.2f}</b>")
    if balance is not None:
        lines.append(f"🏦 Balance Bybit: <b>{balance:,.2f} USDT</b>")

    lines.append("")
    lines.append(_format_position(state_long, "LONG", price))
    lines.append("")
    lines.append(_format_position(state_short, "SHORT", price))

    # Última vela procesada
    last_long = state_long.get("last_candle_time", "—")
    last_short = state_short.get("last_candle_time", "—")
    lines.append("")
    lines.append(f"🕐 Última vela LONG: {_escape(last_long)}")
    lines.append(f"🕐 Última vela SHORT: {_escape(last_short)}")

    _send(chat_id, "\n".join(lines))


def _handle_trades(chat_id: str) -> None:
    """Comando /trades: últimos trades cerrados de ambas estrategias."""
    state_long = _load_state(STATE_LONG)
    state_short = _load_state(STATE_SHORT)

    trades_long = state_long.get("closed_trades", [])
    trades_short = state_short.get("closed_trades", [])

    def _fmt_trades(trades: list, label: str) -> str:
        if not trades:
            return f"  <b>{label}</b>: Sin trades registrados"
        recent = trades[-5:]  # últimos 5
        lines = [f"  <b>{label}</b> (últimos {len(recent)}):"]
        for t in reversed(recent):
            pnl = t.get("pnl_net", 0)
            emoji = "✅" if pnl > 0 else "❌"
            pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
            entry = t.get("entry_price", 0)
            exit_p = t.get("exit_price", 0)
            reason = t.get("exit_reason", "?")
            date = (t.get("exit_time") or "?")[:16]
            lines.append(
                f"  {emoji} {date} | {entry:,.0f}→{exit_p:,.0f} | "
                f"{pnl_str} USDT | {reason}"
            )
        return "\n".join(lines)

    lines = ["📋 <b>Últimos trades</b>\n"]
    lines.append(_fmt_trades(trades_long, "LONG"))
    lines.append("")
    lines.append(_fmt_trades(trades_short, "SHORT"))

    # Estadísticas 7 días
    cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_long = [t for t in trades_long if (t.get("exit_time") or "")[:10] >= cutoff]
    week_short = [t for t in trades_short if (t.get("exit_time") or "")[:10] >= cutoff]
    pnl_week = sum(t.get("pnl_net", 0) for t in week_long + week_short)
    n_week = len(week_long) + len(week_short)
    pnl_str = f"+{pnl_week:.2f}" if pnl_week >= 0 else f"{pnl_week:.2f}"
    lines.append(f"\n📅 <b>Últimos 7 días</b>: {n_week} trades, PnL: {pnl_str} USDT")

    _send(chat_id, "\n".join(lines))


def _handle_equity(chat_id: str) -> None:
    """Comando /equity: resumen de rendimiento."""
    state_long = _load_state(STATE_LONG)
    state_short = _load_state(STATE_SHORT)
    balance = _get_bybit_balance()

    def _stats(trades: list) -> dict:
        n = len(trades)
        if not n:
            return {"n": 0, "pnl": 0, "wins": 0, "wr": 0, "best": 0, "worst": 0}
        wins = sum(1 for t in trades if t.get("pnl_net", 0) > 0)
        pnl = sum(t.get("pnl_net", 0) for t in trades)
        best = max(t.get("pnl_net", 0) for t in trades)
        worst = min(t.get("pnl_net", 0) for t in trades)
        return {"n": n, "pnl": pnl, "wins": wins, "wr": wins / n * 100, "best": best, "worst": worst}

    trades_long = state_long.get("closed_trades", [])
    trades_short = state_short.get("closed_trades", [])
    sl = _stats(trades_long)
    ss = _stats(trades_short)
    combined_pnl = sl["pnl"] + ss["pnl"]

    lines = ["📈 <b>Resumen de rendimiento</b>\n"]

    if balance is not None:
        lines.append(f"🏦 Balance actual: <b>{balance:,.2f} USDT</b>")
        lines.append("")

    def _fmt_stats(s: dict, label: str) -> str:
        if s["n"] == 0:
            return f"  <b>{label}</b>: Sin trades"
        pnl_str = f"+{s['pnl']:.2f}" if s["pnl"] >= 0 else f"{s['pnl']:.2f}"
        return (
            f"  <b>{label}</b>: {s['n']} trades | {s['wins']} wins ({s['wr']:.0f}%)\n"
            f"  PnL total: {pnl_str} USDT\n"
            f"  Mejor: +{s['best']:.2f} | Peor: {s['worst']:.2f}"
        )

    lines.append(_fmt_stats(sl, "LONG"))
    lines.append("")
    lines.append(_fmt_stats(ss, "SHORT"))
    lines.append("")

    emoji = "🟢" if combined_pnl >= 0 else "🔴"
    cpnl_str = f"+{combined_pnl:.2f}" if combined_pnl >= 0 else f"{combined_pnl:.2f}"
    lines.append(f"{emoji} <b>PnL combinado: {cpnl_str} USDT</b>")

    _send(chat_id, "\n".join(lines))


def _handle_help(chat_id: str) -> None:
    """Comando /help."""
    msg = (
        "🤖 <b>Comandos disponibles</b>\n\n"
        "/status - Estado actual (posiciones, balance, precio)\n"
        "/trades - Últimos 5 trades por estrategia\n"
        "/equity - Resumen de rendimiento total\n"
        "/help - Este mensaje"
    )
    _send(chat_id, msg)


COMMANDS = {
    "/status": _handle_status,
    "/trades": _handle_trades,
    "/equity": _handle_equity,
    "/help": _handle_help,
    "/start": _handle_help,
}


def run_bot() -> None:
    """
    Bucle principal del bot. Long-polling con getUpdates.
    Solo responde a mensajes del TELEGRAM_CHAT_ID configurado.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID deben estar configurados en .env")
        return

    # Limpiar webhook, conexiones pendientes y updates para evitar conflictos (409)
    try:
        _api_call("deleteWebhook", {"drop_pending_updates": True})
        log.info("Webhook limpiado")
    except Exception as e:
        log.warning("Error limpiando webhook: %s", e)

    # Forzar cierre de conexiones long-poll previas: hacer getUpdates con timeout=0
    for _ in range(3):
        try:
            _api_call("getUpdates", {"timeout": 0, "limit": 1})
            break
        except Exception:
            time.sleep(2)
    time.sleep(2)  # Esperar a que Telegram libere la conexión anterior

    log.info("Telegram bot iniciado. Esperando comandos de chat_id=%s...", TELEGRAM_CHAT_ID)
    _send(TELEGRAM_CHAT_ID, "🤖 Bot de monitoreo iniciado.\nEscribe /help para ver comandos.")

    offset = 0
    consecutive_errors = 0
    use_long_poll = True  # Empezar con long-polling, cambiar a short si hay 409
    while True:
        try:
            poll_timeout = POLL_TIMEOUT if use_long_poll else 1
            params = {
                "offset": offset,
                "timeout": poll_timeout,
                "allowed_updates": '["message"]',
            }
            result = _api_call("getUpdates", params)
            if not use_long_poll and consecutive_errors == 0:
                # Intentar volver a long-polling tras 5 ciclos exitosos sin 409
                pass
            consecutive_errors = 0
            updates = result.get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()

                # Solo responder al chat autorizado
                if chat_id != TELEGRAM_CHAT_ID:
                    log.debug("Ignorando mensaje de chat_id=%s (no autorizado)", chat_id)
                    continue

                # Extraer comando (ignorar @botname si existe)
                cmd = text.split()[0].split("@")[0].lower() if text else ""
                handler = COMMANDS.get(cmd)

                if handler:
                    log.info("Comando recibido: %s", cmd)
                    try:
                        handler(chat_id)
                    except Exception as e:
                        log.exception("Error ejecutando comando %s: %s", cmd, e)
                        _send(chat_id, f"⚠️ Error ejecutando {_escape(cmd)}: {_escape(str(e))}")
                elif text.startswith("/"):
                    _send(chat_id, f"❓ Comando desconocido: {_escape(cmd)}\nEscribe /help para ver opciones.")

        except KeyboardInterrupt:
            log.info("Telegram bot detenido por el usuario")
            _send(TELEGRAM_CHAT_ID, "🛑 Bot de monitoreo detenido.")
            break
        except Exception as e:
            consecutive_errors += 1
            err_str = str(e)
            # 409 Conflict = otro proceso usando getUpdates → cambiar a short-polling
            if "409" in err_str:
                if use_long_poll:
                    log.warning(
                        "409 Conflict: otro proceso usa getUpdates. "
                        "Cambiando a short-polling (menos responsivo pero funcional)."
                    )
                    use_long_poll = False
                wait = 3  # short-polling: reintentar rápido
            else:
                wait = min(5 * consecutive_errors, 60)
            log.warning("Error en bot loop (%d): %s. Retry en %ds...", consecutive_errors, e, wait)
            time.sleep(wait)
