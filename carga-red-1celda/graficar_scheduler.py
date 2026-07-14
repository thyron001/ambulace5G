"""
Gráficas para explicar el funcionamiento del scheduler (OFDMA Round-Robin) y
del slicing, a partir de RxPacketTrace_{a,b,c}.txt y del mapeo RNTI->UE.

Genera:
  sched_throughput.png  — throughput entregado por flujo/banda en el tiempo
                          (áreas apiladas; una fila por configuración)
  sched_reparto.png     — reparto medio de recursos (tbSize) por flujo
  sched_mcs.png         — MCS (adaptación de enlace) por UE en el tiempo
"""
import glob

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CFGS = [("a", "Sin carga"), ("b", "Con carga (sin slicing)"), ("c", "Con carga + slicing")]
BIN = 1.0  # tamaño del bin temporal (s)

# --- Mapeo RNTI -> etiqueta de flujo, por configuración ---
def leer_mapeo(cfg):
    amb_rnti = None
    bg = {}  # rnti -> "auto k (rate)"
    for line in open(f"sched_{cfg}.log"):
        if line.startswith("MAPEO,amb,"):
            amb_rnti = int(line.strip().split(",")[2])
        elif line.startswith("MAPEO,bg"):
            p = line.strip().split(",")
            bg[int(p[2])] = f"auto {p[1][2:]} ({float(p[3]):.0f} Mbps)"
    return amb_rnti, bg


def leer_traza(cfg):
    """Devuelve lista de (t, bwp, rnti, tbSize_bits, mcs) del downlink."""
    filas = []
    with open(f"RxPacketTrace_{cfg}.txt") as f:
        next(f)
        for line in f:
            c = line.split()
            if c[1] != "DL":
                continue
            filas.append((float(c[0]), int(c[8]), int(c[10]), int(c[11]), int(c[12])))
    return filas


def etiqueta_flujo(rnti, bwp, amb_rnti, bg, slicing):
    if rnti == amb_rnti:
        if slicing:
            return "Vitales (URLLC)" if bwp == 0 else "Video (eMBB)"
        return "Ambulancia (vitales+video)"
    return bg.get(rnti, f"rnti {rnti}")


COLORES = {
    "Vitales (URLLC)": "crimson", "Video (eMBB)": "steelblue",
    "Ambulancia (vitales+video)": "crimson",
}
AUTO_CMAP = plt.cm.Greys

# ================= Gráfica 1: throughput apilado =================
fig, axes = plt.subplots(len(CFGS), 1, figsize=(11, 10), sharex=True)
fig.suptitle("Scheduler OFDMA — throughput entregado por flujo en el tiempo\n"
             "(el Round-Robin reparte la celda; el slicing aísla el URLLC)", fontsize=13)
for ax, (cfg, titulo) in zip(axes, CFGS):
    amb_rnti, bg = leer_mapeo(cfg)
    filas = leer_traza(cfg)
    if not filas:
        ax.set_title(f"{titulo} (sin datos)")
        continue
    tmax = max(f[0] for f in filas)
    nbins = int(tmax / BIN) + 1
    series = {}
    for (t, bwp, rnti, tb, mcs) in filas:
        et = etiqueta_flujo(rnti, bwp, amb_rnti, bg, cfg == "c")
        series.setdefault(et, np.zeros(nbins))
        series[et][min(int(t / BIN), nbins - 1)] += tb * 8 / BIN / 1e6  # Mbps
    x = np.arange(nbins) * BIN
    # ordenar: vitales/video primero, autos después
    claves = sorted(series, key=lambda k: (0 if "URLLC" in k or "vitales" in k.lower()
                                           else 1 if "eMBB" in k or "Ambulancia" in k
                                           else 2, k))
    autos = [k for k in claves if k.startswith("auto") or k.startswith("rnti")]
    colores = []
    for i, k in enumerate(claves):
        if k in COLORES:
            colores.append(COLORES[k])
        else:
            colores.append(AUTO_CMAP(0.3 + 0.5 * autos.index(k) / max(1, len(autos))))
    ax.stackplot(x, [series[k] for k in claves], labels=claves, colors=colores, alpha=0.85)
    ax.set_title(titulo, fontsize=11)
    ax.set_ylabel("Throughput (Mbps)")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.grid(alpha=0.3)
axes[-1].set_xlabel("Tiempo (s)")
plt.tight_layout()
plt.savefig("sched_throughput.png", dpi=150)
print("Escrito sched_throughput.png")

# ================= Gráfica 2: reparto medio de recursos =================
fig, axes = plt.subplots(1, len(CFGS), figsize=(15, 5))
fig.suptitle("Reparto de recursos del scheduler (bits entregados por flujo)", fontsize=13)
for ax, (cfg, titulo) in zip(axes, CFGS):
    amb_rnti, bg = leer_mapeo(cfg)
    filas = leer_traza(cfg)
    tot = {}
    for (t, bwp, rnti, tb, mcs) in filas:
        et = etiqueta_flujo(rnti, bwp, amb_rnti, bg, cfg == "c")
        tot[et] = tot.get(et, 0) + tb * 8 / 1e6
    claves = sorted(tot, key=lambda k: -tot[k])
    cols = [COLORES.get(k, "0.6") for k in claves]
    ax.barh(range(len(claves)), [tot[k] for k in claves], color=cols)
    ax.set_yticks(range(len(claves)))
    ax.set_yticklabels(claves, fontsize=8)
    ax.invert_yaxis()
    ax.set_title(titulo, fontsize=11)
    ax.set_xlabel("Datos entregados (Mb)")
    ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig("sched_reparto.png", dpi=150)
print("Escrito sched_reparto.png")

# ================= Gráfica 3: MCS por UE en el tiempo =================
fig, axes = plt.subplots(1, len(CFGS), figsize=(15, 5), sharey=True)
fig.suptitle("Adaptación de enlace (MCS) por UE — autos en el borde usan MCS bajo "
             "y consumen más recursos", fontsize=12)
for ax, (cfg, titulo) in zip(axes, CFGS):
    amb_rnti, bg = leer_mapeo(cfg)
    filas = leer_traza(cfg)
    porue = {}
    for (t, bwp, rnti, tb, mcs) in filas:
        et = etiqueta_flujo(rnti, bwp, amb_rnti, bg, cfg == "c")
        porue.setdefault(et, []).append((t, mcs))
    for et, pts in porue.items():
        pts.sort()
        ts = [p[0] for p in pts]
        ms = [p[1] for p in pts]
        col = COLORES.get(et, None)
        ax.plot(ts, ms, ".", ms=2, alpha=0.5, color=col, label=et)
    ax.set_title(titulo, fontsize=11)
    ax.set_xlabel("Tiempo (s)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=6, ncol=2)
axes[0].set_ylabel("MCS (índice de modulación/codificación)")
plt.tight_layout()
plt.savefig("sched_mcs.png", dpi=150)
print("Escrito sched_mcs.png")
