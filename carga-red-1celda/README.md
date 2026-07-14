# Carga de red — versión de UNA sola celda (la del hospital)

Misma idea que `../carga-red/` pero acotada a **un solo gNB** (el de la celda
del hospital, gNB 3) y con simulación **corta**. Dos scripts:

## 1) `generar_rutas.py` — genera las rutas y corre SUMO

Crea la ruta de la ambulancia (extremo opuesto de la celda → hospital, ~1 km
todo dentro de la cobertura), usa el tráfico de la ciudad como fondo, y exporta
el FCD de todos los vehículos. Soporta accidente y semilla:

```bash
~/sumo-venv/bin/python generar_rutas.py                     # sin accidente
~/sumo-venv/bin/python generar_rutas.py --seed 7            # otra semilla
~/sumo-venv/bin/python generar_rutas.py --accidente auto@30 # accidente aleatorio (por seed)
~/sumo-venv/bin/python generar_rutas.py --accidente 400264794@30  # calle concreta
```
Salidas: `fcd_todos.xml`, `ambulancia_1celda.rou.xml`, `escenario_1celda.json`.

## 2) `correr_fases.py` — ejecuta las 3 fases

- **Fase 1**: filtra los autos cuya celda servidora (gNB más cercana de las 35)
  es la del hospital, en los mismos instantes que la ambulancia. Mapas
  `mapa1_ruta_gnb.png` y `mapa2_competidores.png`.
- **Fase 2**: ventana corta (15 s) + muestreo de UEs de fondo con tasa eMBB.
- **Fase 3**: 3 corridas ns-3 (sin carga / carga / carga+slicing por 2 bandas)
  reutilizando el binario `fase3-carga`. Gráfica `fase3_urllc_vs_embb.png`.

```bash
~/sumo-venv/bin/python correr_fases.py
```

## Resultado de ejemplo (accidente en seed=3, ventana 15 s, 4 UEs, ~34 Mbps)

Aquí la carga NO satura la celda (régimen suave), así que el efecto se ve como
degradación de latencia/jitter (no pérdida):

| Escenario | Vitales: latencia | Vitales: jitter |
|---|---|---|
| Sin carga | 7.1 ms | 0.00 ms |
| Con carga (sin slicing) | 8.4 ms | 0.86 ms |
| Con carga + slicing | **7.1 ms** | **0.00 ms** |

El slicing **restaura los signos vitales a su línea base** (sobre todo el
jitter, clave para telemetría), aislándolos del tráfico eMBB de los autos.
Complementa el escenario de `../carga-red/`, donde con carga mayor se ve el
caso extremo (100% de pérdida sin slicing vs 0% con slicing).

## Gráficas del scheduler (cómo reparte los recursos)

Requiere `nrHelper->EnableTraces()` (ya activado en `fase3-carga.cc`). Se corren
las 3 configs guardando `RxPacketTrace_{a,b,c}.txt` y el mapeo RNTI->UE (líneas
`MAPEO,...` en `sched_{a,b,c}.log`), y luego:

```bash
~/sumo-venv/bin/python graficar_scheduler.py
```

Genera:
- **`sched_throughput.png`** — throughput entregado por flujo en el tiempo
  (áreas apiladas). Muestra el OFDMA Round-Robin repartiendo la celda entre la
  ambulancia y los autos; con slicing, los vitales (URLLC) aparecen como una
  franja aislada al fondo, separada del video (eMBB).
- **`sched_reparto.png`** — datos totales entregados por flujo. Sin slicing el
  RR reparte de forma casi pareja entre todos; con slicing los vitales tienen su
  porción reservada.
- **`sched_mcs.png`** — MCS (adaptación de enlace) por UE. La ambulancia (cerca
  del centro) usa MCS alto; los autos en el borde usan MCS bajo/variable y por
  eso consumen más recursos para los mismos datos.

Nota: `tbSize` de la traza está en bytes (se multiplica por 8 para Mbps).
