"""
Tests de integración del camino crítico del runner.
Mockea broker y downloader para simular entrada, TP1, stop y atomic write.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.paper_live.runner import _save_state, _load_state, run_live_loop

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config(tmp_path):
    """Config YAML mínimo para el runner."""
    cfg = tmp_path / "test_live.yaml"
    cfg.write_text("""
symbol: BTCUSDT
timeframe: 4h
strategy:
  direction: long
  squeeze_mode: relative
  squeeze_min_bars: 6
  entry_atr_mult: 0.10
  stop_range_atr_mult: 0.10
  stop_entry_atr_mult: 1.5
  tp1_r: 2.0
  tp1_close_pct: 0.4
  chandelier_lookback: 22
  chandelier_atr_mult: 2.5
  trail_activation_r: 0.5
  time_stop_bars: 15
  time_stop_min_r: 0.5
  min_r_atr_mult: 0.5
  trend_filter: false
  quality_filter: false
  entry_require_close_above: false
risk:
  risk_pct: 0.01
  max_open_positions: 1
  max_drawdown_stop_pct: 0.50
  max_consecutive_losses: 20
paper_live:
  initial_capital: 10000.0
  poll_interval_seconds: 1
execution:
  broker: testnet
""")
    return cfg


def _make_ohlcv(n=200, base_price=50000.0, squeeze_start=60, squeeze_end=75):
    """
    Genera un DataFrame OHLCV sintético con un squeeze claro seguido de breakout.
    La última barra tiene close alto para disparar la entrada.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    high = pd.Series([base_price + 500] * n)
    low = pd.Series([base_price - 500] * n)
    close = pd.Series([base_price] * n)
    open_ = close.copy()

    # Squeeze: rango muy estrecho en bars squeeze_start..squeeze_end
    for i in range(squeeze_start, squeeze_end):
        high.iloc[i] = base_price + 50
        low.iloc[i] = base_price - 50
        close.iloc[i] = base_price
        open_.iloc[i] = base_price

    # Breakout: última barra cierra bien arriba del rango
    high.iloc[-1] = base_price + 2000
    low.iloc[-1] = base_price - 100
    close.iloc[-1] = base_price + 1800
    open_.iloc[-1] = base_price

    df = pd.DataFrame({
        "open_time": idx,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": [1000.0] * n,
    })
    return df


def _make_broker_mock(balance=10000.0, position=None, last_price=50000.0):
    """Crea un mock de broker con comportamiento configurable."""
    broker = MagicMock()
    broker.get_balance_usdt.return_value = balance
    broker.get_position.return_value = position
    broker.get_last_price.return_value = last_price
    broker.market_buy.return_value = {"id": "test-order-1", "status": "closed"}
    broker.market_sell.return_value = {"id": "test-order-2", "status": "closed"}
    return broker


# ── Test: escritura atómica de state ──────────────────────────────────────────

def test_save_state_atomic_write(tmp_path):
    """_save_state escribe a .tmp y luego reemplaza: el .tmp no debe quedar."""
    from src.paper_live import runner
    original_path = runner.STATE_PATH
    runner.STATE_PATH = tmp_path / "state.json"

    try:
        state = {"position": None, "balance_usdt": 9999.0, "closed_trades": []}
        _save_state(state)

        assert runner.STATE_PATH.exists(), "El state file debe existir"
        assert not runner.STATE_PATH.with_suffix(".tmp").exists(), "El .tmp no debe quedar"

        loaded = json.loads(runner.STATE_PATH.read_text())
        assert loaded["balance_usdt"] == 9999.0
    finally:
        runner.STATE_PATH = original_path


def test_save_and_load_roundtrip(tmp_path):
    """_save_state + _load_state preservan todos los campos."""
    from src.paper_live import runner
    original_path = runner.STATE_PATH
    runner.STATE_PATH = tmp_path / "state.json"

    try:
        state = {
            "balance_usdt": 10500.0,
            "position": {"entry_price": 50000.0, "qty": 0.002, "stop": 49000.0},
            "closed_trades": [{"pnl_net": 120.0}],
            "peak_equity": 10500.0,
        }
        _save_state(state)
        loaded = _load_state()

        assert loaded["balance_usdt"] == 10500.0
        assert loaded["position"]["entry_price"] == 50000.0
        assert loaded["closed_trades"][0]["pnl_net"] == 120.0
    finally:
        runner.STATE_PATH = original_path


