#!/bin/bash
# Inicia LONG, SHORT, bot Telegram y Dashboard en sesiones screen separadas.
# Uso: ./scripts/start_all.sh   (ejecutar desde la raíz del proyecto)
# Requiere: screen instalado (sudo apt install -y screen)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_ACTIVATE="$PROJECT_ROOT/venv/bin/activate"
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "Error: venv no encontrado en $PROJECT_ROOT/venv"
    exit 1
fi

# Verificar que screen está instalado
if ! command -v screen &> /dev/null; then
    echo "Error: screen no está instalado. Ejecuta: sudo apt install -y screen"
    exit 1
fi

# Actualizar datos OHLCV
echo "Actualizando datos OHLCV..."
source "$VENV_ACTIVATE"
python cli.py fetch-data --end-date today
echo ""

start_session() {
    local name=$1
    local cmd=$2
    if screen -ls | grep -q "\.$name "; then
        echo "  $name: ya existe (usa 'screen -r $name' para entrar)"
    else
        screen -dmS "$name" bash -c "source $VENV_ACTIVATE && cd $PROJECT_ROOT && $cmd; exec bash"
        echo "  $name: iniciado"
    fi
}

echo "Iniciando procesos en screen..."
echo ""

start_session long "python cli.py paper-live --config configs/live.yaml --execute --log-dir data/logs"
start_session short "python cli.py paper-live --config configs/live_short.yaml --execute --log-dir data/logs"
start_session tgbot "python cli.py telegram-bot --log-dir data/logs"
start_session dashboard "streamlit run src/dashboard/app.py --server.port 8501 --server.address 0.0.0.0"

echo ""
echo "Listo. Sesiones activas:"
screen -ls
echo ""
echo "Comandos útiles:"
echo "  screen -r long      # entrar a LONG"
echo "  screen -r short     # entrar a SHORT"
echo "  screen -r tgbot     # entrar a bot Telegram"
echo "  screen -r dashboard # entrar a Dashboard"
echo "  Ctrl+A, luego D     # salir de screen sin matar el proceso"
