# BTCUSDT 4H Squeeze Breakout / Breakdown

App en Python para operar **BTCUSDT Perpetual en 4H** con órdenes reales en **Bybit Futures Testnet** (demo). Dos estrategias independientes:

- **LONG** (Squeeze → Breakout): opera rupturas alcistas
- **SHORT** (Squeeze → Breakdown): opera rupturas bajistas

## Requisitos

- Python 3.10+
- Cuenta en [Bybit Testnet](https://testnet.bybit.com/) (API keys para órdenes)
- Bot de Telegram (opcional, para notificaciones y monitoreo remoto)

## Setup

```bash
# Clonar / entrar al proyecto
cd last_last_one

# Entorno virtual (recomendado)
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Linux/Mac

# Dependencias
pip install -r requirements.txt

# Credenciales: copiar .env.example a .env y rellenar
copy .env.example .env
# Editar .env con BYBIT_TESTNET_API_KEY, BYBIT_TESTNET_SECRET,
# TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

## Comandos CLI

```bash
# --- DATOS ---
python cli.py fetch-data --config configs/base.yaml
python cli.py fetch-data --start-date 2019-01-01 --end-date today

# --- BACKTEST ---
# LONG
python cli.py backtest --config configs/base.yaml
python cli.py backtest --config configs/base.yaml --start-date 2019-01-01 --end-date 2025-12-31

# SHORT
python cli.py backtest --config configs/base_short.yaml
python cli.py backtest --config configs/base_short.yaml --start-date 2019-01-01 --end-date 2025-12-31

# --- WALK-FORWARD ---
python cli.py walkforward --config configs/wf.yaml --start-date 2020-01-01 --end-date 2025-12-31
python cli.py walkforward --config configs/wf_short.yaml --start-date 2020-01-01 --end-date 2025-12-31

# --- PAPER-LIVE (simulado, sin órdenes) ---
python cli.py paper-live --config configs/live.yaml
python cli.py paper-live --config configs/live_short.yaml

# --- PAPER-LIVE CON ÓRDENES REALES (Bybit Testnet) ---
python cli.py paper-live --config configs/live.yaml --execute        # LONG
python cli.py paper-live --config configs/live_short.yaml --execute   # SHORT

# --- TELEGRAM BOT (monitoreo remoto) ---
python cli.py telegram-bot

# --- RESUMEN SEMANAL MANUAL ---
python cli.py weekly-report --config configs/live.yaml
```

Opciones comunes: `--config`, `--cache-dir`, `--db`, `--log-level`, `--log-dir`.

## Migrar a VPS (primera vez)

### 1. Requisitos del VPS

- **SO**: Ubuntu/Debian recomendado
- **Python 3.10+**: `python3 --version`
- **screen**: `sudo apt install -y screen`
- **Git**: `sudo apt install -y git` (si vas a clonar)

### 2. Subir el código

**Opción A – Clonar desde Git (recomendado):**

```bash
cd /home/tu_usuario   # o /root
git clone https://github.com/TU_USUARIO/last_one.git
cd last_one
```

**Opción B – Copiar desde tu PC (rsync o SCP):**

```bash
# Desde tu PC (Windows PowerShell o WSL):
scp -r C:\proyectos\last_last_one usuario@TU_VPS_IP:/home/usuario/last_one
```

### 3. Configurar entorno en el VPS

```bash
cd /home/usuario/last_one   # o la ruta donde esté el proyecto

# Entorno virtual
python3 -m venv venv
source venv/bin/activate

# Dependencias
pip install -r requirements.txt

# Crear .env desde ejemplo
cp .env.example .env
nano .env   # o vi
```

**Rellenar .env con:**

```
TELEGRAM_BOT_TOKEN=tu_token_de_BotFather
TELEGRAM_CHAT_ID=tu_chat_id
BYBIT_TESTNET_API_KEY=tu_api_key
BYBIT_TESTNET_SECRET=tu_secret
```

Las API keys se crean en [Bybit Testnet → API Management](https://testnet.bybit.com/).

### 4. Descargar datos OHLCV

```bash
source venv/bin/activate
python cli.py fetch-data --end-date today
```

Esto crea `data/cache/` y descarga velas 4H de BTCUSDT. Sin esto, el paper-live no tendrá datos.

### 5. Crear directorios (si no existen)

```bash
mkdir -p data/cache data/logs
```

### 6. Arrancar procesos (ver sección siguiente)

Seguir los pasos de **Despliegue en VPS** para poner en marcha LONG, SHORT, bot Telegram y dashboard.

---

## Despliegue en VPS (LONG + SHORT + Bot Telegram)

Para ejecutar ambas estrategias en un VPS con monitoreo remoto:

```bash
# 1. Actualizar datos (antes de cada arranque recomendado)
source venv/bin/activate
python cli.py fetch-data --end-date today

# 2. Sesión screen para LONG
screen -S long
source venv/bin/activate
python cli.py paper-live --config configs/live.yaml --execute --log-dir data/logs
# Ctrl+A, luego D para salir sin matar

# 3. Sesión screen para SHORT
screen -S short
source venv/bin/activate
python cli.py paper-live --config configs/live_short.yaml --execute --log-dir data/logs
# Ctrl+A, luego D para salir sin matar

# 4. Sesión screen para bot de Telegram
screen -S tgbot
source venv/bin/activate
python cli.py telegram-bot --log-dir data/logs
# Ctrl+A, luego D para salir sin matar

# 5. Dashboard (monitoreo web: estado, métricas, posiciones)
screen -S dashboard
source venv/bin/activate
pip install streamlit-autorefresh   # opcional, para auto-refresh cada 60s
streamlit run src/dashboard/app.py --server.port 8501 --server.address 0.0.0.0
# Ctrl+A, luego D para salir sin matar
# Acceder desde navegador: http://TU_VPS_IP:8501

# Ver sesiones activas
screen -ls

# Volver a una sesión
screen -r long    # o short, tgbot, dashboard
```

**Firewall** (si quieres ver el dashboard desde fuera):
```bash
sudo ufw allow 8501/tcp
sudo ufw reload
```
Luego accede desde el navegador a `http://TU_VPS_IP:8501`.

**Importante**: El bot de Telegram debe ejecutarse en una **única instancia**. Si hay otro proceso usando `getUpdates` con el mismo token, se produce un error 409 Conflict.

## Bot de Telegram (monitoreo remoto)

Permite consultar el estado de las estrategias desde el celular sin conectar por SSH.

### Configuración

1. Crear bot con [@BotFather](https://t.me/BotFather) → copiar el token
2. Obtener tu `chat_id` con [@userinfobot](https://t.me/userinfobot)
3. Agregar ambos en `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```
4. **Enviar `/start` al bot desde Telegram** (necesario la primera vez)

### Comandos disponibles

| Comando | Descripción |
|---------|-------------|
| `/status` | Precio BTC, balance Bybit, posiciones LONG y SHORT (entry, stop, R actual, PnL flotante) |
| `/trades` | Últimos 5 trades cerrados por estrategia + PnL últimos 7 días |
| `/equity` | Resumen de rendimiento total: trades, winrate, PnL, mejor/peor trade |
| `/help` | Lista de comandos |

### Notificaciones automáticas

Además de los comandos, el runner envía automáticamente:
- **Al abrir posición**: entrada, stop, cantidad
- **Al cerrar posición**: éxito/pérdida, PnL neto
- **Resumen semanal**: viernes 10:00 AM Argentina (13:00 UTC), últimos 7 días

## Dashboard

```bash
streamlit run src/dashboard/app.py
```

- **Live Monitor**: estado de runners LONG/SHORT (activo/stale), posiciones, balance, últimos trades, PnL. Auto-refresh cada 60s.
- **Logs**: últimas líneas del archivo de log (requiere `--log-dir data/logs` en paper-live y telegram-bot). Auto-refresh cada 5s.
- **Runs**: lista de runs (backtest y walk-forward) con parámetros y métricas; comparación de 2 runs.
- **Run detail**: equity curve + drawdown, tabla de trades, gráfico de precio con marcadores.
- **Walk-Forward**: tabla por ventana + gráfico de métricas.

## Estrategia

### LONG (Squeeze → Breakout)
- **Entrada**: buy-stop en `range_high + entry_atr_mult × ATR(14)` (ruptura alcista)
- **Trend filter**: solo LONG si `close > SMA(close, trend_period)`

### SHORT (Squeeze → Breakdown)
- **Entrada**: sell-stop en `range_low - entry_atr_mult × ATR(14)` (ruptura bajista)
- **Trend filter**: solo SHORT si `close < SMA(close, trend_period)`

### Común a ambas
- **Squeeze**: BB dentro de KC (modos: `relative`, `width`, `inside`). Rango: `range_high` / `range_low`.
- **Stop**: `max(range extremo ± ATR, entry ± stop_entry_atr_mult × ATR)`. Breakeven a +0.5R.
- **TP1**: parcial a `tp1_r × R`, cerrando `tp1_close_pct` de la posición.
- **Trail**: Chandelier (`highest_high(N) - mult × ATR` para LONG / `lowest_low(N) + mult × ATR` para SHORT).
- **Time stop**: si tras N velas no alcanza `time_stop_min_r`, cierra.
- **Fees/slippage**: taker 0.06%, slippage 0.02%; modo stress duplica.

## Rendimiento (backtest 2020-01-01 a 2025-12-31, 10k USD)

| Métrica | LONG | SHORT |
|---------|------|-------|
| Retorno total | 428.58% | 198.30% |
| Retorno anualizado | ~32% | ~20% |
| Max Drawdown | 2.79% | 6.91% |
| Profit Factor | 8.41 | 3.49 |
| Trades | 327 | 287 |

**Combinado (5k LONG + 5k SHORT)**: retorno total ~250%, anualizado ~23%, DD contenido por diversificación.

### Optimización (retorno sin subir DD)

```bash
python scripts/dev/optimize_return_dd_constraint.py           # grid completo
python scripts/dev/optimize_return_dd_constraint.py --quick   # 2 combos/estrategia
```

Parámetros evaluados: `tp1_r`, `chandelier_atr_mult`, `quality_filter_tr_mult`. Resultados en `data/optimize_results.txt`.

## Estructura del proyecto

```
last_last_one/
  configs/          # base.yaml, base_short.yaml, wf.yaml, wf_short.yaml, live.yaml, live_short.yaml
  data/             # cache OHLCV (Parquet), trading.db (SQLite), paper_live_state*.json
  src/
    data/           # downloader, cache, feed
    strategy/       # indicadores, squeeze, signals
    execution/      # paper broker, bybit testnet broker, portfolio, fees/slippage
    backtest/       # motor event-driven (direction-aware)
    wf/             # walk-forward runner
    paper_live/     # runner live (Bybit Testnet + Telegram)
    notifications/  # telegram.py (envío), telegram_bot.py (monitoreo interactivo)
    storage/        # SQLite + export CSV/Parquet
    dashboard/      # Streamlit app
  scripts/          # wf_detail, test_bot_handlers; dev/ (tuning opcional)
  tests/            # unitarios (squeeze, R/sizing, fees/slippage)
  cli.py            # fetch-data, backtest, walkforward, paper-live, telegram-bot, weekly-report
  requirements.txt
  .env.example
```

## Tests

```bash
pytest tests/ -v
```

## Checklist UAT (User Acceptance Testing)

Antes de considerar el sistema listo para uso prolongado en VPS:

- [ ] **Backtest LONG**: `python cli.py backtest --config configs/base.yaml --start-date 2020-01-01 --end-date 2025-12-31` → verificar retorno/DD razonables
- [ ] **Backtest SHORT**: `python cli.py backtest --config configs/base_short.yaml --start-date 2020-01-01 --end-date 2025-12-31` → verificar retorno/DD razonables
- [ ] **Walk-Forward**: ejecutar WF para ambas estrategias y revisar mean_return/mean_PF
- [ ] **Fetch data**: `python cli.py fetch-data --end-date today` → sin errores
- [ ] **Paper-live LONG (execute)**: arrancar con `--execute` en sesión screen; verificar heartbeat, sincronización con Bybit, notificaciones Telegram
- [ ] **Paper-live SHORT (execute)**: misma verificación
- [ ] **Bot Telegram**: `/status`, `/trades`, `/equity` responden correctamente
- [ ] **Simulación de fallos**: desconectar red brevemente → el runner debe recuperarse (reintentos, log de errores, sin crash)
- [ ] **Dashboard**: `streamlit run src/dashboard/app.py` → runs, detalle, WF visibles
- [ ] **Config inválido**: corromper un YAML → mensaje de error claro
- [ ] **Sin API keys**: ejecutar sin .env completo → mensaje claro, no stacktrace genérico

## Restricciones

- No se usan cruces de medias como señal principal.
- Sin `--execute`: todo es simulado. Con `--execute`: órdenes reales **solo en Bybit Futures Testnet**.
- Prioridad: claridad y robustez sobre optimización prematura.
