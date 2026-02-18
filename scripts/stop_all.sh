#!/bin/bash
# Detiene todos los procesos (LONG, SHORT, tgbot, dashboard).
# Uso: ./scripts/stop_all.sh

for name in long short tgbot dashboard; do
    session=$(screen -ls 2>/dev/null | grep -E "\.$name[[:space:]]" | head -1 | awk '{print $1}')
    if [ -n "$session" ]; then
        screen -S "$session" -X quit
        echo "  $name: detenido"
    else
        echo "  $name: no estaba corriendo"
    fi
done

echo ""
echo "Sesiones restantes:"
screen -ls 2>/dev/null || echo "  (ninguna)"
