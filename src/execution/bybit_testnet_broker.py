"""
Broker para Bybit Futures Testnet: órdenes reales en sandbox.
Las posiciones se ven en https://testnet.bybit.com/
API keys: https://testnet.bybit.com/ → API Management
"""
import logging
import os
from typing import Any

import ccxt
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

SYMBOL_CCXT = "BTC/USDT:USDT"


def get_exchange() -> ccxt.Exchange:
    """Devuelve instancia de Bybit Futures Testnet (sandbox)."""
    api_key = os.getenv("BYBIT_TESTNET_API_KEY", "")
    secret = os.getenv("BYBIT_TESTNET_SECRET", "")
    if not api_key or not secret:
        raise ValueError(
            "Faltan BYBIT_TESTNET_API_KEY y BYBIT_TESTNET_SECRET en .env. "
            "Créalas en https://testnet.bybit.com/ → API Management"
        )
    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},  # futuros perpetuos (derivados)
        }
    )
    exchange.set_sandbox_mode(True)
    return exchange


class BybitTestnetBroker:
    """Coloca órdenes market en Bybit Futures Testnet. Solo LONG."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._exchange: ccxt.Exchange | None = None
        self.symbol = SYMBOL_CCXT

    @property
    def exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            self._exchange = get_exchange()
        return self._exchange

    def get_balance_usdt(self) -> float:
        """Saldo disponible en USDT."""
        balance = self.exchange.fetch_balance()
        # Bybit unified account: balance["USDT"]["free"]
        usdt = balance.get("USDT", {})
        if isinstance(usdt, dict):
            return float(usdt.get("free", 0) or 0)
        # Fallback
        free = balance.get("free", {})
        if isinstance(free, dict):
            return float(free.get("USDT", 0) or 0)
        return 0.0

    def get_position(self) -> dict[str, Any] | None:
        """
        Posición abierta en BTC/USDT:USDT. Solo LONG.
        Returns: {"side": "long", "qty": float, "entry_price": float} o None.
        """
        positions = self.exchange.fetch_positions([self.symbol])
        for p in positions:
            contracts = float(p.get("contracts", 0) or 0)
            if contracts <= 0:
                continue
            side = p.get("side", "")
            if side != "long":
                continue
            return {
                "side": "long",
                "qty": abs(contracts),
                "entry_price": float(p.get("entryPrice") or p.get("averagePrice") or 0),
            }
        return None

    def get_last_price(self) -> float:
        """Precio actual (último trade)."""
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)

    def market_buy(self, qty_btc: float) -> dict[str, Any]:
        """Abre LONG con market buy. qty_btc en BTC."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        qty_str = self.exchange.amount_to_precision(self.symbol, qty_btc)
        order = self.exchange.create_market_buy_order(self.symbol, float(qty_str))
        log.info("Bybit Testnet BUY %s BTC @ market -> order %s", qty_str, order.get("id"))
        return order

    def market_sell(self, qty_btc: float) -> dict[str, Any]:
        """Cierra LONG con market sell. qty_btc en BTC."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        qty_str = self.exchange.amount_to_precision(self.symbol, qty_btc)
        order = self.exchange.create_market_sell_order(self.symbol, float(qty_str))
        log.info("Bybit Testnet SELL %s BTC @ market -> order %s", qty_str, order.get("id"))
        return order
