"""
Notificaciones por Telegram (Bot API).
Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env.
"""
import html
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Envía un mensaje al chat configurado.
    Si parse_mode=HTML, escapa solo los caracteres que no sean tags.
    """
    if not is_configured():
        log.debug("Telegram no configurado (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID), no se envía mensaje")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        data["parse_mode"] = parse_mode
    try:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                log.warning("Telegram API status %s: %s", resp.status, resp.read())
                return False
            return True
    except Exception as e:
        log.warning("Error enviando Telegram: %s", e)
        return False


def escape_html(s: str) -> str:
    return html.escape(str(s))


def notify_position_opened(entry_price: float, stop: float, qty: float, symbol: str = "BTCUSDT") -> bool:
    """Notifica apertura de posición LONG."""
    msg = (
        "🟢 <b>LONG abierto</b>\n"
        f"• Símbolo: {escape_html(symbol)}\n"
        f"• Entrada: {escape_html(f'{entry_price:,.2f}')}\n"
        f"• Stop: {escape_html(f'{stop:,.2f}')}\n"
        f"• Cantidad: {escape_html(f'{qty:.5f}')}"
    )
    return send_message(msg)


def notify_position_closed(
    entry_price: float,
    exit_price: float,
    qty: float,
    pnl_net: float,
    exit_reason: str,
    symbol: str = "BTCUSDT",
) -> bool:
    """Notifica cierre de posición indicando si fue exitosa o no."""
    success = pnl_net > 0
    emoji = "✅" if success else "❌"
    result = "Éxito" if success else "Pérdida"
    pnl_str = f"+{pnl_net:.2f}" if pnl_net >= 0 else f"{pnl_net:.2f}"
    msg = (
        f"{emoji} <b>Posición cerrada</b> ({result})\n"
        f"• Símbolo: {escape_html(symbol)}\n"
        f"• Entrada: {escape_html(f'{entry_price:,.2f}')} → Salida: {escape_html(f'{exit_price:,.2f}')}\n"
        f"• Cantidad: {escape_html(f'{qty:.5f}')}\n"
        f"• PnL neto: {escape_html(pnl_str)} USDT\n"
        f"• Motivo: {escape_html(exit_reason)}"
    )
    return send_message(msg)


def notify_weekly_summary(stats: dict[str, Any], symbol: str = "BTCUSDT") -> bool:
    """
    Envía resumen semanal. stats debe tener:
    n_trades, n_wins, win_rate_pct, total_pnl, profit_factor (opcional), max_dd_pct (opcional)
    """
    n = stats.get("n_trades", 0)
    if n == 0:
        msg = (
            "📊 <b>Resumen semanal</b>\n"
            f"• Símbolo: {escape_html(symbol)}\n"
            "• Sin operaciones en los últimos 7 días."
        )
    else:
        wr = stats.get("win_rate_pct", 0)
        total = stats.get("total_pnl", 0)
        pf = stats.get("profit_factor")
        total_str = f"+{total:.2f}" if total >= 0 else f"{total:.2f}"
        msg = (
            "📊 <b>Resumen semanal</b>\n"
            f"• Símbolo: {escape_html(symbol)}\n"
            f"• Operaciones: {n} ({stats.get('n_wins', 0)} ganadoras)\n"
            f"• Win rate: {wr:.1f}%\n"
            f"• PnL total: {escape_html(total_str)} USDT\n"
        )
        if pf is not None and pf != float("inf"):
            msg += f"• Profit factor: {escape_html(f'{pf:.2f}')}\n"
        elif pf == float("inf") and n:
            msg += "• Profit factor: ∞\n"
        if stats.get("max_dd_pct") is not None:
            dd_val = stats["max_dd_pct"]
            msg += f"• Max DD: {escape_html(f'{dd_val:.2f}')}%"
    return send_message(msg)
