"""FASE 3 — Comparativa URLLC vs eMBB bajo carga (sin carga / carga / slicing)."""
import csv
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

LOG = "resultados_fase3.log"  # log con líneas CSV,escenario,flujo,thr,lat,jit,loss
ESC = {
    "a_sin_carga": "Sin carga\n(solo ambulancia)",
    "b_carga": "Con carga\n(sin slicing)",
    "c_slicing": "Con carga\n+ slicing 2 bandas",
}
ORDEN = ["a_sin_carga", "b_carga", "c_slicing"]

datos = {}
with open(LOG) as f:
    for line in f:
        if line.startswith("CSV,"):
            _, esc, flujo, thr, lat, jit, loss = line.strip().split(",")
            datos[(esc, flujo)] = dict(thr=float(thr), lat=float(lat),
                                       jit=float(jit), loss=float(loss))

def v(esc, flujo, k):
    return datos.get((esc, flujo), {}).get(k, float("nan"))

fig, axes = plt.subplots(1, 4, figsize=(17, 5))
fig.suptitle("Fase 3 — Signos vitales (URLLC) vs Video (eMBB) de la ambulancia bajo "
             "carga de tráfico vehicular\n(1 celda, downlink; slicing = banda dedicada "
             "de 2 MHz para URLLC)", fontsize=12)

metricas = [("lat", "Latencia (ms)"), ("jit", "Jitter (ms)"),
            ("loss", "Pérdida (%)"), ("thr", "Throughput (Mbps)")]
x = np.arange(len(ORDEN))
w = 0.38
for ax, (k, titulo) in zip(axes, metricas):
    vit = [v(e, "SIGNOS_VITALES_URLLC", k) for e in ORDEN]
    vid = [v(e, "VIDEO_eMBB", k) for e in ORDEN]
    b1 = ax.bar(x - w / 2, vit, w, color="crimson", label="Signos vitales (URLLC)")
    b2 = ax.bar(x + w / 2, vid, w, color="slategray", label="Video (eMBB)")
    ax.bar_label(b1, fmt="%.1f", fontsize=8)
    ax.bar_label(b2, fmt="%.1f", fontsize=8)
    ax.set_title(titulo)
    ax.set_xticks(x)
    ax.set_xticklabels([ESC[e] for e in ORDEN], fontsize=8)
    ax.grid(axis="y", alpha=0.3)
axes[0].legend(fontsize=9, loc="upper left")

plt.tight_layout()
plt.savefig("fase3_urllc_vs_embb.png", dpi=150)
print("Escrito fase3_urllc_vs_embb.png")

print(f"\n{'Escenario':<22}{'Flujo':<22}{'Lat(ms)':<10}{'Jit(ms)':<10}"
      f"{'Perd(%)':<10}{'Thr(Mbps)'}")
for e in ORDEN:
    for fl in ["SIGNOS_VITALES_URLLC", "VIDEO_eMBB"]:
        print(f"{ESC[e].replace(chr(10),' '):<22}{fl:<22}{v(e,fl,'lat'):<10.2f}"
              f"{v(e,fl,'jit'):<10.2f}{v(e,fl,'loss'):<10.2f}{v(e,fl,'thr'):.3f}")
