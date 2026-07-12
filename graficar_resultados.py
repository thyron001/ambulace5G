import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt

# ---- Configuración ----
XML_FILE = "resultados-ambulancia.xml"
PUERTOS = {5000: "Signos Vitales", 5001: "Video", 5002: "GPS"}
SIM_DURATION = 28.5  # simTime - 1.5 s (tiempo activo de las apps)

def to_ms(valor):
    """Convierte '+1.23e+09ns' de FlowMonitor a milisegundos."""
    return float(valor.replace("ns", "").replace("+", "")) / 1e6

# ---- Parsear XML ----
tree = ET.parse(XML_FILE)
root = tree.getroot()

# 1) Clasificador: mapear flowId -> puerto destino
flujo_nombre = {}
for flow in root.find("Ipv4FlowClassifier").findall("Flow"):
    fid = flow.get("flowId")
    puerto = int(flow.get("destinationPort"))
    if puerto in PUERTOS:
        flujo_nombre[fid] = PUERTOS[puerto]

# 2) Estadísticas por flujo
resultados = {}
for flow in root.find("FlowStats").findall("Flow"):
    fid = flow.get("flowId")
    if fid not in flujo_nombre:
        continue
    nombre = flujo_nombre[fid]
    tx = int(flow.get("txPackets"))
    rx = int(flow.get("rxPackets"))
    rx_bytes = int(flow.get("rxBytes"))
    resultados[nombre] = {
        "throughput_mbps": rx_bytes * 8 / SIM_DURATION / 1e6,
        "latencia_ms": to_ms(flow.get("delaySum")) / rx if rx > 0 else 0,
        "jitter_ms": to_ms(flow.get("jitterSum")) / (rx - 1) if rx > 1 else 0,
        "perdida_pct": 100 * (tx - rx) / tx if tx > 0 else 0,
    }

# ---- Graficar (4 subgráficas de barras) ----
metricas = [
    ("throughput_mbps", "Throughput (Mbps)", "steelblue"),
    ("latencia_ms", "Latencia media (ms)", "darkorange"),
    ("jitter_ms", "Jitter medio (ms)", "seagreen"),
    ("perdida_pct", "Pérdida de paquetes (%)", "firebrick"),
]

nombres = list(resultados.keys())
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle("Simulación 5G - Ambulancia Inteligente (NS-3 / 5G-LENA)", fontsize=14)

for ax, (clave, titulo, color) in zip(axes.flat, metricas):
    valores = [resultados[n][clave] for n in nombres]
    barras = ax.bar(nombres, valores, color=color)
    ax.set_title(titulo)
    ax.grid(axis="y", alpha=0.3)
    ax.bar_label(barras, fmt="%.2f")  # valor encima de cada barra

plt.tight_layout()
plt.savefig("graficas_ambulancia.png", dpi=150)
plt.show()

# ---- Tabla resumen en consola ----
print(f"\n{'Flujo':<16}{'Thr (Mbps)':<12}{'Lat (ms)':<10}{'Jitter (ms)':<12}{'Pérdida (%)':<10}")
for n, r in resultados.items():
    print(f"{n:<16}{r['throughput_mbps']:<12.3f}{r['latencia_ms']:<10.2f}"
          f"{r['jitter_ms']:<12.2f}{r['perdida_pct']:<10.2f}")
