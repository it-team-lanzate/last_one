#!/bin/bash
# Backup diario de state files y base de datos SQLite.
# Cron sugerido (4 AM UTC): 0 4 * * * /home/ubuntu/last_last_one/deploy/backup_state.sh
#
# Backups locales: ~/backups/btcbot/YYYYMMDD/
# Backup remoto S3 (opcional): configurar BACKUP_S3_BUCKET en .env o aquí abajo
#
# Uso: ./deploy/backup_state.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="$HOME/backups/btcbot"
DATE_TAG="$(date -u +%Y%m%d_%H%M%S)"
DEST="$BACKUP_ROOT/$DATE_TAG"
KEEP_DAYS=7

# Cargar .env para leer BACKUP_S3_BUCKET si existe
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
fi

BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-}"

mkdir -p "$DEST"

# ── Archivos a respaldar ───────────────────────────────────────────────────────
FILES=(
    "$PROJECT_ROOT/data/paper_live_state.json"
    "$PROJECT_ROOT/data/paper_live_state_short.json"
    "$PROJECT_ROOT/data/trading.db"
)

copied=0
for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
        cp "$f" "$DEST/"
        echo "  ✓ $(basename "$f")"
        ((copied++))
    else
        echo "  – $(basename "$f") no encontrado, saltando"
    fi
done

echo "Backup local: $DEST ($copied archivos)"

# ── Limpiar backups locales viejos ────────────────────────────────────────────
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +$KEEP_DAYS -exec rm -rf {} + 2>/dev/null || true
echo "Backups locales retenidos: últimos $KEEP_DAYS días"

# ── Backup remoto S3 (opcional) ───────────────────────────────────────────────
if [ -n "$BACKUP_S3_BUCKET" ]; then
    if command -v aws &>/dev/null; then
        aws s3 cp "$DEST" "s3://$BACKUP_S3_BUCKET/btcbot/$DATE_TAG/" --recursive --quiet
        echo "Backup S3: s3://$BACKUP_S3_BUCKET/btcbot/$DATE_TAG/"
    else
        echo "  ⚠ BACKUP_S3_BUCKET configurado pero 'aws' CLI no encontrado. Instalar: pip install awscli"
    fi
fi

echo "Backup completado: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
