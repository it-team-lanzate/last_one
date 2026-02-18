#!/bin/bash
# Detiene todos los procesos (LONG, SHORT, tgbot, dashboard).
# Uso: ./scripts/stop_all.sh

for name in long short tgbot dashboard; do
    if screen -ls | grep -q "\.$name "; then
        screen -S "$name" -X quit
        echo "  $name: detenido"
    else
        echo "  $name: no estaba corriendo"
    fi
done

echo ""
echo "Sesiones restantes:"
screen -ls 2>/dev/null || echo "  (ninguna)"
