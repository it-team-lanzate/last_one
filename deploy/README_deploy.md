# Deploy en VPS (Ubuntu/Debian)

## Prerequisitos

```bash
sudo apt update && sudo apt install -y python3-venv git
```

## 1. Clonar y configurar el proyecto

```bash
cd /home/ubuntu
git clone <repo-url> last_last_one
cd last_last_one
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env  # completar BYBIT_API_KEY, BYBIT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

## 2. Descargar datos históricos

```bash
venv/bin/python cli.py fetch-data --end-date today
```

## 3. Instalar los servicios systemd

```bash
# Ajustar el usuario si no es "ubuntu"
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## 4. Habilitar e iniciar

```bash
sudo systemctl enable --now btcbot-long
sudo systemctl enable --now btcbot-short
sudo systemctl enable --now btcbot-tgbot
sudo systemctl enable --now btcbot-dashboard
```

## 5. Verificar estado

```bash
sudo systemctl status btcbot-long
sudo systemctl status btcbot-short
sudo journalctl -u btcbot-long -f     # logs en tiempo real
sudo journalctl -u btcbot-short -f
```

## Comandos útiles

```bash
# Ver logs de las últimas 100 líneas
sudo journalctl -u btcbot-long -n 100

# Reiniciar un servicio
sudo systemctl restart btcbot-long

# Detener todos
sudo systemctl stop btcbot-long btcbot-short btcbot-tgbot btcbot-dashboard

# Deshabilitar (no auto-arranque)
sudo systemctl disable btcbot-long
```

## Cambiar de testnet a mainnet

1. Editar `.env` y completar `BYBIT_API_KEY` y `BYBIT_SECRET` con keys de mainnet
2. Los configs `configs/mainnet.yaml` y `configs/mainnet_short.yaml` ya tienen `execution.broker: mainnet`
3. Los service files apuntan a `mainnet.yaml` por defecto
4. Reiniciar los servicios:
   ```bash
   sudo systemctl restart btcbot-long btcbot-short
   ```

## Actualizar el código

```bash
cd /home/ubuntu/last_last_one
git pull
venv/bin/pip install -r requirements.txt  # solo si cambiaron dependencias
sudo systemctl restart btcbot-long btcbot-short btcbot-tgbot btcbot-dashboard
```

## Backup automático diario

```bash
# Hacer ejecutable el script
chmod +x deploy/backup_state.sh

# Agregar al crontab (backup a las 4 AM UTC)
crontab -e
# Agregar esta línea:
0 4 * * * /home/ubuntu/last_last_one/deploy/backup_state.sh >> /home/ubuntu/backups/backup.log 2>&1
```

Backups locales en `~/backups/btcbot/`, retención 7 días.
Para backup remoto, configurar `BACKUP_S3_BUCKET` en `.env` e instalar `awscli`.

## Notas

- Los services usan `Restart=on-failure` — se reinician solos si crashean, pero no si se detienen limpiamente (Ctrl+C o `systemctl stop`)
- `RestartSec=30s` — espera 30 segundos entre reinicios para evitar loops rápidos
- `EnvironmentFile` — carga el `.env` directamente; las keys nunca aparecen en `ps aux`
- Logs van a systemd journal + al archivo `data/logs/` del proyecto
