"""FASE 1 — Mapas: (1) ruta+accidente+gNBs visitados; (2) + autos filtrados."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sumolib

net = sumolib.net.readNet("../sumo/cuenca.net.xml")
datos = json.load(open("fase1_datos.json"))

gnb_xy = datos["gnb_xy"]
amb_cells = datos["amb_cells"]
radio = datos["radio"]
amb_traj = datos["amb_traj"]
axs = [p[1] for p in amb_traj]
ays = [p[2] for p in amb_traj]

# centro de la calle del accidente
forma = net.getEdge(datos["accidente_edge"]).getShape()
acc_x = sum(p[0] for p in forma) / len(forma)
acc_y = sum(p[1] for p in forma) / len(forma)


def base(ax):
    for edge in net.getEdges():
        xs, ys = zip(*edge.getShape())
        ax.plot(xs, ys, color="0.85", linewidth=0.4, zorder=1)
    # gNBs que la ambulancia usó, con su cobertura
    for k, c in enumerate(amb_cells):
        gx, gy = gnb_xy[c]
        ax.add_patch(plt.Circle((gx, gy), radio, color="purple", alpha=0.10, zorder=2))
        ax.plot(gx, gy, "^", color="purple", markersize=14, zorder=6,
                label="gNB usada por la ambulancia" if k == 0 else None)
        ax.annotate(f"gNB {c}", (gx, gy), textcoords="offset points",
                    xytext=(9, 9), color="purple", fontsize=10, weight="bold")
    ax.plot(axs, ays, color="red", linewidth=2.5, zorder=5, label="Ruta seguida por la ambulancia")
    ax.plot(axs[0], ays[0], "o", color="green", markersize=11, zorder=7, label="Origen")
    ax.plot(axs[-1], ays[-1], "s", color="darkblue", markersize=11, zorder=7, label="Hospital")
    ax.plot(acc_x, acc_y, "X", color="red", markersize=17, zorder=8, label="Accidente (t=140 s)")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_aspect("equal")
    ax.set_xlim(min(axs) - 700, max(axs) + 700)
    ax.set_ylim(min(ays) - 700, max(ays) + 700)


# --- Mapa 1 ---
fig, ax = plt.subplots(figsize=(11, 10))
base(ax)
ax.set_title("Fase 1 — Ruta de la ambulancia, accidente y gNBs 5G que la sirvieron")
ax.legend(loc="lower left", fontsize=9)
plt.tight_layout()
plt.savefig("mapa1_ruta_gnbs.png", dpi=150)
print("Escrito mapa1_ruta_gnbs.png")

# --- Mapa 2: + rutas de los autos competidores ---
fig, ax = plt.subplots(figsize=(11, 10))
base(ax)
comp = datos["competidores"]
for k, (vid, pts) in enumerate(comp.items()):
    cx = [p[0] for p in pts]
    cy = [p[1] for p in pts]
    ax.plot(cx, cy, color="teal", linewidth=0.5, alpha=0.35, zorder=3,
            label=f"Autos competidores ({len(comp)})" if k == 0 else None)
ax.set_title("Fase 1 — Autos que compartieron celda 5G con la ambulancia\n"
             "(compiten por recursos de red en los mismos instantes)")
ax.legend(loc="lower left", fontsize=9)
plt.tight_layout()
plt.savefig("mapa2_competidores.png", dpi=150)
print("Escrito mapa2_competidores.png")
