# BTCUSDT 4H Squeeze Breakout (LONG-only)

App en Python para operar **BTCUSDT Perpetual en 4H** con órdenes reales en **Bybit Futures Testnet** (demo). Estrategia LONG-only: Squeeze → Breakout.

## Requisitos

- Python 3.10+
- Cuenta en [Bybit Testnet](https://testnet.bybit.com/) (API keys para órdenes)

## Setup

```bash
# Clonar / entrar al proyecto
cd last_last_one

# Entorno virtual (recomendado)
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/Mac

# Dependencias
pip install -r requirements.txt

# Credenciales: copiar .env.example a .env y rellenar
copy .env.example .env
# Editar .env con BYBIT_TESTNET_API_KEY y BYBIT_TESTNET_SECRET
```

## Comandos CLI

```bash
# Descargar OHLCV histórico (BTCUSDT 4H) y cachear (rango por defecto en config: 2020-01-01 a 2025-12-31)
python cli.py fetch-data --config configs/base.yaml

# Descargar un rango concreto por CLI (sobrescribe config)
python cli.py fetch-data --start-date 2019-01-01 --end-date 2025-02-01
python cli.py fetch-data --end-date today   # hasta hoy

# Backtest histórico
python cli.py backtest --config configs/base.yaml

# Walk-forward (ventanas deslizantes)
python cli.py walkforward --config configs/wf.yaml

# Paper-live simulado (backtest hasta hoy, sin órdenes)
python cli.py paper-live --config configs/live.yaml

# Paper-live con órdenes reales en Bybit Futures Testnet (posiciones visibles en testnet.bybit.com)
python cli.py paper-live --config configs/live.yaml --execute
```

Opciones comunes: `--config`, `--cache-dir`, `--db`, `--log-level`, `--log-dir`.

### Paper trade en vivo (Bybit Testnet)

Trading con **órdenes reales** en Bybit Futures Testnet. Las posiciones se ven en [testnet.bybit.com](https://testnet.bybit.com/).

**Prerrequisitos**:
1. Crear cuenta en [Bybit Testnet](https://testnet.bybit.com/)
2. Ir a API Management → crear API key
3. Copiar `BYBIT_TESTNET_API_KEY` y `BYBIT_TESTNET_SECRET` en `.env`

**Ejecutar**:
```bash
python cli.py paper-live --config configs/live.yaml --execute
```

El script revisa cada cierto tiempo (p. ej. 2 min, ver `poll_interval_seconds` en `configs/live.yaml`) si cerró una vela 4H. Si hay señal de entrada o salida, **coloca la orden real** en Bybit Testnet. Los datos OHLCV se obtienen de Binance (API pública, sin keys).

Capital disponible: el balance de USDT en tu cuenta Bybit Testnet (se obtiene fondos de prueba gratis al crear la cuenta).

### Notificaciones por Telegram

Con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en `.env` (crear bot con [@BotFather](https://t.me/BotFather), chat_id con [@userinfobot](https://t.me/userinfobot)):

- **Al abrir posición**: mensaje con entrada, stop y cantidad.
- **Al cerrar posición**: mensaje indicando si fue **éxito** o **pérdida** y PnL neto en USDT.
- **Resumen semanal**: si el proceso `--execute` está en marcha, los **viernes a las 10:00 AM Argentina** (13:00 UTC) se envía un resumen de los últimos 7 días (operaciones, win rate, PnL total, profit factor).

Para enviar el resumen semanal a mano (p. ej. desde cron):

```bash
python cli.py weekly-report --config configs/live.yaml
```

## Dashboard

```bash
streamlit run src/dashboard/app.py
```

- **Runs**: lista de runs (backtest y walk-forward) con parámetros y métricas; comparación de 2 runs.
- **Run detail**: equity curve + drawdown, tabla de trades, gráfico de precio con marcadores entrada/salida.
- **Walk-Forward**: tabla por ventana (trades, return, PF, DD, winrate) y gráfico de métricas por ventana.

## Estrategia (resumen)

- **Indicadores**: Bollinger Bands (20, 2), Keltner Channels (20, 1.5×ATR(20)), ATR(14) para stops/trailing.
- **Squeeze**: Modos `relative` (BB width &lt; media o percentil), `width` (BB &lt; KC×ratio), `inside` (BB dentro de KC). Rango: `range_high` / `range_low` del squeeze.
- **Entrada**: buy-stop en `entry = range_high + 0.10×ATR(14)`. Opciones: `entry_require_close_above` (solo si cierre &gt; entry), `quality_filter` (TrueRange &gt; 1.1×SMA(TR,20)), `trend_filter` (close &gt; SMA(close, trend_period)), `min_r_atr_mult` (mínimo R en ATR).
- **Stop**: `stop = min(range_low - 0.10×ATR, entry - stop_entry_atr_mult×ATR)`. Tras +0.5R el stop se mueve a breakeven.
- **Salida**: TP1 +1R cerrando 50%; resto Chandelier trail; time stop (barras sin +min_r). En salidas a mercado se usa `max(close, stop)` para no superar 1R de pérdida.
- **Fees/slippage**: taker 0.06%, slippage 0.02%; modo stress duplica desde config.
- **Riesgo**: configurable (ej. 0.5%); guardrails: `max_drawdown_stop_pct`, `max_consecutive_losses`.

## Estructura del proyecto

```
last_last_one/
  configs/          # base.yaml, wf.yaml, live.yaml
  data/             # cache OHLCV (Parquet), trading.db (SQLite)
  src/
    data/           # downloader, cache, feed
    strategy/       # indicadores, squeeze, signals
    execution/      # paper broker, portfolio, fees/slippage
    backtest/       # motor event-driven
    wf/             # walk-forward runner
    storage/       # SQLite + export CSV/Parquet
    dashboard/     # Streamlit app
  tests/           # unitarios (squeeze, R/sizing, fees/slippage)
  cli.py           # fetch-data, backtest, walkforward, paper-live
  requirements.txt
  .env.example
```

## Tests

```bash
pytest tests/ -v
```

## Persistencia y export

- **SQLite** (`data/trading.db`): runs, trades, equity snapshots, wf_windows.
- **Export**: desde código o dashboard se pueden exportar trades y resumen a CSV/Parquet (ver `src/storage/export.py`).

## Objetivo 20% anual y DD bajo

- En `configs/base.yaml` el perfil prioriza selectividad (squeeze percentil, trend filter opcional), TP1 +1.5R, trail amplio y breakeven para limitar pérdidas.
- Para más operaciones con las mismas protecciones: `python cli.py backtest --config configs/target_20pct_annual.yaml`.
- El retorno anual depende del periodo; conviene validar con walk-forward o varios rangos de fechas. Ajustar `squeeze_percentile_max`, `trend_filter`, `risk_pct` según resultados.

## Restricciones

- No se usan cruces de medias como señal principal.
- Sin `--execute`: todo es simulado (backtest hasta hoy). Con `--execute`: se envían órdenes reales **solo a Bybit Futures Testnet** (sandbox), no a producción.
- Prioridad: claridad y robustez sobre optimización prematura.
