"""
Broker para Binance USD-M Futures Testnet: órdenes reales en sandbox.
Las posiciones se ven en https://testnet.binancefuture.com/
"""
import logging
import os
from typing import Any

import ccxt
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# Símbolo CCXT para BTC perpetual
SYMBOL_CCXT = "BTC/USDT:USDT"


def get_exchange(config: dict[str, Any] | None = None) -> ccxt.Exchange:
    """Devuelve instancia de Binance Futures Testnet (sandbox)."""
    api_key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY", "")
    secret = os.getenv("BINANCE_FUTURES_TESTNET_SECRET", "")
    if not api_key or not secret:
        raise ValueError(
            "Faltan BINANCE_FUTURES_TESTNET_API_KEY y BINANCE_FUTURES_TESTNET_SECRET en .env. "
            "Créalas en https://testnet.binancefuture.com/"
        )
    exchange = ccxt.binance(
        {
            "apiKey": api_key,
            "secret": secret,
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


class BinanceTestnetBroker:
    """Coloca órdenes market en Binance Futures Testnet. Solo LONG (compra para abrir, venta para cerrar)."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._exchange: ccxt.Exchange | None = None
        self.symbol = SYMBOL_CCXT

    @property
    def exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            self._exchange = get_exchange(self.config)
        return self._exchange

    def get_balance_usdt(self) -> float:
        """Saldo disponible en USDT (margin wallet)."""
        balance = self.exchange.fetch_balance()
        # En futures, el balance está en "USDT" o en "total"
        for key in ("USDT", "free", "total"):
            if isinstance(balance.get(key), dict):
                usdt = balance[key].get("USDT") or balance[key].get("free")
                if usdt is not None:
                    return float(usdt)
        return float(balance.get("USDT", {}).get("free", 0) or 0)

    def get_position(self) -> dict[str, Any] | None:
        """
        Posición abierta en BTC/USDT:USDT. Solo LONG.
        Returns: {"side": "long", "qty": float, "entry_price": float} o None si no hay posición.
        """
        positions = self.exchange.fetch_positions([self.symbol])
        for p in positions:
            if p.get("symbol") != self.symbol:
                continue
            contracts = float(p.get("contracts", 0) or 0)
            if contracts <= 0:
                continue
            side = "long" if (p.get("side") == "long" or float(p.get("contracts", 0)) > 0) else "short"
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
        """Abre LONG con market buy. qty_btc en base (BTC)."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        qty_str = self.exchange.amount_to_precision(self.symbol, qty_btc)
        order = self.exchange.create_market_buy_order(self.symbol, float(qty_str))
        log.info("Market BUY %s BTC @ market -> order %s", qty_str, order.get("id"))
        return order

    def market_sell(self, qty_btc: float) -> dict[str, Any]:
        """Cierra LONG con market sell. qty_btc en base (BTC)."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        qty_str = self.exchange.amount_to_precision(self.symbol, qty_btc)
        order = self.exchange.create_market_sell_order(self.symbol, float(qty_str))
        log.info("Market SELL %s BTC @ market -> order %s", qty_str, order.get("id"))
        return order
