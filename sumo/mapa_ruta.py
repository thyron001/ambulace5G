"""Dibuja la red vial de Cuenca, la ruta de la ambulancia y la gNB."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sumolib

net = sumolib.net.readNet("cuenca.net.xml")

fig, ax = plt.subplots(figsize=(11, 10))

# Red vial en gris
for edge in net.getEdges():
    shape = edge.getShape()
    xs, ys = zip(*shape)
    ax.plot(xs, ys, color="0.8", linewidth=0.5, zorder=1)

# Trayectoria de la ambulancia (traza ns-2)
xs, ys = [], []
with open("mobility_amb.tcl") as f:
    for line in f:
        parts = line.split()
        if len(parts) >= 7 and parts[1] == "at":
            xs.append(float(parts[5]))
            ys.append(float(parts[6]))
ax.plot(xs, ys, color="red", linewidth=2.5, zorder=3, label="Ruta ambulancia (SUMO)")
ax.plot(xs[0], ys[0], "o", color="green", markersize=10, zorder=4, label="Origen (centro histórico)")
ax.plot(xs[-1], ys[-1], "s", color="darkblue", markersize=10, zorder=4, label="Hospital V. Corral Moscoso")

# gNBs (4 celdas a lo largo de la ruta, escenario con handover)
GNBS = [(1926.4, 3060.4), (2408.0, 2650.4), (3079.2, 2373.4), (3326.6, 1931.1)]
for i, (gx, gy) in enumerate(GNBS):
    ax.plot(gx, gy, "^", color="purple", markersize=14, zorder=5,
            label="gNB 5G (3.5 GHz)" if i == 0 else None)
    ax.annotate(f"celda {2*(i+1)}", (gx, gy), textcoords="offset points",
                xytext=(8, 8), color="purple", fontsize=10, weight="bold")
    circ = plt.Circle((gx, gy), 420, fill=False, color="purple", linestyle="--", alpha=0.4)
    ax.add_patch(circ)

ax.set_title("Escenario: ambulancia 5G sobre mapa real de Cuenca (SUMO + ns-3)")
ax.set_xlabel("x (m)")
ax.set_ylabel("y (m)")
ax.set_aspect("equal")
ax.legend(loc="lower left")
ax.set_xlim(1400, 4200)
ax.set_ylim(1400, 3900)
plt.tight_layout()
plt.savefig("mapa_ruta.png", dpi=150)
print("Escrito mapa_ruta.png")
