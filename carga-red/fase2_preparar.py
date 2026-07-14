"""
FASE 2 — Muestreo de UEs activos y preparación de la ventana para ns-3.

- Ventana corta [T0, T1] que cubre 2-3 celdas del viaje.
- Factor de actividad: no todos los autos transmiten a la vez; se instancia
  una fracción (ACTIVIDAD) de los competidores medios por celda como UEs
  activos, colocados en posiciones reales (snapshot) dentro de su celda.
- Cada UE de fondo recibe una tasa eMBB aleatoria realista (1-4 Mbps).
- La ambulancia se exporta como traza de movilidad ns-2 de la ventana.

Salidas: escenario_ventana.json (gNBs, UEs de fondo, tasas) y
mobility_amb_ventana.tcl (traza ns-2 de la ambulancia, t=0 al inicio).
"""
import json
import random

import numpy as np

T0, T1 = 150.0, 198.0          # ventana (s): una sola celda (21), sin handover
ACTIVIDAD = 0.30               # fracción de competidores transmitiendo
MAX_UE_CELDA = 5               # UEs de fondo en la celda (estudio de carga)
RATE_MIN, RATE_MAX = 6.0, 10.0  # Mbps eMBB por UE (satura la celda)
rng = random.Random(20)

d = json.load(open("fase1_datos.json"))
gnb_xy = d["gnb_xy"]
amb_traj = [p for p in d["amb_traj"] if T0 <= p[0] <= T1]
cells_ventana = sorted({p[3] for p in amb_traj})
print(f"Ventana [{T0},{T1}] s: celdas {cells_ventana}")

# --- Competidores por celda en la ventana (para dimensionar la carga) ---
# Reconstruimos, por celda, qué autos estuvieron y su última posición vista.
comp = d["competidores"]  # id -> lista de (x,y) en instantes de coincidencia
# necesitamos saber a qué celda pertenecía cada competidor; recalculamos por
# cercanía de su posición media a las gNBs de la ventana.
gnb_arr = np.array(gnb_xy)
por_celda = {c: [] for c in cells_ventana}
for vid, pts in comp.items():
    p = np.array(pts)
    # posición representativa (mediana) del auto mientras competía
    pm = np.median(p, axis=0)
    d2 = ((gnb_arr[cells_ventana] - pm) ** 2).sum(axis=1)
    c = cells_ventana[int(d2.argmin())]
    # solo si su celda servidora real (de las 35) es una de la ventana
    d2all = ((gnb_arr - pm) ** 2).sum(axis=1)
    if int(d2all.argmin()) == c:
        por_celda[c].append((vid, pm.tolist()))

# --- Muestreo de UEs activos ---
ues_fondo = []
for c in cells_ventana:
    autos = por_celda[c]
    n_activos = min(MAX_UE_CELDA, max(1, round(len(autos) * ACTIVIDAD)))
    elegidos = rng.sample(autos, min(n_activos, len(autos))) if autos else []
    for vid, pos in elegidos:
        ues_fondo.append({
            "id": vid, "celda": c, "x": pos[0], "y": pos[1],
            "rate_mbps": round(rng.uniform(RATE_MIN, RATE_MAX), 2)})
    print(f"  celda {c}: {len(autos)} competidores -> {len(elegidos)} UEs activos "
          f"(factor {ACTIVIDAD})")

carga_total = sum(u["rate_mbps"] for u in ues_fondo)
print(f"UEs de fondo totales: {len(ues_fondo)}  |  carga eMBB agregada: "
      f"{carga_total:.1f} Mbps")

# --- Traza ns-2 de la ambulancia en la ventana ---
with open("mobility_amb_ventana.tcl", "w") as f:
    x0, y0 = amb_traj[0][1], amb_traj[0][2]
    f.write(f"$node_(0) set X_ {x0:.2f}\n$node_(0) set Y_ {y0:.2f}\n"
            f"$node_(0) set Z_ 1.5\n")
    for (t, x, y, c) in amb_traj:
        v = 12.0
        f.write(f'$ns_ at {t - T0:.1f} "$node_(0) setdest {x:.2f} {y:.2f} {v:.2f}"\n')

escenario = {
    "t0": T0, "t1": T1, "dur": T1 - T0,
    "cells": cells_ventana,
    "gnb_pos": {str(c): gnb_xy[c] for c in cells_ventana},
    "ues_fondo": ues_fondo,
    "amb_xy0": [amb_traj[0][1], amb_traj[0][2]],
}
json.dump(escenario, open("escenario_ventana.json", "w"), indent=1)
print("Escrito escenario_ventana.json y mobility_amb_ventana.tcl")
