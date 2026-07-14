"""
Grafica el SINR de control DL y la distancia a la gNB más cercana durante el
trayecto. Marca los instantes de handover. Sirve para el escenario multi-gNB
y para el de celda única (pasar posiciones por --gnbs "x,y;x,y;...").
"""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GNBS = [(1926.4, 3060.4), (2408.0, 2650.4), (3079.2, 2373.4), (3326.6, 1931.1)]
HANDOVERS = []  # se leen de handovers.txt si existe
SINR_FILE = "DlCtrlSinr.txt"
TRACE_FILE = "mobility_amb.tcl"
SALIDA = "sinr_vs_tiempo.png"
TITULO = "4 gNBs @ 3.5 GHz con handover X2 — traza SUMO Cuenca"

try:
    with open("handovers.txt") as f:
        HANDOVERS = [float(line.split()[0]) for line in f if line.strip()]
except FileNotFoundError:
    pass

# --- SINR medio por segundo ---
suma, cuenta = {}, {}
with open(SINR_FILE) as f:
    next(f)
    for line in f:
        campos = line.split()
        t = int(float(campos[0]))
        sinr = float(campos[5])
        suma[t] = suma.get(t, 0) + sinr
        cuenta[t] = cuenta.get(t, 0) + 1
t_sinr = sorted(suma)
sinr_medio = [suma[t] / cuenta[t] for t in t_sinr]

# --- Distancia a la gNB más cercana desde la traza SUMO ---
t_dist, dist = [], []
with open(TRACE_FILE) as f:
    for line in f:
        p = line.split()
        if len(p) >= 7 and p[1] == "at":
            t = float(p[2])
            x, y = float(p[5]), float(p[6])
            if int(t * 10) % 10 == 0:  # una muestra por segundo
                t_dist.append(t)
                dist.append(min(((x - gx)**2 + (y - gy)**2) ** 0.5
                                for gx, gy in GNBS))

fig, ax1 = plt.subplots(figsize=(12, 5))
ax1.plot(t_sinr, sinr_medio, color="steelblue", label="SINR ctrl DL (dB)")
ax1.axhline(0, color="firebrick", linestyle="--", alpha=0.6, label="SINR = 0 dB")
for i, ho in enumerate(HANDOVERS):
    ax1.axvline(ho, color="purple", linestyle=":", alpha=0.8,
                label="Handover" if i == 0 else None)
ax1.set_xlabel("Tiempo de simulación (s)")
ax1.set_ylabel("SINR (dB)", color="steelblue")
ax1.tick_params(axis="y", labelcolor="steelblue")
ax1.grid(alpha=0.3)

ax2 = ax1.twinx()
ax2.plot(t_dist, dist, color="gray", alpha=0.7, label="Dist. a gNB más cercana (m)")
ax2.set_ylabel("Distancia (m)", color="gray")
ax2.tick_params(axis="y", labelcolor="gray")

l1, e1 = ax1.get_legend_handles_labels()
l2, e2 = ax2.get_legend_handles_labels()
ax1.legend(l1 + l2, e1 + e2, loc="upper right", fontsize=9)

plt.title("SINR y distancia durante el trayecto de la ambulancia\n(" + TITULO + ")")
plt.tight_layout()
plt.savefig(SALIDA, dpi=150)
print(f"Escrito {SALIDA}")