def test_load_state_returns_defaults_on_corrupt_file(tmp_path):
    """_load_state devuelve state con defaults (no {}) si el JSON está corrupto — no debe crashear."""
    from src.paper_live import runner
    original_path = runner.STATE_PATH
    runner.STATE_PATH = tmp_path / "state.json"

    try:
        runner.STATE_PATH.write_text("{broken json!!!")
        loaded = _load_state()
        # Después de la migración, el state tiene al menos state_version y campos base
        assert "state_version" in loaded
        assert loaded.get("paused") is False
        assert "position" not in loaded  # no hay posición inventada
    finally:
        runner.STATE_PATH = original_path


# ── Test: broker idempotency guard ────────────────────────────────────────────

def test_execute_order_idempotency_on_timeout():
    """
    Si create_market_buy_order lanza RequestTimeout en el 1er intento
    y get_position devuelve una posición abierta, no debe reintentar la orden.
    """
    import ccxt
    from src.execution.bybit_testnet_broker import BybitTestnetBroker

    broker = BybitTestnetBroker.__new__(BybitTestnetBroker)
    broker.config = {}
    broker.symbol = "BTC/USDT:USDT"

    mock_exchange = MagicMock()
    mock_exchange.amount_to_precision.return_value = "0.002"
    # 1er intento: timeout
    mock_exchange.create_market_buy_order.side_effect = ccxt.RequestTimeout("timeout")
    broker._exchange = mock_exchange

    # get_position devuelve posición existente (orden ya ejecutada en Bybit)
    broker.get_position = MagicMock(return_value={"side": "long", "qty": 0.002, "entry_price": 50000.0})

    result = broker._execute_order("buy", 0.002)

    # No debe haber reintentado la orden
    assert mock_exchange.create_market_buy_order.call_count == 1
    assert result["id"] == "recovered"


def test_execute_order_retries_when_no_position_after_timeout():
    """
    Si hay timeout y get_position devuelve None (orden no ejecutada),
    debe reintentar la orden.
    """
    import ccxt
    from src.execution.bybit_testnet_broker import BybitTestnetBroker

    broker = BybitTestnetBroker.__new__(BybitTestnetBroker)
    broker.config = {}
    broker.symbol = "BTC/USDT:USDT"

    mock_exchange = MagicMock()
    mock_exchange.amount_to_precision.return_value = "0.002"
    # 1er intento timeout, 2do intento éxito
    mock_exchange.create_market_buy_order.side_effect = [
        ccxt.RequestTimeout("timeout"),
        {"id": "order-retry", "status": "closed"},
    ]
    broker._exchange = mock_exchange

    # No hay posición en Bybit → la orden no se ejecutó
    broker.get_position = MagicMock(return_value=None)

    result = broker._execute_order("buy", 0.002)

    assert mock_exchange.create_market_buy_order.call_count == 2
    assert result["id"] == "order-retry"


# ── Test: drawdown guard bloquea entradas ─────────────────────────────────────

def test_drawdown_guard_blocks_entry(minimal_config, tmp_path):
    """
    Si el equity actual está por debajo del umbral de drawdown,
    no se deben abrir nuevas posiciones (market_buy no debe llamarse).
    """
    state_path = tmp_path / "state_test.json"
    df = _make_ohlcv()

    # Estado inicial: peak_equity alto, equity actual bajo (simulando DD > 50%)
    initial_state = {
        "peak_equity": 10000.0,
        "closed_trades": [],
        "last_candle_time": None,
        "entered_ranges": [],
    }
    state_path.write_text(json.dumps(initial_state))

    broker_mock = _make_broker_mock(balance=4500.0)  # 55% DD respecto a peak 10000

    with (
        patch("src.paper_live.runner.BybitTestnetBroker", return_value=broker_mock),
        patch("src.paper_live.runner.download_ohlcv", return_value=df),
        patch("src.paper_live.runner.telegram_configured", return_value=False),
        patch("src.paper_live.runner._rotate_state_backup"),
        patch("src.paper_live.runner._ping_healthcheck"),
    ):
        # Configurar max_drawdown_stop_pct bajo (10%) para que se active
        import src.paper_live.runner as runner_mod
        runner_mod.STATE_PATH = state_path

        # Correr solo 1 iteración usando poll_interval_seconds=0 y cortando con StopIteration
        call_count = 0
        original_sleep = __import__("time").sleep

        def one_shot_sleep(s):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt()

        with patch("src.paper_live.runner.time.sleep", side_effect=one_shot_sleep):
            try:
                run_live_loop(minimal_config, poll_interval_seconds=1, state_path=state_path)
            except KeyboardInterrupt:
                pass

    broker_mock.market_buy.assert_not_called()
