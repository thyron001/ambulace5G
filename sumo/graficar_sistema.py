"""Gráfica de ablación del sistema de emergencia: qué aporta cada componente
(preempción de semáforos, re-ruteo dinámico, subida a la vereda)."""
import csv
from statistics import mean, stdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ETIQUETAS = {
    "sin_asistencia": "Sin\nasistencia",
    "solo_preempcion": "Solo\npreempción",
    "solo_reroute": "Solo\nre-ruteo",
    "sistema_completo": "Sistema completo\n(preempción + re-ruteo\n+ vereda)",
}
ORDEN = ["sin_asistencia", "solo_preempcion", "solo_reroute", "sistema_completo"]
COLORES = ["firebrick", "goldenrod", "steelblue", "seagreen"]

filas = {}
descartadas = 0
with open("resultados_preempcion.csv") as f:
    for fila in csv.DictReader(f):
        if int(fila.get("amb_teleports", 0)) > 0 or fila["viaje_s"] == "nan":
            descartadas += 1
            continue
        filas.setdefault(fila["escenario"], []).append(fila)
if descartadas:
    print(f"AVISO: {descartadas} corridas descartadas (teleport o sin llegada)")

def agg(escenario, campo):
    vals = [float(f[campo]) for f in filas[escenario]]
    return mean(vals), (stdev(vals) if len(vals) > 1 else 0.0)

nombres = [ETIQUETAS[e] for e in ORDEN]
metricas = [("viaje_s", "Tiempo de viaje al hospital (s)"),
            ("detenida_s", "Tiempo detenida (s)"),
            ("paradas", "Número de detenciones")]

n_min = min(len(filas[e]) for e in ORDEN)
fig, axes = plt.subplots(1, 3, figsize=(15, 5.5))
fig.suptitle("Sistema 5G de asistencia a la ambulancia — aporte de cada componente\n"
             f"(hora pico en Cuenca; media de {n_min}+ semillas)", fontsize=13)

for ax, (campo, titulo) in zip(axes, metricas):
    medias, errores = zip(*[agg(e, campo) for e in ORDEN])
    barras = ax.bar(nombres, medias, yerr=errores, capsize=5, color=COLORES)
    ax.set_title(titulo)
    ax.bar_label(barras, fmt="%.0f", padding=3)
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(axis="x", labelsize=8)

base, _ = agg("sin_asistencia", "viaje_s")
for i, e in enumerate(ORDEN[1:], start=1):
    m, _ = agg(e, "viaje_s")
    if base - m > 1:
        axes[0].annotate(f"−{base - m:.0f} s", (i, m / 2), ha="center",
                         color="white", weight="bold", fontsize=11)

plt.tight_layout()
plt.savefig("sistema_comparacion.png", dpi=150)
print("Escrito sistema_comparacion.png")

print(f"\n{'Escenario':<18}{'Viaje (s)':<18}{'Detenida (s)':<18}{'Paradas'}")
for e in ORDEN:
    v, sv = agg(e, "viaje_s")
    d, sd = agg(e, "detenida_s")
    p, sp = agg(e, "paradas")
    print(f"{e:<18}{v:6.1f} ± {sv:<8.1f}{d:6.1f} ± {sd:<8.1f}{p:4.1f} ± {sp:.1f}")
