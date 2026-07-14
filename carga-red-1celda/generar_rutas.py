"""
SCRIPT 1 (1 celda) — Genera las rutas de la ambulancia y de los autos, y corre
SUMO exportando el FCD de todos los vehículos.

Escenario acotado a UNA sola celda 5G: la del hospital (gNB 3). La ambulancia
sale del extremo opuesto de la celda y va al hospital (~1 km, todo dentro de la
cobertura). Simulación corta.

Uso:
  python generar_rutas.py                      # semilla por defecto, sin accidente
  python generar_rutas.py --seed 7             # otra semilla de tráfico
  python generar_rutas.py --accidente auto@30  # accidente aleatorio (según seed)
  python generar_rutas.py --accidente 84861608@30   # bloquear una calle concreta

Salidas: fcd_todos.xml, ambulancia_1celda.rou.xml, escenario_1celda.json
"""
import argparse
import json
import math
import os

import sumolib
import traci

SUMO = os.path.expanduser("~/sumo-venv/bin/sumo")
NET = "../sumo/cuenca.net.xml"
GNBS = "../sumo/gnbs_cobertura.csv"
HOSPITAL = (3631.0, 2042.0)
AMB = "amb"
DEPART_AMB = 20.0     # la ambulancia sale en t=20 s (tras algo de tráfico)


def arista_cercana(net, x, y, r=300):
    c = [(e, d) for e, d in net.getNeighboringEdges(x, y, r) if e.allows("passenger")]
    c.sort(key=lambda z: z[1])
    return c[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--accidente", default=None, metavar="ARISTA@T",
                    help="'auto@T' (aleatorio por seed) o 'idCalle@T'")
    ap.add_argument("--gui", action="store_true")
    args = ap.parse_args()

    net = sumolib.net.readNet(NET)
    gnbs = []
    with open(GNBS) as f:
        next(f)
        for l in f:
            x, y, t = l.strip().split(",")
            gnbs.append((float(x), float(y)))
    gi = min(range(len(gnbs)),
             key=lambda i: math.hypot(gnbs[i][0] - HOSPITAL[0], gnbs[i][1] - HOSPITAL[1]))
    gcx, gcy = gnbs[gi]

    # --- Ruta de la ambulancia: extremo opuesto de la celda -> hospital ---
    edest = arista_cercana(net, *HOSPITAL)
    vx, vy = gcx - HOSPITAL[0], gcy - HOSPITAL[1]
    n = math.hypot(vx, vy)
    ox, oy = gcx + vx / n * 430, gcy + vy / n * 430
    eorig = arista_cercana(net, ox, oy)
    ruta, _ = net.getShortestPath(eorig, edest, vClass="passenger")
    ids = " ".join(e.getID() for e in ruta)
    print(f"Celda del hospital: gNB {gi} en ({gcx:.0f},{gcy:.0f})")
    print(f"Ruta ambulancia: {len(ruta)} aristas, "
          f"{sum(e.getLength() for e in ruta):.0f} m (origen {eorig.getID()})")

    with open("ambulancia_1celda.rou.xml", "w") as f:
        f.write(f"""<routes>
    <vType id="ambulancia" vClass="emergency" color="1,0,0" guiShape="emergency"
           speedFactor="1.5" accel="3.5" decel="6.0" maxSpeed="33"
           width="2.1" minGapLat="0.25" lcSublane="2.0" lcPushy="1.0" lcAssertive="2.0"/>
    <route id="r" edges="{ids}"/>
    <vehicle id="{AMB}" type="ambulancia" route="r" depart="{DEPART_AMB}" departSpeed="max">
        <param key="has.bluelight.device" value="true"/>
    </vehicle>
</routes>
""")

    # --- Config SUMO (tráfico de fondo de la ciudad ya generado) ---
    with open("cuenca_1celda.sumocfg", "w") as f:
        f.write(f"""<configuration>
  <input>
    <net-file value="../sumo/cuenca.net.xml"/>
    <route-files value="../sumo/rush.trips.xml,../sumo/locales.trips.xml,ambulancia_1celda.rou.xml"/>
  </input>
  <time><begin value="0"/><end value="200"/><step-length value="0.1"/></time>
  <processing>
    <ignore-route-errors value="true"/><time-to-teleport value="120"/>
    <lateral-resolution value="0.8"/><device.bluelight.reactiondist value="60"/>
  </processing>
  <report><no-step-log value="true"/></report>
</configuration>
""")

    # --- Correr SUMO con TraCI (accidente + FCD de todos) ---
    binario = SUMO + ("-gui" if args.gui else "")
    orden = [binario, "-c", "cuenca_1celda.sumocfg", "--seed", str(args.seed),
             "--fcd-output", "fcd_todos.xml",
             "--fcd-output.attributes", "x,y,angle,speed",
             "--device.fcd.period", "0.5"]
    traci.start(orden)

    accidente = None
    if args.accidente:
        a, t = args.accidente.rsplit("@", 1)
        accidente = (a, float(t))
    acc_edge_final = None
    t_salida = t_llegada = None

    import random
    while True:
        traci.simulationStep()
        ahora = traci.simulation.getTime()
        vehs = traci.vehicle.getIDList()

        if accidente and ahora >= accidente[1]:
            a = accidente[0]
            if a == "auto" and AMB in vehs:
                ruta_amb = traci.vehicle.getRoute(AMB)
                idx = traci.vehicle.getRouteIndex(AMB)
                cand = list(ruta_amb[idx + 2: idx + 6]) or list(ruta_amb[idx + 1:-1])
                a = random.Random(args.seed).choice(cand) if cand else None
            if a and a != "auto":
                traci.edge.setMaxSpeed(a, 0.3)
                acc_edge_final = a
                print(f"t={ahora:.1f}s  ACCIDENTE en calle {a}")
                # re-ruteo de la ambulancia para esquivarlo
                if AMB in vehs:
                    traci.vehicle.rerouteTraveltime(AMB, True)
                accidente = None
            elif a is None:
                accidente = None

        if AMB in vehs and t_salida is None:
            t_salida = ahora
        if AMB not in vehs and t_salida is not None and t_llegada is None:
            t_llegada = ahora
            break
        if ahora > 199:
            break

    traci.close()
    print(f"Viaje ambulancia: t={t_salida} -> {t_llegada} s")

    json.dump({
        "gnb_idx": gi, "gnb_pos": [gcx, gcy],
        "hospital": list(HOSPITAL),
        "t_salida": t_salida, "t_llegada": t_llegada,
        "accidente_edge": acc_edge_final,
        "origen_edge": eorig.getID(),
    }, open("escenario_1celda.json", "w"), indent=1)
    print("Escrito fcd_todos.xml, ambulancia_1celda.rou.xml, escenario_1celda.json")


if __name__ == "__main__":
    main()
