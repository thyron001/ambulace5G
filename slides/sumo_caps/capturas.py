"""Capturas de sumo-gui vía TraCI: tráfico, ambulancia, accidente con marcador."""
import os
import traci

SUMO = os.path.expanduser("~/sumo-venv/bin/sumo-gui")
CFG = "../../sumo/cuenca-rush.sumocfg"
OUT = os.path.abspath(".")
V = "View #0"
ACC = "60204533"


def cap(nombre):
    # dos pasos para que el frame se renderice antes de guardar
    traci.gui.screenshot(V, f"{OUT}/{nombre}.png")
    traci.simulationStep()
    traci.simulationStep()


traci.start([SUMO, "-c", CFG, "--seed", "3", "--start", "true",
             "--window-size", "1400,900", "--delay", "0",
             "--no-warnings", "true"])
traci.gui.setSchema(V, "real world")

# 1) Vista general del tráfico de la ciudad (t=70 s)
traci.simulationStep(70)
traci.gui.setZoom(V, 300)
traci.gui.setOffset(V, 2650, 2450)
cap("01_trafico_ciudad")

# 2) La ambulancia entre el tráfico (sale en t=100 s)
traci.simulationStep(115)
traci.gui.trackVehicle(V, "amb")
traci.gui.setZoom(V, 2800)
traci.simulationStep(116)
cap("02_ambulancia_trafico")

# 3) Accidente con marcador visual (t=135 s)
traci.simulationStep(135)
traci.edge.setMaxSpeed(ACC, 0.3)
forma = traci.lane.getShape(ACC + "_0")
traci.polygon.add("acc", forma, (220, 30, 30, 255), False, layer=20, lineWidth=6)
cx = sum(p[0] for p in forma) / len(forma)
cy = sum(p[1] for p in forma) / len(forma)
traci.poi.add("ACCIDENTE", cx, cy, (230, 0, 0, 255), poiType="acc", layer=21, width=25)
try:
    traci.gui.trackVehicle(V, "")   # dejar de seguir a la ambulancia
except traci.TraCIException:
    pass
traci.simulationStep(138)
traci.gui.setOffset(V, cx, cy)
traci.gui.setZoom(V, 3200)
traci.simulationStep(139)
cap("03_accidente")

# 4) Detalle de una intersección con semáforo y colas (misma zona)
traci.gui.setZoom(V, 5000)
traci.simulationStep(141)
cap("04_interseccion")

traci.close()
print("Capturas guardadas en", OUT)
