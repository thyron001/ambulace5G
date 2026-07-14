"""
SCRIPT 2 (1 celda) — Toma las rutas generadas y ejecuta las 3 fases.

  Fase 1: filtra los autos que comparten la celda del hospital con la ambulancia
          en los mismos instantes (una sola celda -> mismo gNB). Genera 2 mapas.
  Fase 2: elige una ventana CORTA y muestrea UEs de fondo con tráfico eMBB.
  Fase 3: corre en ns-3 las 3 configuraciones (sin carga / carga / carga+slicing)
          y genera la gráfica comparativa URLLC vs eMBB.

Todas las imágenes quedan en esta carpeta. Simulación corta.

Uso:  python correr_fases.py
"""
import json
import os
import random
import subprocess
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import sumolib

RADIO = 500.0
VENTANA = 15.0          # duración de la ventana ns-3 (s) — corta
ACTIVIDAD = 0.30
MAX_UE = 4              # UEs de fondo (coste ns-3)
RATE_MIN, RATE_MAX = 6.0, 10.0
NS3 = os.path.expanduser("~/ns3-5glena/ns-3-dev")
BIN = f"{NS3}/build/scratch/ns3.40-fase3-carga-optimized"
AQUI = os.path.abspath(".")

net = sumolib.net.readNet("../sumo/cuenca.net.xml")
esc = json.load(open("escenario_1celda.json"))
gcx, gcy = esc["gnb_pos"]
gnb_hosp = esc["gnb_idx"]

# todas las gNBs (para celda servidora = más cercana)
gnb_xy = []
with open("../sumo/gnbs_cobertura.csv") as f:
    next(f)
    for l in f:
        x, y, t = l.strip().split(",")
        gnb_xy.append((float(x), float(y)))
gnb_arr = np.array(gnb_xy)

# =================== FASE 1: filtrado ===================
print("== Fase 1: filtrado de vehículos en la celda del hospital ==")
amb_traj = []                 # (t, x, y)
competidores = {}             # id -> [(x,y)]
for _, elem in ET.iterparse("fcd_todos.xml", events=("end",)):
    if elem.tag != "timestep":
        continue
    t = float(elem.get("time"))
    ids, xs, ys = [], [], []
    for v in elem:
        ids.append(v.get("id")); xs.append(float(v.get("x"))); ys.append(float(v.get("y")))
    elem.clear()
    if "amb" not in ids:
        continue
    P = np.column_stack([xs, ys])
    celda = (((P[:, None, :] - gnb_arr[None, :, :]) ** 2).sum(2)).argmin(1)
    i_amb = ids.index("amb")
    if celda[i_amb] != gnb_hosp:      # ambulancia debe estar en la celda del hospital
        continue
    amb_traj.append((t, float(P[i_amb, 0]), float(P[i_amb, 1])))
    for j, vid in enumerate(ids):
        if vid != "amb" and celda[j] == gnb_hosp:
            competidores.setdefault(vid, []).append((float(P[j, 0]), float(P[j, 1])))

print(f"  Instantes ambulancia en la celda: {len(amb_traj)}")
print(f"  Autos que compartieron la celda : {len(competidores)}")

# ---- Mapas ----
acc_edge = esc.get("accidente_edge")
acc_xy = None
if acc_edge:
    fo = net.getEdge(acc_edge).getShape()
    acc_xy = (sum(p[0] for p in fo) / len(fo), sum(p[1] for p in fo) / len(fo))
axs = [p[1] for p in amb_traj]; ays = [p[2] for p in amb_traj]


