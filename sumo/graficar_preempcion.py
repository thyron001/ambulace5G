"""Gráfica comparativa de preempción: media ± desviación sobre varias semillas."""
import csv
from statistics import mean, stdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ETIQUETAS = {
    "sin_preempcion": "Sin\npreempción",
    "5G_20ms": "5G real\n(20 ms)",
    "degradada_10s": "Red degradada\n(10 s)",
    "degradada_30s": "Red degradada\n(30 s)",
}
ORDEN = ["sin_preempcion", "5G_20ms", "degradada_10s", "degradada_30s"]
COLORES = ["firebrick", "seagreen", "goldenrod", "darkorange"]

filas = {}
descartadas = 0
with open("resultados_preempcion.csv") as f:
    for fila in csv.DictReader(f):
        if int(fila.get("amb_teleports", 0)) > 0 or fila["viaje_s"] == "nan":
            descartadas += 1  # ambulancia teletransportada o sin llegar
            continue
        filas.setdefault(fila["escenario"], []).append(fila)
if descartadas:
    print(f"AVISO: {descartadas} corridas descartadas (teleport o sin llegada)")

def agg(escenario, campo):
    vals = [float(f[campo]) for f in filas[escenario]]
    return mean(vals), (stdev(vals) if len(vals) > 1 else 0.0)

nombres = [ETIQUETAS[e] for e in ORDEN]
metricas = [
    ("viaje_s", "Tiempo de viaje al hospital (s)"),
    ("detenida_s", "Tiempo detenida (s)"),
    ("paradas", "Número de detenciones"),
]

n_seeds = min(len(filas[e]) for e in ORDEN)
fig, axes = plt.subplots(1, 3, figsize=(14, 5))
fig.suptitle("Preempción de semáforos vía 5G — ambulancia en hora pico "
             f"(Cuenca, SUMO/TraCI; media de {n_seeds} semillas)", fontsize=13)

for ax, (campo, titulo) in zip(axes, metricas):
    medias, errores = zip(*[agg(e, campo) for e in ORDEN])
    barras = ax.bar(nombres, medias, yerr=errores, capsize=5, color=COLORES)
    ax.set_title(titulo)
    ax.bar_label(barras, fmt="%.0f", padding=3)
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(axis="x", labelsize=9)

base, _ = agg("sin_preempcion", "viaje_s")
for i, e in enumerate(ORDEN[1:], start=1):
    m, _ = agg(e, "viaje_s")
    axes[0].annotate(f"−{base - m:.0f} s", (i, m / 2), ha="center",
                     color="white", weight="bold", fontsize=11)

plt.tight_layout()
plt.savefig("preempcion_comparacion.png", dpi=150)
print(f"Escrito preempcion_comparacion.png ({n_seeds} semillas por escenario)")

print(f"\n{'Escenario':<16}{'Viaje (s)':<18}{'Detenida (s)':<18}{'Paradas'}")
for e in ORDEN:
    v, sv = agg(e, "viaje_s")
    d, sd = agg(e, "detenida_s")
    p, sp = agg(e, "paradas")
    print(f"{e:<16}{v:6.1f} ± {sv:<8.1f}{d:6.1f} ± {sd:<8.1f}{p:4.1f} ± {sp:.1f}")
