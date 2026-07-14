# Parches para habilitar el handover X2 en 5G-LENA (NR-v2.6 / ns-3.40)

El módulo 5G-LENA **no soporta handover oficialmente**. El RRC que usa (heredado
del módulo LTE de ns-3) sí trae toda la maquinaria X2, pero la cadena se rompe
en varios puntos al combinarla con la PHY/MAC de NR. Este trabajo identificó y
corrigió cada eslabón roto hasta lograr traspasos X2 completos entre gNBs NR.

El disparo del handover lo hace un **gestor de proximidad** implementado en el
escenario (`ambulancia-5G.cc`): cada 500 ms compara la distancia del UE a cada
gNB y, con una histéresis de 50 m, ordena el traspaso vía
`LteEnbRrc::SendHandoverRequest()`. Al completarse (traza `HandoverEndOk`),
los haces se re-apuntan a la celda nueva mediante una subclase de
`IdealBeamformingHelper` que sustituye la tarea de beamforming.

## Cadena de fallos encontrada y corregida (en orden de aparición)

| # | Archivo | Problema | Corrección |
|---|---------|----------|------------|
| 1 | `src/lte/model/lte-enb-rrc.cc` | `PrepareHandover` y `GetRrcConnectionReconfigurationForHandover` hacen `DynamicCast<ComponentCarrierEnb>`, pero el NrHelper registra `ComponentCarrierBaseStation` → puntero nulo → segfault. Solo usan métodos de la clase base. | Relajar ambos casts a `ComponentCarrierBaseStation`. |
| 2 | `contrib/nr/model/nr-gnb-mac.cc` | `DoAllocateNcRaPreamble` era un stub que devolvía `valid=false` → la celda destino rechazaba toda preparación de handover (HO Preparation Failure silencioso). | Reservar un preámbulo dedicado real (rango 192-255) asociado al RNTI pre-asignado (`m_ncRaPreambleMap`). |
| 3 | `contrib/nr/model/nr-mac-scheduler-ns3.cc` | `DoSchedUlCqiInfoReq` desreferenciaba `end()` al procesar CQIs de un UE ya eliminado (asserts desactivados en build optimizado). | Descartar CQI/asignaciones de RNTIs o slots desconocidos. |
| 4 | `contrib/nr/model/nr-rrc-protocol-ideal.cc` | `DoSendIdealUeContextRemoveRequest` era `NS_FATAL_ERROR` → abortaba cuando el UE pedía a la celda vieja borrar su contexto. | Portada la implementación equivalente de `LteUeRrcProtocolIdeal`. |
| 5 | `contrib/nr/model/nr-ue-phy.cc` | `DoResetPhyAfterRlf`, `DoResetRlfParams`, `DoStartInSyncDetection` eran `NS_FATAL_ERROR`; el RRC los invoca durante el handover. | Convertidos en no-ops (la PHY NR no modela RLF; no hay estado que resetear). |
| 6 | `src/lte/model/simple-ue-component-carrier-manager.cc` | Oportunidades de TX y PDUs para LCIDs ya liberados durante el traspaso abortaban la simulación. | Descartar en lugar de abortar. |
| 7 | `contrib/nr/model/nr-gnb-mac.cc` | PDUs en vuelo de un RNTI ya eliminado en la celda origen → segfault en `DoReceivePhyPdu`. | Descartar PDUs de RNTI/LCID desconocidos. |
| 8 | `contrib/nr/model/nr-ue-mac.cc` | `DoStartNonContentionBasedRandomAccessProcedure` solo guardaba el RNTI: nunca transmitía el preámbulo y el UE esperaba el RAR para siempre. | Transmitir el preámbulo dedicado recibido en la orden de handover y rearmar `m_waitingForRaResponse`. |
| 8b | `contrib/nr/model/nr-gnb-mac.cc` | El bucle de preámbulos siempre asignaba un RNTI temporal nuevo (rompía el contexto `HANDOVER_JOINING` pre-asignado). | Si el preámbulo está en `m_ncRaPreambleMap`, usar el RNTI reservado. |
| 9 | `contrib/nr/model/nr-ue-mac.cc` | `DoReset` era un stub vacío: el UE arrastraba a la celda nueva la máquina SR/BSR (`m_srState==ACTIVE` huérfano → nunca vuelve a pedir recursos → el plano de datos UL muere tras el 2º handover), BSRs, DCIs y buffers HARQ de la celda anterior. | Implementado el reset (SR/BSR/DCI/HARQ + limpieza de LCIDs de datos, conservando señalización, como `LteUeMac::DoReset`). |
| 10 | `contrib/nr/model/nr-ue-mac.cc` | Mina preexistente: si una concesión UL queda sin usar, `SendNewData` anula el burst HARQ (`m_pktBurst=nullptr`); una transmisión posterior en el mismo proceso HARQ hacía `AddPacket` sobre nulo → segfault (se dispara con buffers vacíos justo tras un handover). | `DoTransmitPdu` recrea el burst si lo encuentra nulo. |
| 11 | `contrib/nr/model/nr-spectrum-phy.cc` | `StartTxDataFrames/DlControl/UlControl` abortaban con `NS_FATAL_ERROR("Cannot TX while RX.")` cuando una concesión de subida caía en el instante de un handover con la celda **cargada** (sólo se dispara con tráfico de fondo compitiendo, por eso no aparecía en los escenarios de un solo UE). | Descartar la trama (return) en vez de abortar: modela la interrupción de datos propia del traspaso. |

Los parches #1-#11 se necesitan para el handover multi-celda. El estudio de
carga (`carga-red/`, Fase 3) usa una sola celda **sin** handover, así que sólo
depende de los parches ya presentes en el módulo (no introduce nuevos). El
slicing se hace por 2 bandas dedicadas (no por scheduler QoS, que resultó poco
fiable en este stack), evitando por completo la maquinaria de handover.

## Resultado

Traspaso X2 completo (preparación → orden RRC → acceso aleatorio sin
contención en la celda destino → conmutación de ruta S1 → borrado de contexto
en la origen) en **~2.5 ms** de tiempo simulado, con continuidad de los tres
flujos de la ambulancia.

## Notas

- Los parches están pensados para este escenario (RRC ideal, un UE). No
  implementan RLF ni medición RSRP/RSRQ en el UE NR: el disparo del handover
  es responsabilidad del escenario (gestor de proximidad), no de la red.
- Con `--numGnb=1` el escenario reproduce el caso de celda única (línea base
  para comparar).
