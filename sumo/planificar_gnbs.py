"""
Planifica gNBs 5G adicionales para cubrir todo el mapa de Cuenca.

- Rejilla hexagonal con distancia entre sitios ISD=800 m (radio de buen
  servicio ~500 m a 3.5 GHz / 43 dBm, según lo medido en ns-3: el SINR se
  degrada fuerte más allá de ~500-600 m en NLOS urbano).
- Solo se colocan sitios donde hay calles a menos de 250 m (mancha urbana).
- Las 4 gNBs existentes de la ruta de la ambulancia NO se tocan: la rejilla
  omite los puntos que ya quedan cubiertos por ellas.

Salidas: gnbs_cobertura.csv (todas las estaciones) y mapa_cobertura_5g.png.
"""
import csv
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sumolib

RADIO = 500.0   # radio de buen servicio (m)
ISD = 800.0     # distancia entre sitios de la rejilla (m)
URBANO = 250.0  # debe haber calles a esta distancia para poner un sitio

EXISTENTES = [(1926.4, 3060.4), (2408.0, 2650.4), (3079.2, 2373.4), (3326.6, 1931.1)]

net = sumolib.net.readNet("cuenca.net.xml")
xmin, ymin, xmax, ymax = net.getBoundary()

# --- Rejilla hexagonal sobre el mapa ---
dy = ISD * math.sqrt(3) / 2
candidatos = []
fila = 0
y = ymin + dy / 2
while y < ymax:
    x0 = xmin + (ISD / 2 if fila % 2 else ISD / 4)
    x = x0
    while x < xmax:
        candidatos.append((x, y))
        x += ISD
    y += dy
    fila += 1

# --- Filtros: mancha urbana y cercanía a las existentes ---
nuevas = []
for (x, y) in candidatos:
    if any(math.hypot(x - ex, y - ey) < RADIO for ex, ey in EXISTENTES):
        continue  # esa zona ya la cubre una estación de la ruta
    if not net.getNeighboringEdges(x, y, URBANO):
        continue  # sin calles cerca: fuera de la mancha urbana
    nuevas.append((x, y))

print(f"Rejilla: {len(candidatos)} candidatos -> {len(nuevas)} gNBs nuevas "
      f"(+{len(EXISTENTES)} existentes = {len(nuevas) + len(EXISTENTES)} sitios)")

with open("gnbs_cobertura.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["x", "y", "tipo"])
    for x, y in EXISTENTES:
        w.writerow([round(x, 1), round(y, 1), "ruta"])
    for x, y in nuevas:
        w.writerow([round(x, 1), round(y, 1), "cobertura"])

# --- Mapa ---
fig, ax = plt.subplots(figsize=(12, 11))
for edge in net.getEdges():
    xs, ys = zip(*edge.getShape())
    ax.plot(xs, ys, color="0.8", linewidth=0.5, zorder=1)

for i, (x, y) in enumerate(nuevas):
    ax.add_patch(plt.Circle((x, y), RADIO, color="teal", alpha=0.12, zorder=2))
    ax.plot(x, y, "^", color="teal", markersize=9, zorder=4,
            label="gNB nueva (cobertura ciudad)" if i == 0 else None)

for i, (x, y) in enumerate(EXISTENTES):
    ax.add_patch(plt.Circle((x, y), RADIO, color="purple", alpha=0.15, zorder=3))
    ax.plot(x, y, "^", color="purple", markersize=13, zorder=5,
            label="gNB existente (ruta ambulancia)" if i == 0 else None)
    ax.annotate(f"celda {2 * (i + 1)}", (x, y), textcoords="offset points",
                xytext=(8, 8), color="purple", fontsize=9, weight="bold")

ax.set_title(f"Cobertura 5G de Cuenca: {len(EXISTENTES)} gNBs de la ruta + "
             f"{len(nuevas)} nuevas\n(3.5 GHz, 43 dBm — radio de buen servicio "
             f"{RADIO:.0f} m, ISD {ISD:.0f} m)")
ax.set_xlabel("x (m)")
ax.set_ylabel("y (m)")
ax.set_aspect("equal")
ax.legend(loc="lower right")
ax.set_xlim(xmin - 100, xmax + 100)
ax.set_ylim(ymin - 100, ymax + 100)
plt.tight_layout()
plt.savefig("mapa_cobertura_5g.png", dpi=150)
print("Escrito mapa_cobertura_5g.png y gnbs_cobertura.csv")
