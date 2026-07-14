"""
Preempción de semáforos para la ambulancia vía 5G (paso 3).

Modela el lazo completo:
  1. La ambulancia publica su posición por la red 5G cada --gps segundos
     (el flujo GPS de la simulación ns-3).
  2. Un servidor de control (MEC/hospital) detecta los semáforos que la
     ambulancia tiene por delante (getNextTLS) a menos de --dist metros.
  3. Envía la orden de preempción al semáforo A TRAVÉS DE LA RED: la orden
     se aplica --latencia segundos después (latencia medida en ns-3).
  4. El semáforo pone verde el movimiento de la ambulancia (rojo al resto)
     y se restaura a su programa normal cuando la ambulancia lo cruza.

Uso:
  python preempcion.py                     # preempción con 5G real (20 ms)
  python preempcion.py --latencia 1.0     # red degradada
  python preempcion.py --sin-preempcion   # línea base
  python preempcion.py --gui              # ver en sumo-gui
"""
import argparse
import csv
import os
import random
import sys

import traci

AMB = "amb"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latencia", type=float, default=0.02,
                    help="latencia de red GPS->servidor->semáforo (s)")
    ap.add_argument("--gps", type=float, default=1.0,
                    help="período de reporte de posición (s)")
    ap.add_argument("--dist", type=float, default=150.0,
                    help="distancia de preempción al semáforo (m)")
    ap.add_argument("--sin-preempcion", action="store_true",
                    help="no tocar los semáforos")
    ap.add_argument("--reroute", type=float, default=10.0,
                    help="período de re-ruteo dinámico por tráfico (s); 0=off")
    ap.add_argument("--sin-vereda", action="store_true",
                    help="los autos NO se suben a la vereda al oír la sirena")
    ap.add_argument("--gui", action="store_true", help="usar sumo-gui")
    ap.add_argument("--etiqueta", default=None,
                    help="nombre del escenario en el CSV de resultados")
    ap.add_argument("--sumocfg", default="cuenca-rush.sumocfg",
                    help="configuración SUMO (por defecto: hora pico)")
    ap.add_argument("--seed", type=int, default=42,
                    help="semilla aleatoria de SUMO (para promediar corridas)")
    ap.add_argument("--accidente", default=None, metavar="ARISTA@T",
                    help="bloquear una calle en el instante T (p.ej. 'id@140') "
                         "para probar el re-ruteo en caliente. Con 'auto@T' se "
                         "elige al azar (según --seed) una calle de la ruta "
                         "actual de la ambulancia, unas cuadras por delante")
    ap.add_argument("--fcd", default=None,
                    help="exportar traza FCD de la ambulancia a este archivo")
    ap.add_argument("--fcd-all", default=None,
                    help="exportar FCD de TODOS los autos a este archivo")
    ap.add_argument("--fcd-period", type=float, default=1.0,
                    help="período de muestreo del FCD-all (s)")
    args = ap.parse_args()

    binario = "sumo-gui" if args.gui else "sumo"
    binario = os.path.expanduser(f"~/sumo-venv/bin/{binario}")
    orden = [binario, "-c", args.sumocfg, "--no-step-log", "true",
             "--duration-log.disable", "true", "--seed", str(args.seed)]
    if args.gui:
        # arrancar sin esperar el botón de play y a velocidad observable
        orden += ["--start", "true", "--delay", "100",
                  "--gui-settings-file", "gui-settings.xml"]
    if args.fcd:
        orden += ["--fcd-output", args.fcd, "--device.fcd.explicit", AMB,
                  "--fcd-output.attributes", "x,y,angle,speed"]
    if args.fcd_all:
        orden += ["--fcd-output", args.fcd_all,
                  "--fcd-output.attributes", "x,y,angle,speed",
                  "--device.fcd.period", str(args.fcd_period)]
    traci.start(orden)

    paso = traci.simulation.getDeltaT()

    # --- Estado del controlador ---
    pendientes = []        # [(t_aplicar, funcion), ...] órdenes en tránsito por la red
    preemptados = {}       # tlsId -> programa original
    ya_solicitados = set() # tls con orden de verde en vuelo o aplicada
    proximo_reporte = 0.0
    proximo_reroute = 0.0
    eventos_preempcion = []
    reroutes = 0           # cambios de ruta efectivos
    encogidos = {}         # veh -> (ancho, minGapLat) originales (en la vereda)
    vereda_total = set()   # vehículos que alguna vez cedieron la vereda

    # --- Métricas de la ambulancia ---
    t_salida = None
    t_llegada = None
    tiempo_detenida = 0.0
    paradas = 0
    detenida_antes = False
    amb_teleports = 0  # si >0, el tiempo de viaje NO es válido
    ruta_final = []    # última ruta conocida de la ambulancia

    def poner_verde(tls, ruta_restante):
        """Verde a TODOS los movimientos que salen de los accesos por los que
        circula la ambulancia (descarga la cola completa, que incluye autos
        que giran hacia otras calles); rojo al tráfico transversal."""
        if tls not in preemptados:
            preemptados[tls] = traci.trafficlight.getProgram(tls)
        enlaces = traci.trafficlight.getControlledLinks(tls)
        verdes = set()
        for i, conexiones in enumerate(enlaces):
            for con in conexiones:
                arista_entrada = con[0].rsplit("_", 1)[0]
                if arista_entrada in ruta_restante:
                    verdes.add(i)
        nuevo = "".join("G" if i in verdes else "r" for i in range(len(enlaces)))
        traci.trafficlight.setRedYellowGreenState(tls, nuevo)
        eventos_preempcion.append((traci.simulation.getTime(), tls, "VERDE"))

    def restaurar(tls):
        if tls in preemptados:
            traci.trafficlight.setProgram(tls, preemptados.pop(tls))
            ya_solicitados.discard(tls)
            eventos_preempcion.append((traci.simulation.getTime(), tls, "RESTAURADO"))

    def reroutear():
        """El servidor de control, con visión del tráfico de toda la ciudad,
        recalcula la ruta de menor tiempo y se la envía a la ambulancia
        (la orden ya viajó por la red: esta función se aplica con latencia)."""
        nonlocal reroutes
        if AMB not in traci.vehicle.getIDList():
            return
        idx = traci.vehicle.getRouteIndex(AMB)
        antes = traci.vehicle.getRoute(AMB)[idx:]
        traci.vehicle.rerouteTraveltime(AMB, True)  # True: tráfico actual
        despues = traci.vehicle.getRoute(AMB)[traci.vehicle.getRouteIndex(AMB):]
        if list(antes) != list(despues):
            reroutes += 1
            print(f"t={traci.simulation.getTime():.1f}s  RE-RUTEO: el servidor "
                  f"desvía a la ambulancia ({len(antes)} -> {len(despues)} tramos)")

    VENTANA_VEREDA = 60.0   # metros por delante en los que rige la sirena
    FACTOR_VEREDA = 0.5     # huella lateral con dos ruedas en la vereda

    def gestionar_vereda():
        """Los autos justo delante de la ambulancia se suben un poco a la
        vereda (típico en Cuenca): se modela reduciendo su huella lateral,
        lo que abre espacio extra en el modelo de sub-carriles. Es reacción
        local de los conductores a la sirena: no pasa por la red."""
        objetivos = {}
        arista = traci.vehicle.getRoadID(AMB)
        if not arista.startswith(":"):  # en cruce interno no se gestiona
            pos_amb = traci.vehicle.getLanePosition(AMB)
            for veh in traci.edge.getLastStepVehicleIDs(arista):
                if veh == AMB:
                    continue
                d = traci.vehicle.getLanePosition(veh) - pos_amb
                if -5.0 <= d <= VENTANA_VEREDA:
                    objetivos[veh] = d
            # también la siguiente calle de la ruta si está cerca
            resto = traci.lane.getLength(traci.vehicle.getLaneID(AMB)) - pos_amb
            ruta = traci.vehicle.getRoute(AMB)
            idx = traci.vehicle.getRouteIndex(AMB)
            if resto < VENTANA_VEREDA and 0 <= idx < len(ruta) - 1:
                for veh in traci.edge.getLastStepVehicleIDs(ruta[idx + 1]):
                    d = resto + traci.vehicle.getLanePosition(veh)
                    if d <= VENTANA_VEREDA:
                        objetivos[veh] = d

        for veh in objetivos:
            if veh not in encogidos:
                try:
                    encogidos[veh] = (traci.vehicle.getWidth(veh),
                                      traci.vehicle.getMinGapLat(veh))
                    traci.vehicle.setWidth(veh, encogidos[veh][0] * FACTOR_VEREDA)
                    traci.vehicle.setMinGapLat(veh, 0.1)
                    vereda_total.add(veh)
                except traci.TraCIException:
                    encogidos.pop(veh, None)
        # bajar de la vereda a quienes la ambulancia ya dejó atrás
        activos = set(traci.vehicle.getIDList())
        for veh in list(encogidos):
            if veh not in objetivos:
                ancho, gap = encogidos.pop(veh)
                if veh not in activos:  # ya llegó a su destino
                    continue
                try:
                    traci.vehicle.setWidth(veh, ancho)
                    traci.vehicle.setMinGapLat(veh, gap)
                except traci.TraCIException:
                    pass

    accidente = None
    if args.accidente:
        arista_acc, t_acc = args.accidente.rsplit("@", 1)
        accidente = (arista_acc, float(t_acc))

    while True:
        traci.simulationStep()
        ahora = traci.simulation.getTime()

        if accidente and ahora >= accidente[1]:
            arista_acc = accidente[0]
            if arista_acc == "auto":
                # elegir una calle de la ruta actual, 4-9 tramos por delante
                if AMB not in traci.vehicle.getIDList():
                    arista_acc = None  # aún no sale: reintentar el próximo paso
                else:
                    ruta_amb = traci.vehicle.getRoute(AMB)
                    idx_amb = traci.vehicle.getRouteIndex(AMB)
                    candidatas = list(ruta_amb[idx_amb + 4: idx_amb + 10]) or \
                                 list(ruta_amb[idx_amb + 1: -1])
                    arista_acc = (random.Random(args.seed).choice(candidatas)
                                  if candidatas else None)
                    if arista_acc is None:
                        accidente = None  # sin tramos por delante: descartar
            if arista_acc:
                traci.edge.setMaxSpeed(arista_acc, 0.3)  # calle bloqueada
                print(f"t={ahora:.1f}s  *** ACCIDENTE: calle {arista_acc} bloqueada ***")
                # --- Indicador visual en sumo-gui ---
                try:
                    forma = traci.lane.getShape(arista_acc + "_0")
                    # línea roja gruesa sobre la calle bloqueada
                    traci.polygon.add("accidente_via", forma, color=(220, 30, 30, 255),
                                      fill=False, layer=20, lineWidth=6)
                    cx = sum(p[0] for p in forma) / len(forma)
                    cy = sum(p[1] for p in forma) / len(forma)
                    # marcador circular grande + etiqueta en el centro
                    traci.poi.add("ACCIDENTE", cx, cy, color=(230, 0, 0, 255),
                                  poiType="accidente", layer=21, width=25)
                except traci.TraCIException:
                    pass
                accidente = None

        # Aplicar órdenes cuya latencia de red ya venció
        while pendientes and pendientes[0][0] <= ahora:
            _, accion = pendientes.pop(0)
            accion()
        pendientes.sort(key=lambda x: x[0])

        if AMB in traci.simulation.getStartingTeleportIDList():
            amb_teleports += 1

        vehiculos = traci.vehicle.getIDList()
        if AMB in vehiculos:
            if t_salida is None:
                t_salida = ahora
                # la ambulancia aprovecha al máximo el espacio lateral cedido
                traci.vehicle.setMinGapLat(AMB, 0.05)

            ruta_final = list(traci.vehicle.getRoute(AMB))

            if not args.sin_vereda:
                gestionar_vereda()

            # --- Re-ruteo dinámico: decisión del servidor, viaja por la red ---
            if args.reroute > 0 and ahora >= proximo_reroute:
                proximo_reroute = ahora + args.reroute
                pendientes.append((ahora + args.latencia, reroutear))
                pendientes.sort(key=lambda x: x[0])

            # métricas de detención (umbral 3 m/s: congestión o frenado)
            v = traci.vehicle.getSpeed(AMB)
            if v < 3.0:
                tiempo_detenida += paso
                if not detenida_antes:
                    paradas += 1
                detenida_antes = True
            else:
                detenida_antes = False

            # --- Lazo de control 5G (muestreo GPS + latencia de red) ---
            if not args.sin_preempcion and ahora >= proximo_reporte:
                proximo_reporte = ahora + args.gps
                siguientes = traci.vehicle.getNextTLS(AMB)
                delante = {t[0] for t in siguientes}
                ruta = traci.vehicle.getRoute(AMB)
                idx = traci.vehicle.getRouteIndex(AMB)
                ruta_restante = set(ruta[max(idx, 0):])

                for tlsId, indice, dist, _ in siguientes:
                    if dist <= args.dist and tlsId not in ya_solicitados:
                        ya_solicitados.add(tlsId)
                        pendientes.append((
                            ahora + args.latencia,
                            lambda t=tlsId, r=ruta_restante: poner_verde(t, r)))

                # restaurar los semáforos que ya quedaron atrás
                for tlsId in list(preemptados):
                    if tlsId not in delante:
                        pendientes.append((
                            ahora + args.latencia,
                            lambda t=tlsId: restaurar(t)))
                pendientes.sort(key=lambda x: x[0])

        elif t_salida is not None and t_llegada is None:
            t_llegada = ahora
            # guardar la ruta efectivamente tomada (para análisis/gráficas)
            if ruta_final:
                with open(f"ruta_{args.etiqueta or 'run'}.txt", "w") as rf:
                    rf.write(" ".join(ruta_final))
            for tls in list(preemptados):
                restaurar(tls)
            for veh in list(encogidos):  # todos bajan de la vereda
                ancho, gap = encogidos.pop(veh)
                try:
                    traci.vehicle.setWidth(veh, ancho)
                    traci.vehicle.setMinGapLat(veh, gap)
                except traci.TraCIException:
                    pass

        if t_llegada is not None or ahora >= 899:
            break

    traci.close()

    # --- Resultados ---
    viaje = (t_llegada - t_salida) if (t_salida and t_llegada) else float("nan")
    etiqueta = args.etiqueta or (
        "sin_preempcion" if args.sin_preempcion else f"lat_{args.latencia}s")
    print(f"\n===== ESCENARIO: {etiqueta} =====")
    if amb_teleports:
        print(f"*** CORRIDA INVALIDA: la ambulancia fue teletransportada "
              f"{amb_teleports} vez/veces (bloqueo > time-to-teleport) ***")
    print(f"Salida            : t={t_salida} s")
    print(f"Llegada al hospital: t={t_llegada} s")
    print(f"Tiempo de viaje   : {viaje:.1f} s")
    print(f"Tiempo detenida   : {tiempo_detenida:.1f} s")
    print(f"Paradas           : {paradas}")
    print(f"Preempciones      : {len([e for e in eventos_preempcion if e[2]=='VERDE'])}")
    print(f"Re-ruteos         : {reroutes}")
    print(f"Autos a la vereda : {len(vereda_total)}")
    for t, tls, acc in eventos_preempcion:
        print(f"   t={t:6.1f}s  {acc:<11} {tls}")

    nuevo = not os.path.exists("resultados_preempcion.csv")
    with open("resultados_preempcion.csv", "a", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["escenario", "seed", "latencia_s", "gps_s", "dist_m",
                        "viaje_s", "detenida_s", "paradas", "amb_teleports",
                        "reroutes", "vereda_veh"])
        w.writerow([etiqueta, args.seed, args.latencia, args.gps, args.dist,
                    round(viaje, 1), round(tiempo_detenida, 1), paradas,
                    amb_teleports, reroutes, len(vereda_total)])
    print("Añadido a resultados_preempcion.csv")


if __name__ == "__main__":
    sys.exit(main())
