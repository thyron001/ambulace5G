"""
Dibuja sobre el mapa las rutas que la ambulancia toma según las condiciones:
  1. Ruta planificada original (por distancia, paso 1)
  2. Ruta re-ruteada por el servidor 5G (más rápida según tráfico real)
  3. Desvío en caliente al bloquearse una calle (accidente en t=135 s)
"""
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sumolib

net = sumolib.net.readNet("cuenca.net.xml")


def trayectoria_fcd(archivo):
    xs, ys = [], []
    for _, elem in ET.iterparse(archivo):
        if elem.tag == "vehicle" and elem.get("id") == "amb":
            xs.append(float(elem.get("x")))
            ys.append(float(elem.get("y")))
        elem.clear()
    return xs, ys


fig, ax = plt.subplots(figsize=(11, 10))

for edge in net.getEdges():
    exs, eys = zip(*edge.getShape())
    ax.plot(exs, eys, color="0.85", linewidth=0.5, zorder=1)

# 1. Ruta original planificada (traza del paso 1)
xs, ys = [], []
with open("mobility_amb.tcl") as f:
    for linea in f:
        p = linea.split()
        if len(p) >= 7 and p[1] == "at":
            xs.append(float(p[5]))
            ys.append(float(p[6]))
ax.plot(xs, ys, color="steelblue", linewidth=2, linestyle="--", zorder=2,
        label="Ruta original por distancia (223 s en ciudad vacía)")

# 2. Ruta re-ruteada por tráfico real
xs, ys = trayectoria_fcd("fcd_congA.xml")
ax.plot(xs, ys, color="seagreen", linewidth=2.5, zorder=3,
        label="Re-ruteo del servidor 5G en hora pico (181 s)")

# 3. Desvío en caliente por accidente
xs, ys = trayectoria_fcd("fcd_accidente.xml")
ax.plot(xs, ys, color="darkorange", linewidth=2.5, zorder=4,
        label="Desvío en caliente por accidente (211 s; sin re-ruteo: 333 s)")

# Marcador del accidente (centro de la calle bloqueada)
forma = net.getEdge("60204533").getShape()
cx = sum(p[0] for p in forma) / len(forma)
cy = sum(p[1] for p in forma) / len(forma)
ax.plot(cx, cy, "X", color="red", markersize=16, zorder=6,
        label="Accidente (t=135 s)")

ax.plot(1990, 3402, "o", color="green", markersize=11, zorder=5,
        label="Origen (centro histórico)")
ax.plot(3631, 2042, "s", color="darkblue", markersize=11, zorder=5,
        label="Hospital V. Corral Moscoso")

ax.set_title("Re-ruteo dinámico de la ambulancia según el tráfico en tiempo real\n"
             "(servidor de control 5G + TraCI, Cuenca)")
ax.set_xlabel("x (m)")
ax.set_ylabel("y (m)")
ax.set_aspect("equal")
ax.legend(loc="lower left", fontsize=9)
ax.set_xlim(1400, 4200)
ax.set_ylim(1400, 3900)
plt.tight_layout()
plt.savefig("rutas_dinamicas.png", dpi=150)
print("Escrito rutas_dinamicas.png")
