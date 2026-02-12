"""
Broker para Bybit Futures Testnet: órdenes reales en sandbox.
Las posiciones se ven en https://testnet.bybit.com/
API keys: https://testnet.bybit.com/ → API Management
"""
import logging
import os
import time
from typing import Any

import ccxt
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

SYMBOL_CCXT = "BTC/USDT:USDT"

# Reintentos para llamadas de lectura (balance, posición, precio)
MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos entre reintentos


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
            "timeout": 30000,  # 30s timeout (default era 10s)
            "options": {"defaultType": "swap"},  # futuros perpetuos (derivados)
        }
    )
    exchange.set_sandbox_mode(True)
    return exchange


def _retry(fn, description: str = "API call"):
    """Ejecuta fn() con reintentos para errores de red transitorios."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
            if attempt < MAX_RETRIES:
                log.warning(
                    "Bybit %s: intento %d/%d falló (%s). Reintentando en %ds...",
                    description, attempt, MAX_RETRIES, type(e).__name__, RETRY_DELAY,
                )
                time.sleep(RETRY_DELAY)
            else:
                log.error("Bybit %s: %d intentos agotados. Propagando error.", description, MAX_RETRIES)
                raise


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
        """Saldo disponible en USDT (con reintentos)."""
        balance = _retry(lambda: self.exchange.fetch_balance(), "fetch_balance")
        # Bybit unified account: balance["USDT"]["free"]
        usdt = balance.get("USDT", {})
        if isinstance(usdt, dict):
            return float(usdt.get("free", 0) or 0)
        # Fallback
        free = balance.get("free", {})
        if isinstance(free, dict):
            return float(free.get("USDT", 0) or 0)
        return 0.0

    def get_position(self, side_filter: str = "long") -> dict[str, Any] | None:
        """
        Posición abierta en BTC/USDT:USDT (con reintentos).
        side_filter: "long" o "short".
        Returns: {"side": str, "qty": float, "entry_price": float} o None.
        """
        positions = _retry(
            lambda: self.exchange.fetch_positions([self.symbol]), "fetch_positions"
        )
        for p in positions:
            contracts = float(p.get("contracts", 0) or 0)
            if contracts <= 0:
                continue
            side = p.get("side", "")
            if side != side_filter:
                continue
            return {
                "side": side,
                "qty": abs(contracts),
                "entry_price": float(p.get("entryPrice") or p.get("averagePrice") or 0),
            }
        return None

    def get_last_price(self) -> float:
        """Precio actual (último trade, con reintentos)."""
        ticker = _retry(lambda: self.exchange.fetch_ticker(self.symbol), "fetch_ticker")
        return float(ticker.get("last") or ticker.get("close") or 0)

    def _execute_order(self, side: str, qty_btc: float) -> dict[str, Any]:
        """Ejecuta market order con un reintento ante timeout/red (evitar duplicados: solo 2 intentos)."""
        qty_str = self.exchange.amount_to_precision(self.symbol, qty_btc)
        order_retries = 2  # 1 retry para órdenes (evitar duplicados)
        for attempt in range(1, order_retries + 1):
            try:
                if side == "buy":
                    order = self.exchange.create_market_buy_order(self.symbol, float(qty_str))
                else:
                    order = self.exchange.create_market_sell_order(self.symbol, float(qty_str))
                return order
            except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
                if attempt < order_retries:
                    log.warning("Order %s: intento %d/%d falló (%s). Reintentando...", side, attempt, order_retries, e)
                    time.sleep(RETRY_DELAY)
                else:
                    raise

    def market_buy(self, qty_btc: float) -> dict[str, Any]:
        """Abre LONG con market buy. qty_btc en BTC."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        order = self._execute_order("buy", qty_btc)
        log.info("Bybit Testnet BUY %s BTC @ market -> order %s", self.exchange.amount_to_precision(self.symbol, qty_btc), order.get("id"))
        return order

    def market_sell(self, qty_btc: float) -> dict[str, Any]:
        """Cierra LONG con market sell. qty_btc en BTC."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        order = self._execute_order("sell", qty_btc)
        log.info("Bybit Testnet SELL %s BTC @ market -> order %s", self.exchange.amount_to_precision(self.symbol, qty_btc), order.get("id"))
        return order
