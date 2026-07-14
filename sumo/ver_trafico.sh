#!/bin/bash
# Abre la simulación de tráfico de Cuenca en sumo-gui.
# LIBGL_ALWAYS_SOFTWARE evita el "X Fatal error" del binario de pip
# cuando el driver OpenGL del sistema no es compatible.
export LIBGL_ALWAYS_SOFTWARE=1
cd "$(dirname "$0")"
exec ~/sumo-venv/bin/sumo-gui -c cuenca.sumocfg --delay 100 --start \
     --gui-settings-file gui-settings.xml "$@"
