"""
FASE 1 — Identificación de gNBs de la ruta y filtrado de autos competidores.

Criterio de competencia por recursos: dos vehículos compiten por PRBs si en el
MISMO instante están servidos por la MISMA celda. La celda servidora de cada
vehículo es la gNB MÁS CERCANA de las 35 del despliegue (por eso hacía falta
cubrir toda la ciudad, no solo la ruta).

Procedimiento:
  1. Se recorre el FCD de todos los autos (muestreado cada 1 s).
  2. En cada instante se calcula la celda servidora de cada vehículo.
  3. gNBs de la ambulancia = celdas servidoras que tuvo durante su viaje.
  4. Competidor = auto cuya celda servidora coincidió con la de la ambulancia
     en algún instante en que ambos estaban activos.

Salidas: fase1_datos.json (para los mapas y la fase 2) y un resumen por pantalla.
"""
import json
import xml.etree.ElementTree as ET

import numpy as np

RADIO = 500.0
FCD = "fcd_todos.xml"
GNBS = "../sumo/gnbs_cobertura.csv"
ACCIDENTE_EDGE = "389741419"

# --- Cargar gNBs ---
gnb_xy = []
gnb_tipo = []
with open(GNBS) as f:
    next(f)
    for linea in f:
        x, y, tipo = linea.strip().split(",")
        gnb_xy.append((float(x), float(y)))
        gnb_tipo.append(tipo)
gnb_xy = np.array(gnb_xy)          # (35, 2)
n_gnb = len(gnb_xy)

# --- Recorrer FCD ---
# Por instante: posiciones de todos los vehículos y su celda servidora.
amb_traj = []                       # [(t, x, y, celda), ...]
amb_cells = set()                   # celdas servidoras que tuvo la ambulancia
competidores = {}                   # id -> lista de (x, y)
carga = {}                          # celda -> {t: n_vehiculos_servidos}
# primero: para poder cruzar por instante, guardamos por timestep
# el vehículo->celda; procesamos en streaming.

for _, elem in ET.iterparse(FCD, events=("end",)):
    if elem.tag != "timestep":
        continue
    t = float(elem.get("time"))
    ids, xs, ys = [], [], []
    for v in elem:
        ids.append(v.get("id"))
        xs.append(float(v.get("x")))
        ys.append(float(v.get("y")))
    elem.clear()
    if not ids:
        continue
    P = np.column_stack([xs, ys])                       # (N, 2)
    # celda servidora = gNB más cercana, solo si dentro del radio
    d2 = ((P[:, None, :] - gnb_xy[None, :, :]) ** 2).sum(axis=2)  # (N, 35)
    celda = d2.argmin(axis=1)
    dist_min = np.sqrt(d2[np.arange(len(ids)), celda])
    servida = dist_min <= RADIO                          # dentro de cobertura

    # ¿está la ambulancia en este instante?
    if "amb" not in ids:
        continue
    i_amb = ids.index("amb")
    if not servida[i_amb]:
        continue
    celda_amb = int(celda[i_amb])
    amb_traj.append((t, float(P[i_amb, 0]), float(P[i_amb, 1]), celda_amb))
    amb_cells.add(celda_amb)

    # competidores: mismo celda servidora que la ambulancia, en este instante
    for j, vid in enumerate(ids):
        if vid == "amb" or not servida[j]:
            continue
        c = int(celda[j])
        # carga de las celdas de la ruta (para gráfica de ocupación)
        if c == celda_amb:
            competidores.setdefault(vid, []).append((float(P[j, 0]), float(P[j, 1])))
    # carga instantánea de la celda de la ambulancia
    n_serv = int(((celda == celda_amb) & servida).sum())
    carga.setdefault(str(celda_amb), {})[f"{t:.0f}"] = n_serv

print(f"Instantes con ambulancia en cobertura : {len(amb_traj)}")
print(f"gNBs que la ambulancia usó (de {n_gnb}) : {sorted(amb_cells)}")
print(f"Autos competidores (compartieron celda): {len(competidores)}")

datos = {
    "radio": RADIO,
    "gnb_xy": gnb_xy.tolist(),
    "gnb_tipo": gnb_tipo,
    "amb_cells": sorted(amb_cells),
    "amb_traj": amb_traj,
    "competidores": competidores,
    "carga": carga,
    "accidente_edge": ACCIDENTE_EDGE,
}
with open("fase1_datos.json", "w") as f:
    json.dump(datos, f)
print("Escrito fase1_datos.json")
