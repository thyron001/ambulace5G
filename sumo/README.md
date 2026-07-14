# Pipeline SUMO → ns-3 (Paso 1: movilidad realista)

Escenario: una ambulancia recorre 2.4 km desde el centro histórico de Cuenca
(Parque Calderón) hasta el Hospital Regional Vicente Corral Moscoso, sobre el
mapa real de OpenStreetMap, con ~450 vehículos de tráfico de fondo y 200
semáforos. La traza de movilidad resultante alimenta la simulación 5G en ns-3.

Herramientas: SUMO 1.27.1 (instalado en `~/sumo-venv`), ns-3.40 + 5G-LENA
NR-v2.6 (en `~/ns3-5glena/ns-3-dev`).

## Archivos

| Archivo | Qué es |
|---|---|
| `cuenca.osm.xml` | Recorte de OpenStreetMap (bbox -79.015,-2.922,-78.982,-2.890) |
| `cuenca.net.xml` | Red vial SUMO (200 semáforos importados de OSM) |
| `cuenca.poly.xml` | Edificios (para sumo-gui y, a futuro, propagación en ns-3) |
| `background.trips.xml` | 446 viajes aleatorios de tráfico de fondo |
| `ambulancia.rou.xml` | vType emergencia + ruta fija de 38 aristas al hospital |
| `cuenca.sumocfg` | Configuración de la simulación de tráfico |
| `fcd_amb.xml` | Posición de la ambulancia cada 0.1 s (salida FCD) |
| `mobility_amb.tcl` | Traza en formato ns-2 (tiempos desplazados a t=0, z=1.5 m) |
| `preparar_ruta.py` | Calcula la ruta y genera `ambulancia.rou.xml` |
| `mapa_ruta.py` | Dibuja `mapa_ruta.png` (red + ruta + gNB) |
| `semaforos_ruta.txt` | IDs de los 8 semáforos que cruza la ambulancia (para el paso 3) |

## Reproducir desde cero

```bash
VENV=~/sumo-venv/bin
SUMO_TOOLS=~/sumo-venv/lib/python3.12/site-packages/sumo/tools

# 1. Descargar mapa (Overpass API; la consulta evita los operadores < > que
#    el WAF del servidor rechaza)
curl -s "https://overpass-api.de/api/interpreter" --data-urlencode \
  'data=[out:xml][timeout:240];(way(-2.9220,-79.0150,-2.8900,-78.9820);node(w);node(-2.9220,-79.0150,-2.8900,-78.9820););out meta;' \
  -o cuenca.osm.xml

# 2. Red vial con semáforos + edificios
$VENV/netconvert --osm-files cuenca.osm.xml -o cuenca.net.xml \
  --geometry.remove --ramps.guess --junctions.join \
  --tls.guess-signals --tls.discard-simple --tls.join \
  --tls.default-type actuated --keep-edges.by-vclass passenger \
  --remove-edges.isolated --output.street-names
$VENV/polyconvert --net-file cuenca.net.xml --osm-files cuenca.osm.xml \
  --typemap $SUMO_TOOLS/../data/typemap/osmPolyconvert.typ.xml -o cuenca.poly.xml

# 3. Ruta de la ambulancia y tráfico de fondo
$VENV/python preparar_ruta.py
$VENV/python $SUMO_TOOLS/randomTrips.py -n cuenca.net.xml -o background.trips.xml \
  -b 0 -e 400 --period 0.9 --fringe-factor 5 --vehicle-class passenger \
  --prefix bg --validate --trip-attributes 'departLane="best" departSpeed="max"'

# 4. Simular tráfico y exportar la traza de la ambulancia
$VENV/sumo -c cuenca.sumocfg --fcd-output fcd_amb.xml \
  --device.fcd.explicit amb --fcd-output.attributes x,y,angle,speed
$VENV/python $SUMO_TOOLS/traceExporter.py --fcd-input fcd_amb.xml \
  --ns2mobility-output mobility_amb_raw.tcl --begin 100 --end 324
awk '{ if ($2=="at") { $3 = sprintf("%.1f", $3-100.0) } ; print }' \
  mobility_amb_raw.tcl > mobility_amb.tcl
sed -i 's/set Z_ 0/set Z_ 1.5/' mobility_amb.tcl   # altura UE para el canal UMa

# 5. Correr ns-3 (lee la traza con Ns2MobilityHelper)
cp ../ambulancia-5G.cc ~/ns3-5glena/ns-3-dev/scratch/
cd ~/ns3-5glena/ns-3-dev && ./ns3 run ambulancia-5G
```

