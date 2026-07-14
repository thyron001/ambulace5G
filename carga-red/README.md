# Carga de red: URLLC vs eMBB con tráfico vehicular real (3 fases)

Estudio de cómo el tráfico de los autos de la ciudad (filtrado de SUMO)
compite por recursos 5G con la ambulancia, y de cómo el *network slicing*
protege el tráfico crítico (signos vitales, URLLC) frente al eMBB (video).

Depende de la carpeta `../sumo/` (red de Cuenca, gNBs de cobertura, controlador
de preempción) y del binario `fase3-carga` en el scratch de ns-3.

## Fase 1 — Filtrado por gNBs (SUMO + post-proceso)

1. Se corre SUMO con un **accidente** que fuerza el re-ruteo de la ambulancia
   (ruta variable), exportando el FCD de **todos** los autos:
   ```bash
   cd ../sumo && ~/sumo-venv/bin/python preempcion.py --latencia 0.02 \
     --dist 300 --reroute 10 --seed 3 --etiqueta fase1 --accidente "auto@140" \
     --fcd-all ../carga-red/fcd_todos.xml --fcd-period 1.0
   ```
2. `fase1_filtrar.py` cruza la ruta con `../sumo/gnbs_cobertura.csv`:
   - **celda servidora** de cada vehículo = gNB más cercana de las 35 (por eso
     hacía falta cubrir toda la ciudad).
   - **gNBs de la ambulancia** = las que la sirvieron durante su viaje.
   - **competidores** = autos con la misma celda servidora que la ambulancia
     en el mismo instante.
   - Resultado de esta corrida: la ambulancia usó **4 gNBs** (0, 21, 2, 3) y
     compitió con **369 autos**. Salida: `fase1_datos.json`.
3. `fase1_mapas.py` → `mapa1_ruta_gnbs.png` (ruta + accidente + gNBs) y
   `mapa2_competidores.png` (+ trayectorias de los autos filtrados).

## Fase 2 — Muestreo de UEs activos

`fase2_preparar.py`: ventana corta de 1 celda (la 21, sin handover), factor de
actividad 0.30, y a cada UE de fondo se le asigna una tasa eMBB aleatoria.
Salidas: `escenario_ns3.txt` (gNB + UEs + tasas) y `mobility_amb_ventana.tcl`
(traza ns-2 de la ambulancia). Configuración final: 1 gNB, 5 UEs de fondo,
~34 Mbps eMBB agregados, ventana de 48 s.

## Fase 3 — Experimento URLLC vs eMBB (ns-3)

`fase3-carga.cc` (en `../` y copiado al scratch). Downlink hospital→UEs:
- Ambulancia: signos vitales (URLLC, 100 B/20 ms) + video (eMBB, 4 Mbps).
- Autos: streams eMBB (su tasa muestreada).
- **Slicing = 2 bandas dedicadas** (patrón cttc-nr-demo): 10 MHz totales; con
  slicing se parten en **2 MHz para URLLC** (signos vitales, aislados) + 8 MHz
  para eMBB (video + autos). El enrutado de bearers por 5QI manda cada flujo a
  su banda. Sin slicing, 10 MHz compartidos.

```bash
cd ~/ns3-5glena/ns-3-dev
B=build/scratch/ns3.40-fase3-carga-optimized
for c in "0 0 a_sin_carga" "1 0 b_carga" "1 1 c_slicing"; do set -- $c
  LD_LIBRARY_PATH=$PWD/build/lib $B --carga=$1 --slicing=$2 --etiqueta=$3; done
# gráfica:
cd ../../Desktop/moviles/carga-red && ~/sumo-venv/bin/python graficar_fase3.py
```

Optimizaciones para que corra rápido: canal 3GPP cuasi-estático
(`UpdatePeriod=0`), beamforming una sola vez, ventana de 48 s, log de progreso
con ETA (`PROGRESO t=.../...s (%)`), y `--simcap` para pruebas cortas.

### Resultado (`fase3_urllc_vs_embb.png`)

| Escenario | Vitales (URLLC) | Video (eMBB) |
|---|---|---|
| Sin carga | 7.1 ms, 0% pérdida | 4.1 Mbps, 0% pérdida |
| Con carga, **sin** slicing | **100% pérdida** (perdidos) | 100% pérdida |
| Con carga, **con** slicing | **7.1 ms, 0% pérdida** | 100% pérdida |

Bajo saturación de la celda, **sin slicing se pierde el 100% del tráfico
crítico**; el *slicing* por banda dedicada **garantiza los signos vitales**
(0% pérdida, 7 ms) sacrificando el video no crítico. Es la justificación
cuantitativa del URLLC/eMBB con tráfico vehicular real.

Nota metodológica: la celda pasa de servir bien (~34 Mbps) a colapsar (~40 Mbps)
en un margen muy estrecho (RLC UM descarta todo el buffer al saturar), por eso
el escenario con carga aparece como colapso total y no como degradación
gradual. Es un régimen de saturación deliberado para estresar la red.
