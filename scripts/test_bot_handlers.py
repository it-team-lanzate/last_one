"""Test de handlers del bot de Telegram (sin getUpdates, simula respuestas)."""
import sys
sys.path.insert(0, ".")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", stream=sys.stdout)

from src.notifications.telegram_bot import (
    _load_state, _get_bybit_price, _format_position,
    STATE_LONG, STATE_SHORT,
)


def test_status():
    print("\n=== TEST /status ===")
    state_long = _load_state(STATE_LONG)
    state_short = _load_state(STATE_SHORT)
    price = _get_bybit_price()

    print(f"Precio BTC/USDT: {price}")
    print(f"State LONG keys: {list(state_long.keys())}")
    print(f"State SHORT keys: {list(state_short.keys())}")
    print(f"LONG posición: {'SÍ' if state_long.get('position') else 'NO'}")
    print(f"SHORT posición: {'SÍ' if state_short.get('position') else 'NO'}")
    print(f"LONG última vela: {state_long.get('last_candle_time', '—')}")
    print(f"SHORT última vela: {state_short.get('last_candle_time', '—')}")

    print("\n--- Format LONG ---")
    print(_format_position(state_long, "LONG", price))
    print("\n--- Format SHORT ---")
    print(_format_position(state_short, "SHORT", price))


def test_trades():
    print("\n=== TEST /trades ===")
    state_long = _load_state(STATE_LONG)
    state_short = _load_state(STATE_SHORT)
    trades_long = state_long.get("closed_trades", [])
    trades_short = state_short.get("closed_trades", [])
    print(f"LONG trades cerrados: {len(trades_long)}")
    print(f"SHORT trades cerrados: {len(trades_short)}")
    if trades_long:
        print("Último LONG:", trades_long[-1])
    if trades_short:
        print("Último SHORT:", trades_short[-1])


def test_price():
    print("\n=== TEST precio Bybit ===")
    price = _get_bybit_price()
    print(f"BTC/USDT: {price}")


if __name__ == "__main__":
    test_price()
    test_status()
    test_trades()
    print("\n✅ Handlers funcionan correctamente")
