"""
Broker para Bybit Futures Mainnet: órdenes reales con dinero real.
API keys: https://www.bybit.com/ → API Management

IMPORTANTE: Este broker opera en producción real. Verificar claves y configuración
antes de usar. Las keys de testnet NO funcionan aquí.
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

MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos entre reintentos


def get_exchange() -> ccxt.Exchange:
    """Devuelve instancia de Bybit Futures Mainnet."""
    api_key = os.getenv("BYBIT_API_KEY", "")
    secret = os.getenv("BYBIT_SECRET", "")
    if not api_key or not secret:
        raise ValueError(
            "Faltan BYBIT_API_KEY y BYBIT_SECRET en .env. "
            "Créalas en https://www.bybit.com/ → API Management"
        )
    if len(api_key) < 10 or len(secret) < 10:
        raise ValueError(
            "BYBIT_API_KEY o BYBIT_SECRET parecen inválidas (demasiado cortas). "
            "Verificar que se copiaron correctamente."
        )
    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {"defaultType": "swap"},  # futuros perpetuos
        }
    )
    # NO llamar set_sandbox_mode: por defecto opera en mainnet
    return exchange


_CB_FAILURE_THRESHOLD = 5      # fallos consecutivos para abrir el circuit
_CB_RECOVERY_SECONDS = 600    # 10 min antes de intentar HALF-OPEN


class _CircuitBreaker:
    """
    Circuit breaker simple para llamadas de lectura a la API de Bybit.
    Estados: CLOSED (normal) → OPEN (fallos acumulados) → HALF_OPEN (prueba) → CLOSED.
    Las operaciones de escritura (órdenes) siempre pasan: nunca cachear.
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self) -> None:
        self.state = self.CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0
        self._cache: dict = {}

    def call(self, fn, description: str, cache_key: str | None = None):
        """Ejecuta fn() respetando el estado del circuit breaker."""
        if self.state == self.OPEN:
            if time.time() - self._opened_at >= _CB_RECOVERY_SECONDS:
                log.info("CircuitBreaker: intentando HALF_OPEN para %s", description)
                self.state = self.HALF_OPEN
            else:
                if cache_key and cache_key in self._cache:
                    log.warning("CircuitBreaker OPEN: devolviendo caché para %s", description)
                    return self._cache[cache_key]
                raise ccxt.NetworkError(f"CircuitBreaker OPEN: {description} bloqueado")

        try:
            result = fn()
            # Éxito: resetear
            self._failure_count = 0
            self.state = self.CLOSED
            if cache_key is not None:
                self._cache[cache_key] = result
            return result
        except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
            self._failure_count += 1
            if self._failure_count >= _CB_FAILURE_THRESHOLD:
                log.error(
                    "CircuitBreaker: %d fallos consecutivos en %s. Abriendo circuito por %ds.",
                    self._failure_count, description, _CB_RECOVERY_SECONDS,
                )
                self.state = self.OPEN
                self._opened_at = time.time()
            raise


