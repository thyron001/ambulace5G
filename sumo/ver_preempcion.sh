#!/bin/bash
# Abre sumo-gui con la simulación de hora pico y la preempción de semáforos
# activada (los semáforos se ponen verdes al acercarse la ambulancia).
#
# Uso:
#   ./ver_preempcion.sh                  # preempción con 5G real (20 ms)
#   ./ver_preempcion.sh --latencia 10    # red degradada
#   ./ver_preempcion.sh --sin-preempcion # línea base, sin preempción
#
# Cualquier argumento extra se pasa a preempcion.py (--dist, --gps, ...).
# La ambulancia (roja) sale en t=100 s: Edit -> Locate -> Vehicles -> "amb",
# clic derecho sobre ella -> Start Tracking para seguirla.

export LIBGL_ALWAYS_SOFTWARE=1   # evita el "X Fatal error" del binario de pip
cd "$(dirname "$0")"
exec ~/sumo-venv/bin/python preempcion.py --gui --latencia 0.02 --dist 300 \
     --etiqueta demo_gui "$@"
