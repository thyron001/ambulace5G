"""Mide qué fracción de las calles tiene vehículos durante la simulación."""
import os
import traci

binario = os.path.expanduser("~/sumo-venv/bin/sumo")
traci.start([binario, "-c", "cuenca-rush.sumocfg", "--no-step-log", "true",
             "--duration-log.disable", "true", "--end", "260"])

aristas = [e for e in traci.edge.getIDList() if not e.startswith(":")]
con_autos = set()
while traci.simulation.getTime() < 259:
    traci.simulationStep(traci.simulation.getTime() + 5)
    for e in aristas:
        if traci.edge.getLastStepVehicleNumber(e) > 0:
            con_autos.add(e)
n_activos = traci.vehicle.getIDCount()
teleports = traci.simulation.getEndingTeleportNumber()
traci.close()

print(f"Calles con vehículos (t=0-260 s): {len(con_autos)}/{len(aristas)} "
      f"({100 * len(con_autos) / len(aristas):.0f}%)")
print(f"Vehículos circulando simultáneamente al final: {n_activos}")
