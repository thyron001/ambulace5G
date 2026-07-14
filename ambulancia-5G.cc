/*
 * Demo: Ambulancia inteligente con 5G NR (5G-LENA) + movilidad SUMO
 *       + multi-celda con handover X2
 *
 * - UE móvil (ambulancia) se mueve según una traza real generada con SUMO
 *   sobre el mapa de Cuenca (centro histórico -> Hospital Vicente Corral
 *   Moscoso), con tráfico de fondo y semáforos.
 * - 4 gNBs desplegadas a lo largo de la ruta (o 1 con --numGnb=1).
 * - Handover X2 real disparado por un gestor de proximidad: cuando otra
 *   celda queda más cerca que la servidora (con histéresis), el RRC del
 *   gNB origen inicia el traspaso; al completarse se re-apuntan los haces.
 * - 3 flujos UE->hospital: signos vitales (URLLC), video (eMBB), GPS
 * - Métricas: FlowMonitor + trazas PHY del módulo NR
 */

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/applications-module.h"
#include "ns3/mobility-module.h"
#include "ns3/ns2-mobility-helper.h"
#include "ns3/point-to-point-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/nr-module.h"
#include "ns3/antenna-module.h"
#include "ns3/lte-ue-rrc.h"
#include "ns3/lte-enb-rrc.h"

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("Ambulancia5G");

/*
 * El IdealBeamformingHelper acumula tareas (gNB,UE) y nunca las borra: tras
 * un handover quedaría una tarea apuntando el haz del UE a la celda vieja.
 * Esta subclase permite sustituir todas las tareas por la de la nueva celda
 * servidora (el mapa de tareas es protected en la clase base).
 */
class HandoverBeamformingHelper : public IdealBeamformingHelper
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("HandoverBeamformingHelper")
                                .SetParent<IdealBeamformingHelper>()
                                .AddConstructor<HandoverBeamformingHelper>();
        return tid;
    }

    void ReplaceBeamformingTask(const Ptr<NrGnbNetDevice>& gnbDev,
                                const Ptr<NrUeNetDevice>& ueDev)
    {
        m_spectrumPhyPairToDevicePair.clear();
        AddBeamformingTask(gnbDev, ueDev);
    }
};

// ----- Estado global del gestor de handover -----
static Ptr<HandoverBeamformingHelper> g_beamHelper;
static Ptr<NrUeNetDevice> g_ueDev;
static std::map<uint16_t, Ptr<NrGnbNetDevice>> g_celdas; // cellId -> gNB (todos los IDs)
static std::vector<Ptr<NrGnbNetDevice>> g_gnbs;          // lista única de gNBs
static uint32_t g_numHandovers = 0;
static double g_hoDisparado = -1e9; // instante del último disparo de handover

static double
DistanciaACelda(uint16_t cellId, const Vector& posUe)
{
    Vector p = g_celdas.at(cellId)->GetNode()->GetObject<MobilityModel>()->GetPosition();
    return std::hypot(p.x - posUe.x, p.y - posUe.y);
}