def base(ax):
    for e in net.getEdges():
        xs, ys = zip(*e.getShape()); ax.plot(xs, ys, color="0.85", lw=0.4, zorder=1)
    ax.add_patch(plt.Circle((gcx, gcy), RADIO, color="purple", alpha=0.10, zorder=2))
    ax.plot(gcx, gcy, "^", color="purple", ms=15, zorder=6, label=f"gNB {gnb_hosp} (hospital)")
    ax.plot(axs, ays, color="red", lw=2.5, zorder=5, label="Ruta ambulancia")
    ax.plot(axs[0], ays[0], "o", color="green", ms=10, zorder=7, label="Origen")
    ax.plot(axs[-1], ays[-1], "s", color="darkblue", ms=10, zorder=7, label="Hospital")
    if acc_xy:
        ax.plot(*acc_xy, "X", color="red", ms=16, zorder=8, label="Accidente")
    ax.set_aspect("equal"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.set_xlim(gcx - 650, gcx + 650); ax.set_ylim(gcy - 650, gcy + 650)


fig, ax = plt.subplots(figsize=(9, 9)); base(ax)
ax.set_title("1 celda — Ruta de la ambulancia y gNB del hospital")
ax.legend(loc="lower left", fontsize=9); plt.tight_layout()
plt.savefig("mapa1_ruta_gnb.png", dpi=150); print("  Escrito mapa1_ruta_gnb.png")

fig, ax = plt.subplots(figsize=(9, 9)); base(ax)
for k, (vid, pts) in enumerate(competidores.items()):
    cx = [p[0] for p in pts]; cy = [p[1] for p in pts]
    ax.plot(cx, cy, color="teal", lw=0.5, alpha=0.35, zorder=3,
            label=f"Autos competidores ({len(competidores)})" if k == 0 else None)
ax.set_title("1 celda — Autos que compartieron la celda con la ambulancia")
ax.legend(loc="lower left", fontsize=9); plt.tight_layout()
plt.savefig("mapa2_competidores.png", dpi=150); print("  Escrito mapa2_competidores.png")

# =================== FASE 2: muestreo + ventana corta ===================
print("== Fase 2: ventana corta y muestreo de UEs ==")
t0 = amb_traj[0][0]
T0, T1 = t0, t0 + VENTANA
ventana = [p for p in amb_traj if T0 <= p[0] <= T1]

# competidores presentes en la ventana (por su posición mediana) en la celda
rng = random.Random(20)
cand = []
for vid, pts in competidores.items():
    pm = np.median(np.array(pts), axis=0)
    if int(((gnb_arr - pm) ** 2).sum(1).argmin()) == gnb_hosp:
        cand.append((vid, pm.tolist()))
n_act = min(MAX_UE, max(1, round(len(cand) * ACTIVIDAD)))
elegidos = rng.sample(cand, min(n_act, len(cand))) if cand else []
ues = [{"x": p[0], "y": p[1], "rate": round(rng.uniform(RATE_MIN, RATE_MAX), 2)}
       for _, p in elegidos]
print(f"  Ventana [{T0:.0f},{T1:.0f}] s ({VENTANA:.0f} s), {len(ues)} UEs de fondo, "
      f"{sum(u['rate'] for u in ues):.1f} Mbps")

# traza ns-2 de la ambulancia
with open("mobility_amb_1celda.tcl", "w") as f:
    x0, y0 = ventana[0][1], ventana[0][2]
    f.write(f"$node_(0) set X_ {x0:.2f}\n$node_(0) set Y_ {y0:.2f}\n$node_(0) set Z_ 1.5\n")
    for (t, x, y) in ventana:
        f.write(f'$ns_ at {t - T0:.1f} "$node_(0) setdest {x:.2f} {y:.2f} 10.0"\n')

with open("escenario_ns3.txt", "w") as f:
    f.write(f"DUR {VENTANA:.1f}\nNGNB 1\nGNB {gnb_hosp} {gcx:.2f} {gcy:.2f}\n")
    f.write(f"NUE {len(ues)}\n")
    for u in ues:
        f.write(f"UE {u['x']:.2f} {u['y']:.2f} {u['rate']:.2f}\n")

# =================== FASE 3: ns-3 (3 configuraciones) ===================
print("== Fase 3: ns-3 (sin carga / carga / carga+slicing) ==")
resultados = []
for carga, slicing, etq in [(0, 0, "a_sin_carga"), (1, 0, "b_carga"), (1, 1, "c_slicing")]:
    print(f"  corriendo {etq} ...", flush=True)
    env = dict(os.environ, LD_LIBRARY_PATH=f"{NS3}/build/lib")
    out = subprocess.run(
        [BIN, f"--carga={carga}", f"--slicing={slicing}", f"--etiqueta={etq}",
         f"--escenario={AQUI}/escenario_ns3.txt",
         f"--traceFile={AQUI}/mobility_amb_1celda.tcl"],
        capture_output=True, text=True, env=env, cwd=AQUI)
    for line in out.stdout.splitlines():
        if line.startswith("CSV,"):
            resultados.append(line)
with open("resultados_fase3.log", "w") as f:
    f.write("\n".join(resultados) + "\n")
print("  " + "\n  ".join(resultados))

# ---- Gráfica ----
datos = {}
for line in resultados:
    _, e, fl, thr, lat, jit, loss = line.split(",")
    datos[(e, fl)] = dict(thr=float(thr), lat=float(lat), jit=float(jit), loss=float(loss))
ESC = {"a_sin_carga": "Sin carga", "b_carga": "Con carga\n(sin slicing)",
       "c_slicing": "Con carga\n+ slicing"}
ORDEN = ["a_sin_carga", "b_carga", "c_slicing"]


def gv(e, fl, k):
    return datos.get((e, fl), {}).get(k, float("nan"))


fig, axes = plt.subplots(1, 4, figsize=(16, 4.5))
fig.suptitle("Fase 3 (1 celda) — URLLC (signos vitales) vs eMBB (video) bajo carga",
             fontsize=12)
for ax, (k, tt) in zip(axes, [("lat", "Latencia (ms)"), ("jit", "Jitter (ms)"),
                              ("loss", "Pérdida (%)"), ("thr", "Throughput (Mbps)")]):
    x = np.arange(len(ORDEN)); w = 0.38
    vit = [gv(e, "SIGNOS_VITALES_URLLC", k) for e in ORDEN]
    vid = [gv(e, "VIDEO_eMBB", k) for e in ORDEN]
    b1 = ax.bar(x - w / 2, vit, w, color="crimson", label="Vitales (URLLC)")
    b2 = ax.bar(x + w / 2, vid, w, color="slategray", label="Video (eMBB)")
    ax.bar_label(b1, fmt="%.1f", fontsize=8); ax.bar_label(b2, fmt="%.1f", fontsize=8)
    ax.set_title(tt); ax.set_xticks(x); ax.set_xticklabels([ESC[e] for e in ORDEN], fontsize=8)
    ax.grid(axis="y", alpha=0.3)
axes[0].legend(fontsize=8, loc="upper left")
plt.tight_layout(); plt.savefig("fase3_urllc_vs_embb.png", dpi=150)
print("Escrito fase3_urllc_vs_embb.png")