## Ver la simulación de tráfico con interfaz gráfica

```bash
~/sumo-venv/bin/sumo-gui -c cuenca.sumocfg --delay 100
```
La ambulancia (`amb`, roja, sale en t=100 s) usa `vClass="emergency"` con
dispositivo *bluelight*: los demás vehículos le ceden el paso.

## Paso 3: preempción de semáforos vía 5G (TraCI)

`preempcion.py` cierra el lazo tráfico↔red: la ambulancia publica su posición
cada `--gps` s (el flujo GPS de ns-3), un servidor de control detecta los
semáforos a menos de `--dist` m en su ruta (`getNextTLS`) y les ordena verde;
la orden se aplica `--latencia` s después (la latencia extremo a extremo
medida en ns-3). El verde se da a todos los movimientos del acceso por el que
llega la ambulancia (descarga la cola completa) y el semáforo se restaura a
su programa normal al pasar.

Escenario de evaluación: hora pico (`cuenca-rush.sumocfg` = 1430 viajes de
fondo + flujos de congestión en el corredor, `corridor.flows.xml`).

```bash
V=~/sumo-venv/bin/python
$V preempcion.py --sin-preempcion                            # línea base
$V preempcion.py --latencia 0.02 --dist 300 --etiqueta 5G_20ms
$V preempcion.py --latencia 2.0  --dist 300 --etiqueta degradada_2s
$V preempcion.py --latencia 10.0 --dist 300 --etiqueta degradada_10s
$V graficar_preempcion.py    # gráfica comparativa
# ver en vivo: añadir --gui a cualquier escenario
```

Resultados (viaje de 2.4 km en hora pico; media ± desv. de 8 semillas,
descartando corridas donde SUMO teletransportó a la ambulancia):

| Escenario | Viaje (s) | Detenida (s) | Paradas |
|---|---|---|---|
| Sin preempción | 337.5 ± 20.0 | 22.9 ± 10.4 | 4.4 ± 2.1 |
| Preempción 5G (20 ms) | 336.2 ± 24.8 | 30.8 ± 20.4 | **2.4 ± 1.6** |
| Red degradada (10 s) | 333.9 ± 19.2 | 24.2 ± 16.6 | 2.9 ± 2.0 |
| Red degradada (30 s) | **355.1 ± 31.0** | 38.2 ± 14.9 | 4.5 ± 1.0 |

Lectura honesta (dos regímenes):

- **Sin corredor de emergencia** (sin modelo de sub-carriles, o calles donde
  los conductores no pueden/quieren apartarse), la preempción es decisiva: en
  una corrida representativa el viaje bajó de 434.6 s a 358.9 s (−17%) y el
  tiempo detenida de 102 s a 8 s (−93%).
- **Con corredor de emergencia ideal** (sub-carriles activados: los autos se
  apartan con la sirena), la ambulancia ya se cuela entre las colas y el
  tiempo total de viaje deja de mejorar con la preempción (diferencias dentro
  del ruido estadístico). El beneficio que SÍ persiste es la **reducción de
  detenciones a la mitad** (4.4 → 2.4), relevante para la estabilidad del
  paciente. Y una red muy degradada (30 s) vuelve la preempción
  contraproducente: las órdenes llegan a destiempo y el viaje empeora.

La realidad está entre ambos regímenes (el corredor de SUMO es optimista en
calles angostas). Conclusión de ingeniería: la preempción tolera latencias
de segundos — el requisito URLLC estricto viene de los signos vitales y el
video, no de los semáforos.

## Paso 3b: re-ruteo dinámico y subida a la vereda

`preempcion.py` incorpora dos asistencias más:

- **Re-ruteo dinámico** (`--reroute 10`, 0=off): cada 10 s el servidor de
  control — que conoce el tráfico de toda la ciudad, como una plataforma
  smart-city — recalcula la ruta de menor tiempo (`rerouteTraveltime` con
  tráfico actual) y envía la nueva ruta a la ambulancia por la red 5G (se
  aplica con `--latencia`). La preempción de semáforos sigue automáticamente
  a la ruta nueva.
- **Subida a la vereda** (`--sin-vereda` para desactivar): los autos a menos
  de 60 m por delante de la ambulancia "suben dos ruedas a la vereda"
  (costumbre cuencana), modelado como reducción de su huella lateral al 50%
  en el modelo de sub-carriles; bajan cuando la ambulancia pasa. Es reacción
  local a la sirena: no pasa por la red.