// Gestor de handover por proximidad: si otra celda queda más cerca que la
// servidora por más de `margen` metros, dispara el traspaso X2.
static void
ComprobarHandover(double margen)
{
    Ptr<LteUeRrc> ueRrc = g_ueDev->GetRrc();
    if (ueRrc->GetState() == LteUeRrc::CONNECTED_NORMALLY && g_gnbs.size() > 1 &&
        g_celdas.count(ueRrc->GetCellId()))
    {
        uint16_t servidora = ueRrc->GetCellId();
        Ptr<NrGnbNetDevice> gnbServ = g_celdas.at(servidora);
        Vector posUe = g_ueDev->GetNode()->GetObject<MobilityModel>()->GetPosition();

        Ptr<NrGnbNetDevice> mejor = gnbServ;
        uint16_t mejorCelda = servidora;
        double mejorDist = std::numeric_limits<double>::max();
        for (const auto& g : g_gnbs)
        {
            // El ID de celda "real" (a nivel de portadora) es el de GetCellIds()
            uint16_t cid = g->GetCellIds().at(0);
            double d = DistanciaACelda(cid, posUe);
            if (d < mejorDist)
            {
                mejorDist = d;
                mejor = g;
                mejorCelda = cid;
            }
        }

        double ahora = Simulator::Now().GetSeconds();
        if (mejor != gnbServ && DistanciaACelda(servidora, posUe) - mejorDist > margen &&
            ahora - g_hoDisparado > 5.0) // no re-disparar mientras hay uno en curso
        {
            std::cout << "t=" << ahora << "s  INICIO HANDOVER celda " << servidora << " -> "
                      << mejorCelda << "\n";
            g_hoDisparado = ahora;
            // La PHY del gNB destino debe conocer al UE (beam management) y
            // los haces deben apuntar ya al destino para que el acceso
            // aleatorio (preambulo/RAR) llegue con ganancia de antena.
            mejor->GetPhy(0)->RegisterUe(g_ueDev->GetImsi(), g_ueDev);
            g_beamHelper->ReplaceBeamformingTask(mejor, g_ueDev);
            gnbServ->GetRrc()->SendHandoverRequest(ueRrc->GetRnti(), mejorCelda);
            Ptr<UeManager> um = gnbServ->GetRrc()->GetUeManager(ueRrc->GetRnti());
            std::cout << "    estado UeManager fuente tras disparo: " << um->GetState() << "\n";
        }
    }
    Simulator::Schedule(MilliSeconds(500), &ComprobarHandover, margen);
}

static void
GnbHoStart(uint64_t imsi, uint16_t cellId, uint16_t /*rnti*/, uint16_t targetCellId)
{
    std::cout << "t=" << Simulator::Now().GetSeconds() << "s  [gNB celda " << cellId
              << "] envia orden de handover hacia celda " << targetCellId << "\n";
}

static void
UeHoStart(uint64_t /*imsi*/, uint16_t cellId, uint16_t /*rnti*/, uint16_t targetCellId)
{
    std::cout << "t=" << Simulator::Now().GetSeconds() << "s  [UE] deja celda " << cellId
              << ", sincronizando con celda " << targetCellId << "\n";
}

// Al completarse el handover, apuntar los haces a la nueva celda servidora
static void
HandoverCompletado(uint64_t imsi, uint16_t cellId, uint16_t /*rnti*/)
{
    g_numHandovers++;
    std::cout << "t=" << Simulator::Now().GetSeconds() << "s  HANDOVER COMPLETADO: UE " << imsi
              << " conectado a celda " << cellId << "\n";
    g_beamHelper->ReplaceBeamformingTask(g_celdas.at(cellId), g_ueDev);
}

// Imprime cada 5 s la posición de la ambulancia, celda servidora y distancia
static void
LogPosicion(Ptr<Node> ue)
{
    Vector p = ue->GetObject<MobilityModel>()->GetPosition();
    uint16_t celda = g_ueDev->GetRrc()->GetCellId();
    double d = g_celdas.count(celda) ? DistanciaACelda(celda, p) : -1.0;
    std::cout << "t=" << Simulator::Now().GetSeconds() << "s  amb=(" << p.x << "," << p.y
              << ")  celda=" << celda << "  dist=" << d << " m\n";
    Simulator::Schedule(Seconds(5.0), &LogPosicion, ue);
}