def _retry(fn, description: str = "API call"):
    """Ejecuta fn() con reintentos para errores de red transitorios."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
            if attempt < MAX_RETRIES:
                log.warning(
                    "Bybit mainnet %s: intento %d/%d falló (%s). Reintentando en %ds...",
                    description, attempt, MAX_RETRIES, type(e).__name__, RETRY_DELAY,
                )
                time.sleep(RETRY_DELAY)
            else:
                log.error("Bybit mainnet %s: %d intentos agotados. Propagando error.", description, MAX_RETRIES)
                raise


class BybitMainnetBroker:
    """Coloca órdenes market en Bybit Futures Mainnet. Dinero real."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._exchange: ccxt.Exchange | None = None
        self.symbol = self._resolve_symbol()
        self._cb = _CircuitBreaker()

    def _resolve_symbol(self) -> str:
        """Convierte el símbolo del config (ej. ETHUSDT) al formato CCXT (ej. ETH/USDT:USDT)."""
        raw = self.config.get("symbol", "BTCUSDT")
        if ":" in raw:
            return raw
        if raw.endswith("USDT"):
            base = raw[:-4]
            return f"{base}/USDT:USDT"
        return SYMBOL_CCXT

    @property
    def exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            self._exchange = get_exchange()
        return self._exchange

    def get_balance_usdt(self) -> float:
        """Saldo disponible en USDT. Usa circuit breaker: devuelve caché si API está caída."""
        balance = self._cb.call(
            lambda: _retry(lambda: self.exchange.fetch_balance(), "fetch_balance"),
            description="fetch_balance",
            cache_key="balance",
        )
        usdt = balance.get("USDT", {})
        if isinstance(usdt, dict):
            return float(usdt.get("free", 0) or 0)
        free = balance.get("free", {})
        if isinstance(free, dict):
            return float(free.get("USDT", 0) or 0)
        return 0.0

    def get_position(self, side_filter: str = "long") -> dict[str, Any] | None:
        """
        Posición abierta en BTC/USDT:USDT. Usa circuit breaker: devuelve caché si API está caída.
        side_filter: "long" o "short".
        Returns: {"side": str, "qty": float, "entry_price": float} o None.
        """
        positions = self._cb.call(
            lambda: _retry(lambda: self.exchange.fetch_positions([self.symbol]), "fetch_positions"),
            description="fetch_positions",
            cache_key=f"positions_{side_filter}",
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
        """Precio actual. Usa circuit breaker: devuelve caché si API está caída."""
        ticker = self._cb.call(
            lambda: _retry(lambda: self.exchange.fetch_ticker(self.symbol), "fetch_ticker"),
            description="fetch_ticker",
            cache_key="ticker",
        )
        return float(ticker.get("last") or ticker.get("close") or 0)

    def _execute_order(self, side: str, qty_btc: float) -> dict[str, Any]:
        """
        Ejecuta market order con guard de idempotencia ante timeout.
        Si el primer intento sufre timeout, verifica en Bybit si la orden
        ya se ejecutó antes de reintentar, evitando posiciones duplicadas.
        """
        qty_str = self.exchange.amount_to_precision(self.symbol, qty_btc)
        expected_position_side = "long" if side == "buy" else "short"

        for attempt in range(1, 3):  # máximo 2 intentos
            try:
                if side == "buy":
                    order = self.exchange.create_market_buy_order(self.symbol, float(qty_str))
                else:
                    order = self.exchange.create_market_sell_order(self.symbol, float(qty_str))
                return order
            except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
                log.warning("Order %s: intento %d/2 falló (%s).", side, attempt, type(e).__name__)
                if attempt == 1:
                    time.sleep(RETRY_DELAY)
                    try:
                        existing = self.get_position(side_filter=expected_position_side)
                        if existing and existing.get("qty", 0) > 0:
                            log.warning(
                                "Idempotency guard: posición %s ya existe en Bybit (qty=%s). "
                                "Orden probablemente ejecutada. No se reintenta.",
                                expected_position_side, existing["qty"],
                            )
                            return {"id": "recovered", "status": "closed", "info": existing}
                    except Exception as check_err:
                        log.warning("No se pudo verificar posición post-timeout: %s", check_err)
                else:
                    raise

    def market_buy(self, qty_btc: float) -> dict[str, Any]:
        """Abre LONG con market buy. qty_btc en BTC."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        order = self._execute_order("buy", qty_btc)
        log.info("Bybit Mainnet BUY %s BTC @ market -> order %s", self.exchange.amount_to_precision(self.symbol, qty_btc), order.get("id"))
        return order

    def market_sell(self, qty_btc: float) -> dict[str, Any]:
        """Cierra LONG con market sell. qty_btc en BTC."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        order = self._execute_order("sell", qty_btc)
        log.info("Bybit Mainnet SELL %s BTC @ market -> order %s", self.exchange.amount_to_precision(self.symbol, qty_btc), order.get("id"))
        return order

    def limit_buy(self, qty_btc: float, price: float) -> dict[str, Any]:
        """Coloca limit buy (maker). Retorna el order dict con 'id'."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        qty_str = float(self.exchange.amount_to_precision(self.symbol, qty_btc))
        price_str = float(self.exchange.price_to_precision(self.symbol, price))
        order = _retry(
            lambda: self.exchange.create_limit_buy_order(self.symbol, qty_str, price_str),
            "limit_buy",
        )
        log.info("Bybit Mainnet LIMIT BUY %.5f BTC @ %.2f -> order %s", qty_btc, price, order.get("id"))
        return order

    def limit_sell(self, qty_btc: float, price: float) -> dict[str, Any]:
        """Coloca limit sell (maker). Para SHORT entry o cierre de LONG."""
        if qty_btc <= 0:
            raise ValueError("qty_btc debe ser > 0")
        qty_str = float(self.exchange.amount_to_precision(self.symbol, qty_btc))
        price_str = float(self.exchange.price_to_precision(self.symbol, price))
        order = _retry(
            lambda: self.exchange.create_limit_sell_order(self.symbol, qty_str, price_str),
            "limit_sell",
        )
        log.info("Bybit Mainnet LIMIT SELL %.5f BTC @ %.2f -> order %s", qty_btc, price, order.get("id"))
        return order

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Consulta el estado de una orden por ID."""
        try:
            return _retry(
                lambda: self.exchange.fetch_order(order_id, self.symbol),
                "fetch_order",
            )
        except Exception as e:
            log.warning("No se pudo consultar orden %s: %s", order_id, e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancela una orden abierta. Retorna True si tuvo éxito."""
        try:
            _retry(
                lambda: self.exchange.cancel_order(order_id, self.symbol),
                "cancel_order",
            )
            log.info("Orden %s cancelada", order_id)
            return True
        except Exception as e:
            log.warning("No se pudo cancelar orden %s: %s", order_id, e)
            return False
