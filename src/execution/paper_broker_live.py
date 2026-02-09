"""
Paper broker para live: simula órdenes internamente, obtiene precios reales de Binance.
No requiere API keys (solo datos públicos). No envía órdenes reales.
"""
import logging
from typing import Any

import ccxt

log = logging.getLogger(__name__)

SYMBOL_CCXT = "BTC/USDT:USDT"


def get_public_exchange() -> ccxt.Exchange:
    """Binance Futures producción, solo lectura (sin API keys)."""
    exchange = ccxt.binance({"options": {"defaultType": "future"}})
    return exchange


class PaperBrokerLive:
    """
    Paper trading interno: obtiene precios reales, simula órdenes.
    El estado (balance, posición) se guarda en paper_live_state.json por el runner.
    """

    def __init__(self, config: dict[str, Any] | None = None, initial_capital: float = 10000.0) -> None:
        self.config = config or {}
        self._exchange: ccxt.Exchange | None = None
        self.symbol = SYMBOL_CCXT
        # Estado interno (el runner lo sincroniza con paper_live_state.json)
        self._balance_usdt = initial_capital
        self._position: dict[str, Any] | None = None

    @property
    def exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            self._exchange = get_public_exchange()
        return self._exchange

    def set_state(self, balance: float, position: dict[str, Any] | None) -> None:
        """Carga estado desde el runner (paper_live_state.json)."""
        self._balance_usdt = balance
        self._position = position

    def get_balance_usdt(self) -> float:
        """Saldo simulado en USDT."""
        return self._balance_usdt

    def get_position(self) -> dict[str, Any] | None:
        """Posición simulada."""
        return self._position

    def get_last_price(self) -> float:
        """Precio real de Binance (producción)."""
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)

    def market_buy(self, qty_btc: float) -> dict[str, Any]:
        """Simula compra LONG."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        price = self.get_last_price()
        cost = qty_btc * price
        if cost > self._balance_usdt:
            raise ValueError(f"Saldo insuficiente: {self._balance_usdt:.2f} < {cost:.2f}")
        self._balance_usdt -= cost
        self._position = {
            "side": "long",
            "qty": qty_btc,
            "entry_price": price,
        }
        log.info("Paper BUY %s BTC @ %.2f (simulado)", qty_btc, price)
        return {"id": "paper", "price": price, "qty": qty_btc, "side": "buy"}

    def market_sell(self, qty_btc: float) -> dict[str, Any]:
        """Simula venta (cierre de LONG)."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        price = self.get_last_price()
        proceeds = qty_btc * price
        self._balance_usdt += proceeds
        if self._position and qty_btc >= self._position.get("qty", 0):
            self._position = None
        elif self._position:
            self._position["qty"] -= qty_btc
        log.info("Paper SELL %s BTC @ %.2f (simulado)", qty_btc, price)
        return {"id": "paper", "price": price, "qty": qty_btc, "side": "sell"}