int main(int argc, char* argv[])
{
    // ----- Parámetros generales -----
    double simTime = 225.0;         // segundos (viaje SUMO: 223.4 s)
    double frequency = 3.5e9;       // 3.5 GHz (banda n78, macro urbana)
    double bandwidth = 20e6;        // 20 MHz (mejor presupuesto de enlace)
    uint16_t numerology = 1;        // numerología 5G NR (sub-6 GHz)
    uint16_t numGnb = 4;            // número de gNBs a lo largo de la ruta
    double margenHo = 50.0;         // histéresis de handover (m)
    std::string traceFile =
        "/home/thyron001/Desktop/moviles/sumo/mobility_amb.tcl";

    // Posiciones de las gNBs: puntos de la ruta SUMO en t=28,84,140,196 s
    // (una por cuarto del recorrido). Con --numGnb=1 se usa el centro.
    double gnbPos[4][2] = {{1926.4, 3060.4},
                           {2408.0, 2650.4},
                           {3079.2, 2373.4},
                           {3326.6, 1931.1}};
    const double gnbUnica[2] = {2687.0, 2515.0};
    double gnbZ = 25.0;             // altura de antena macro urbana

    CommandLine cmd(__FILE__);
    cmd.AddValue("simTime", "Duración de la simulación (s)", simTime);
    cmd.AddValue("frequency", "Frecuencia portadora (Hz)", frequency);
    cmd.AddValue("numerology", "Numerología 5G NR", numerology);
    cmd.AddValue("numGnb", "Número de gNBs (1 a 4)", numGnb);
    cmd.AddValue("margenHo", "Histéresis de handover (m)", margenHo);
    cmd.AddValue("traceFile", "Traza de movilidad ns-2 (SUMO)", traceFile);
    cmd.Parse(argc, argv);
    NS_ABORT_MSG_IF(numGnb < 1 || numGnb > 4, "numGnb debe estar entre 1 y 4");

    // ----- Nodos -----
    NodeContainer gnbNodes;
    gnbNodes.Create(numGnb);
    NodeContainer ueNodes;
    ueNodes.Create(1);   // la ambulancia

    // ----- Movilidad -----
    MobilityHelper gnbMobility;
    gnbMobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    gnbMobility.Install(gnbNodes);
    for (uint16_t i = 0; i < numGnb; ++i)
    {
        double x = (numGnb == 1) ? gnbUnica[0] : gnbPos[i][0];
        double y = (numGnb == 1) ? gnbUnica[1] : gnbPos[i][1];
        gnbNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(x, y, gnbZ));
    }

    // Ambulancia: traza real de SUMO (Cuenca, con tráfico y semáforos)
    Ns2MobilityHelper ns2Mobility(traceFile);
    ns2Mobility.Install(ueNodes.Begin(), ueNodes.End());

    // ----- Configuración NR (5G-LENA) -----
    Ptr<NrPointToPointEpcHelper> epcHelper = CreateObject<NrPointToPointEpcHelper>();
    Ptr<HandoverBeamformingHelper> beamHelper = CreateObject<HandoverBeamformingHelper>();
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    nrHelper->SetBeamformingHelper(beamHelper);
    nrHelper->SetEpcHelper(epcHelper);

    // Una banda con un componente de portadora (compartida por las celdas)
    CcBwpCreator ccBwpCreator;
    CcBwpCreator::SimpleOperationBandConf bandConf(frequency, bandwidth, 1,
                                                   BandwidthPartInfo::UMa);
    OperationBandInfo band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf);
    nrHelper->InitializeOperationBand(&band);
    BandwidthPartInfoPtrVector allBwps = CcBwpCreator::GetAllBwps({band});

    // Numerología y potencia
    nrHelper->SetGnbPhyAttribute("Numerology", UintegerValue(numerology));
    nrHelper->SetGnbPhyAttribute("TxPower", DoubleValue(43.0)); // macro urbana
    nrHelper->SetUePhyAttribute("TxPower", DoubleValue(23.0));

    // Antenas
    nrHelper->SetUeAntennaAttribute("NumRows", UintegerValue(2));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumRows", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(8));

    // Instalar dispositivos
    NetDeviceContainer gnbDevs = nrHelper->InstallGnbDevice(gnbNodes, allBwps);
    NetDeviceContainer ueDevs = nrHelper->InstallUeDevice(ueNodes, allBwps);

    for (auto it = gnbDevs.Begin(); it != gnbDevs.End(); ++it)
        DynamicCast<NrGnbNetDevice>(*it)->UpdateConfig();
    for (auto it = ueDevs.Begin(); it != ueDevs.End(); ++it)
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();

    // ----- Núcleo de red y servidor remoto (hospital) -----
    Ptr<Node> pgw = epcHelper->GetPgwNode();
    NodeContainer remoteHostContainer;
    remoteHostContainer.Create(1);
    Ptr<Node> remoteHost = remoteHostContainer.Get(0); // HOSPITAL

    InternetStackHelper internet;
    internet.Install(remoteHostContainer);

    // Enlace PGW <-> hospital
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", DataRateValue(DataRate("10Gbps")));
    p2p.SetChannelAttribute("Delay", TimeValue(MilliSeconds(5)));
    NetDeviceContainer internetDevices = p2p.Install(pgw, remoteHost);

    Ipv4AddressHelper ipv4h;
    ipv4h.SetBase("1.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer internetIfaces = ipv4h.Assign(internetDevices);
    Ipv4Address remoteHostAddr = internetIfaces.GetAddress(1);

    Ipv4StaticRoutingHelper routingHelper;
    Ptr<Ipv4StaticRouting> remoteHostRouting =
        routingHelper.GetStaticRouting(remoteHost->GetObject<Ipv4>());
    remoteHostRouting->AddNetworkRouteTo(Ipv4Address("7.0.0.0"),
                                         Ipv4Mask("255.0.0.0"), 1);

    // Pila IP en el UE
    internet.Install(ueNodes);
    Ipv4InterfaceContainer ueIpIface =
        epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueDevs));
    Ptr<Ipv4StaticRouting> ueRouting =
        routingHelper.GetStaticRouting(ueNodes.Get(0)->GetObject<Ipv4>());
    ueRouting->SetDefaultRoute(epcHelper->GetUeDefaultGatewayAddress(), 1);

    // Interfaces X2 entre todas las gNBs (necesarias para el handover)
    for (uint16_t i = 0; i < numGnb; ++i)
        for (uint16_t j = i + 1; j < numGnb; ++j)
            epcHelper->AddX2Interface(gnbNodes.Get(i), gnbNodes.Get(j));

    // Conectar UE a la gNB más cercana al inicio de la ruta
    nrHelper->AttachToClosestEnb(ueDevs, gnbDevs);

    // ----- Gestor de handover -----
    g_beamHelper = beamHelper;
    g_ueDev = DynamicCast<NrUeNetDevice>(ueDevs.Get(0));
    for (auto it = gnbDevs.Begin(); it != gnbDevs.End(); ++it)
    {
        Ptr<NrGnbNetDevice> g = DynamicCast<NrGnbNetDevice>(*it);
        g_gnbs.push_back(g);
        g_celdas[g->GetCellId()] = g;
        std::cout << "gNB en (" << g->GetNode()->GetObject<MobilityModel>()->GetPosition().x
                  << "," << g->GetNode()->GetObject<MobilityModel>()->GetPosition().y
                  << ")  GetCellId=" << g->GetCellId() << "  GetCellIds=[";
        for (uint16_t cid : g->GetCellIds())
        {
            g_celdas[cid] = g; // un gNB puede exponer varios cell IDs (BWPs)
            std::cout << cid << " ";
        }
        std::cout << "]\n";
    }
    g_ueDev->GetRrc()->TraceConnectWithoutContext(
        "HandoverEndOk", MakeCallback(&HandoverCompletado));
    g_ueDev->GetRrc()->TraceConnectWithoutContext(
        "HandoverStart", MakeCallback(&UeHoStart));
    for (const auto& g : g_gnbs)
        g->GetRrc()->TraceConnectWithoutContext("HandoverStart", MakeCallback(&GnbHoStart));
    Simulator::Schedule(MilliSeconds(500), &ComprobarHandover, margenHo);

    // ----- APLICACIONES (los 3 tipos de tráfico) -----
    uint16_t portVitales = 5000;
    uint16_t portVideo   = 5001;
    uint16_t portGps     = 5002;
    ApplicationContainer serverApps, clientApps;

    // Servidores (sinks) en el HOSPITAL
    UdpServerHelper srvVitales(portVitales);
    UdpServerHelper srvVideo(portVideo);
    UdpServerHelper srvGps(portGps);
    serverApps.Add(srvVitales.Install(remoteHost));
    serverApps.Add(srvVideo.Install(remoteHost));
    serverApps.Add(srvGps.Install(remoteHost));

    // 1) SIGNOS VITALES: 100 bytes cada 100 ms (~8 kbps) - crítico
    UdpClientHelper appVitales(remoteHostAddr, portVitales);
    appVitales.SetAttribute("MaxPackets", UintegerValue(1000000));
    appVitales.SetAttribute("Interval", TimeValue(MilliSeconds(100)));
    appVitales.SetAttribute("PacketSize", UintegerValue(100));
    clientApps.Add(appVitales.Install(ueNodes.Get(0)));

    // 2) VIDEO en tiempo real: flujo constante de 4 Mbps
    //    (paquetes de 1000 bytes cada 2 ms)
    UdpClientHelper appVideo(remoteHostAddr, portVideo);
    appVideo.SetAttribute("MaxPackets", UintegerValue(10000000));
    appVideo.SetAttribute("Interval", TimeValue(MilliSeconds(2)));
    appVideo.SetAttribute("PacketSize", UintegerValue(1000));
    clientApps.Add(appVideo.Install(ueNodes.Get(0)));

    // 3) GPS: 80 bytes cada 2 s
    UdpClientHelper appGps(remoteHostAddr, portGps);
    appGps.SetAttribute("MaxPackets", UintegerValue(100000));
    appGps.SetAttribute("Interval", TimeValue(Seconds(2)));
    appGps.SetAttribute("PacketSize", UintegerValue(80));
    clientApps.Add(appGps.Install(ueNodes.Get(0)));

    serverApps.Start(Seconds(0.5));
    clientApps.Start(Seconds(1.0));
    clientApps.Stop(Seconds(simTime - 0.5));

    Simulator::Schedule(Seconds(0.0), &LogPosicion, ueNodes.Get(0));

    nrHelper->EnableTraces(); // trazas PHY/MAC del módulo NR (SINR, MCS, ...)

    // ----- FlowMonitor (métricas) -----
    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();

    Simulator::Stop(Seconds(simTime));
    Simulator::Run();

    // ----- Resultados por flujo -----
    monitor->CheckForLostPackets();
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    auto stats = monitor->GetFlowStats();

    std::cout << "\n===== RESULTADOS DE LA SIMULACION =====\n";
    std::cout << "gNBs: " << numGnb << "   Handovers completados: " << g_numHandovers << "\n";
    for (auto const& flow : stats)
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(flow.first);
        std::string nombre = "Otro";
        if (t.destinationPort == portVitales) nombre = "SIGNOS VITALES";
        else if (t.destinationPort == portVideo) nombre = "VIDEO";
        else if (t.destinationPort == portGps) nombre = "GPS";

        double duration = simTime - 1.5;
        double throughput = flow.second.rxBytes * 8.0 / duration / 1e6; // Mbps
        double delay = (flow.second.rxPackets > 0)
            ? flow.second.delaySum.GetMilliSeconds() / (double)flow.second.rxPackets : 0;
        double jitter = (flow.second.rxPackets > 1)
            ? flow.second.jitterSum.GetMilliSeconds() / (double)(flow.second.rxPackets - 1) : 0;
        double loss = (flow.second.txPackets > 0)
            ? 100.0 * (flow.second.txPackets - flow.second.rxPackets) / flow.second.txPackets : 0;

        std::cout << "\nFlujo: " << nombre
                  << " (" << t.sourceAddress << " -> " << t.destinationAddress << ")\n"
                  << "  Paquetes Tx/Rx : " << flow.second.txPackets
                  << " / " << flow.second.rxPackets << "\n"
                  << "  Throughput     : " << throughput << " Mbps\n"
                  << "  Latencia media : " << delay << " ms\n"
                  << "  Jitter medio   : " << jitter << " ms\n"
                  << "  Perdida        : " << loss << " %\n";
    }

    // Exportar a XML para análisis posterior
    monitor->SerializeToXmlFile("resultados-ambulancia.xml", true, true);

    Simulator::Destroy();
    return 0;
}