Estudio de ablación (4 configuraciones × 5 semillas, hora pico;
`graficar_sistema.py` → `sistema_comparacion.png`):

| Configuración | Viaje (s) | Detenida (s) | Paradas |
|---|---|---|---|
| Sin asistencia | 346.1 ± 17.8 | 20.8 ± 10.3 | 5.2 ± 2.6 |
| Solo preempción | 344.4 ± 29.7 | 24.4 ± 26.4 | 2.2 ± 2.1 |
| Solo re-ruteo | 202.5 ± 9.2 | 3.8 ± 4.6 | 1.2 ± 0.8 |
| **Sistema completo** | **188.5 ± 6.1 (−46%)** | **2.4 ± 3.3** | **0.8 ± 0.8** |

El re-ruteo es el componente dominante (−42% de viaje por sí solo: evita el
corredor congestionado por completo) y además **estabiliza** el resultado
(desviación ±9 s frente a ±18-30 s). El sistema completo añade la vereda y
la preempción sobre la ruta nueva y deja el viaje casi al nivel de ciudad
vacía (188.5 s vs ~180 s de flujo libre), con menos de una detención en
promedio.

### Verificación del re-ruteo en caliente (accidente)

`--accidente ARISTA@T` bloquea una calle en el instante T (velocidad 0.3 m/s)
para probar que la ruta responde a condiciones en tiempo real:

```bash
V=~/sumo-venv/bin/python
$V preempcion.py --latencia 0.02 --dist 300 --etiqueta accidente \
   --fcd fcd_accidente.xml --accidente "60204533@135"      # con re-ruteo: 211 s
$V preempcion.py --latencia 0.02 --dist 300 --reroute 900 \
   --etiqueta sin_reroute --accidente "60204533@135"        # sin re-ruteo: 333 s
$V rutas_dinamicas.py   # mapa con las tres rutas superpuestas
```

El servidor detecta el bloqueo en el siguiente ciclo (≤10 s + latencia) y
desvía a la ambulancia rodeando el accidente: 211 s frente a 333 s si no hay
re-ruteo (se queda 128 s atrapada). La ruta efectivamente tomada en cada
corrida queda en `ruta_<etiqueta>.txt`.

Nota sobre la aleatoriedad: los viajes del tráfico de fondo están fijos en
archivo (`rush.trips.xml`, generado una vez por `randomTrips.py`); `--seed`
de SUMO varía el comportamiento de conducción (velocidades individuales,
inserción). Para patrones de tráfico distintos, regenerar los trips con otra
semilla de `randomTrips.py` (`--seed N`).

## Tráfico denso en toda la ciudad

Dos capas de tráfico (en los `.sumocfg` de hora pico):

- `rush.trips.xml`: 3 601 viajes con **punto intermedio aleatorio**
  (`--intermediate 1 --fringe-factor 1`), que fuerza a los autos a cruzar
  por calles secundarias en vez de solo las arteriales. Salidas hasta t=900.
- `locales.trips.xml`: 1 127 viajes cortos (100-700 m) por los barrios.

Resultado: ~1 300 vehículos circulando a la vez y 63% de los tramos con
tráfico en los primeros 260 s (el resto son fragmentos <20 m y callejones).
`medir_cobertura.py` recalcula estas cifras.

### El accidente y su semilla

- `--accidente "ARISTA@T"`: bloquea esa calle exacta en el instante T
  (el ID de una calle se ve en sumo-gui con clic derecho sobre ella, o en
  los archivos `ruta_<etiqueta>.txt` de corridas previas).
- `--accidente "auto@T"`: elige al azar una calle de la ruta que la
  ambulancia lleva en ese momento, 4-9 cuadras por delante. El sorteo usa
  `--seed`, así que la misma semilla reproduce el mismo accidente y semillas
  distintas generan accidentes distintos:

```bash
./ver_preempcion.sh --accidente "auto@140" --seed 3   # bloquea 389741419
./ver_preempcion.sh --accidente "auto@140" --seed 8   # otra calle distinta
```

## Datos del viaje (resultado de SUMO)

- Salida: t=100 s, llegada: t=323.4 s → **223.4 s de viaje** (2.4 km).
- Cruza **8 semáforos** (IDs en `semaforos_ruta.txt`) — insumo del paso 3
  (preempción de semáforos vía 5G).
- La traza empieza en (1990, 3402) y termina en (3631, 2042) (coordenadas
  locales SUMO, metros). Centro de la ruta: (2687, 2515) → posición de la gNB.
