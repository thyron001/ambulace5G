"""
Encuentra las aristas de origen (centro de Cuenca) y destino (Hospital
Vicente Corral Moscoso) en la red SUMO y calcula la ruta de la ambulancia.
Genera ambulancia.rou.xml con el vType de emergencia y la ruta fija.
"""
import sumolib

NET_FILE = "cuenca.net.xml"

# Coordenadas geográficas (lon, lat)
ORIGEN = (-79.0045, -2.8974)    # Centro histórico (Parque Calderón)
DESTINO = (-78.9927, -2.9112)   # Hospital Vicente Corral Moscoso

net = sumolib.net.readNet(NET_FILE)


def arista_cercana(lonlat, radio=200):
    """Devuelve la arista para autos más cercana a unas coordenadas."""
    x, y = net.convertLonLat2XY(*lonlat)
    candidatas = net.getNeighboringEdges(x, y, radio)
    candidatas = [(e, d) for e, d in candidatas if e.allows("passenger")]
    if not candidatas:
        raise RuntimeError(f"No hay aristas cerca de {lonlat}")
    candidatas.sort(key=lambda ed: ed[1])
    return candidatas[0][0], (x, y)


edge_origen, xy_origen = arista_cercana(ORIGEN)
edge_destino, xy_destino = arista_cercana(DESTINO)

print(f"Origen : {edge_origen.getID()}  ({edge_origen.getName()!r})  xy={xy_origen}")
print(f"Destino: {edge_destino.getID()}  ({edge_destino.getName()!r})  xy={xy_destino}")

ruta, coste = net.getShortestPath(edge_origen, edge_destino, vClass="passenger")
if ruta is None:
    raise RuntimeError("No se encontró ruta entre origen y destino")

largo = sum(e.getLength() for e in ruta)
ids = " ".join(e.getID() for e in ruta)
print(f"Ruta con {len(ruta)} aristas, {largo:.0f} m")

# Semáforos que la ambulancia cruzará (para la fase de preempción)
semaforos = []
for e in ruta:
    tls = e.getToNode().getType()
    if "traffic_light" in tls:
        semaforos.append(e.getToNode().getID())
print(f"Semáforos en la ruta: {len(semaforos)}")

with open("ambulancia.rou.xml", "w") as f:
    f.write(f"""<routes>
    <!-- Ambulancia: vClass emergency => puede usar carriles bus, exceso de
         velocidad permitido (speedFactor 1.5) y luces azules (bluelight) -->
    <vType id="ambulancia" vClass="emergency" color="1,0,0" guiShape="emergency"
           speedFactor="1.5" accel="3.5" decel="6.0" maxSpeed="33"
           width="2.1" minGapLat="0.25" lcSublane="2.0" lcPushy="1.0" lcAssertive="2.0"/>

    <route id="ruta_hospital" edges="{ids}"/>
    <vehicle id="amb" type="ambulancia" route="ruta_hospital" depart="100"
             departSpeed="max">
        <param key="has.bluelight.device" value="true"/>
    </vehicle>
</routes>
""")
print("Escrito ambulancia.rou.xml")

with open("semaforos_ruta.txt", "w") as f:
    f.write("\n".join(semaforos))
