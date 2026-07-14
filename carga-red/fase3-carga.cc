/*
 * FASE 3 — Verificación de URLLC vs eMBB bajo carga de red vehicular.
 *
 * Ventana corta (95 s) del viaje de la ambulancia que cubre 3 celdas 5G
 * (con handover X2). Además de la ambulancia, la celda que la sirve está
 * cargada por UEs de fondo (autos que compartieron celda, filtrados en la
 * Fase 1 y muestreados en la Fase 2) que generan tráfico eMBB uplink.
 *
 * Tres modos:
 *   --carga=0                : SIN carga (solo ambulancia).
 *   --carga=1 --slicing=0    : CON carga, scheduler round-robin (sin protección).
 *   --carga=1 --slicing=1    : CON carga, scheduler QoS + bearer URLLC dedicado
 *                              para los signos vitales (protección URLLC/eMBB).
 *
 * Señales vitales = URLLC (bearer DGBR alta prioridad).
 * Video de la ambulancia + datos de los autos = eMBB.
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

#include <fstream>
#include <chrono>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("Fase3Carga");

// ---- Log de progreso con porcentaje real y ETA en tiempo de reloj ----
static std::chrono::steady_clock::time_point g_wallStart;
static void
Progreso(double simTime)
{
    double t = Simulator::Now().GetSeconds();
    double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - g_wallStart).count();
    double pct = 100.0 * t / simTime;
    double eta = pct > 1.0 ? wall * (100.0 - pct) / pct : 0.0;
    std::cout << "PROGRESO t=" << t << "/" << simTime << "s (" << (int)pct
              << "%) wall=" << (int)wall << "s ETA=" << (int)eta << "s\n";
    if (t < simTime - 0.05)
        Simulator::Schedule(Seconds(2.0), &Progreso, simTime);
}

// ---- Beamforming helper que permite re-apuntar el haz tras un handover ----
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

static Ptr<HandoverBeamformingHelper> g_beamHelper;
static Ptr<NrUeNetDevice> g_ueDev;
static std::map<uint16_t, Ptr<NrGnbNetDevice>> g_celdas;
static std::vector<Ptr<NrGnbNetDevice>> g_gnbs;
static double g_hoDisparado = -1e9;

static double
DistanciaACelda(uint16_t cellId, const Vector& posUe)
{
    Vector p = g_celdas.at(cellId)->GetNode()->GetObject<MobilityModel>()->GetPosition();
    return std::hypot(p.x - posUe.x, p.y - posUe.y);
}

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
            ahora - g_hoDisparado > 5.0)
        {
            std::cout << "t=" << ahora << "s  HANDOVER celda " << servidora << " -> "
                      << mejorCelda << "\n";
            g_hoDisparado = ahora;
            mejor->GetPhy(0)->RegisterUe(g_ueDev->GetImsi(), g_ueDev);
            g_beamHelper->ReplaceBeamformingTask(mejor, g_ueDev);
            gnbServ->GetRrc()->SendHandoverRequest(ueRrc->GetRnti(), mejorCelda);
        }
    }
    Simulator::Schedule(MilliSeconds(500), &ComprobarHandover, margen);
}

static void
HandoverCompletado(uint64_t /*imsi*/, uint16_t cellId, uint16_t /*rnti*/)
{
    if (g_celdas.count(cellId))
        g_beamHelper->ReplaceBeamformingTask(g_celdas.at(cellId), g_ueDev);
}

int
main(int argc, char* argv[])
{
    double frequency = 3.5e9;
    double bandwidth = 10e6;  // total; con slicing se parte en 2+8 MHz
    uint16_t numerology = 1;
    double simcap = 0.0;      // cap de tiempo de simulación (0 = usar DUR)
    double margenHo = 50.0;
    bool carga = true;    // instanciar UEs de fondo
    bool slicing = false; // scheduler QoS + bearer URLLC dedicado
    std::string escFile = "/home/thyron001/Desktop/moviles/carga-red/escenario_ns3.txt";
    std::string traceFile = "/home/thyron001/Desktop/moviles/carga-red/mobility_amb_ventana.tcl";
    std::string etiqueta = "run";

    CommandLine cmd(__FILE__);
    cmd.AddValue("carga", "Instanciar UEs de fondo (autos)", carga);
    cmd.AddValue("slicing", "Scheduler QoS + bearer URLLC para vitales", slicing);
    cmd.AddValue("escenario", "Archivo de escenario", escFile);
    cmd.AddValue("traceFile", "Traza de movilidad de la ambulancia", traceFile);
    cmd.AddValue("etiqueta", "Nombre del escenario (para el XML)", etiqueta);
    cmd.AddValue("simcap", "Cap de tiempo de simulación (s, 0=usar DUR)", simcap);
    cmd.Parse(argc, argv);

    // ---- Leer escenario (gNBs y UEs de fondo) ----
    double simTime = 95.0;
    std::vector<Vector> gnbPos;
    std::vector<Vector> uePos;
    std::vector<double> ueRate;
    {
        std::ifstream in(escFile);
        NS_ABORT_MSG_IF(!in.is_open(), "No se pudo abrir " << escFile);
        std::string tok;
        while (in >> tok)
        {
            if (tok == "DUR")
                in >> simTime;
            else if (tok == "NGNB" || tok == "NUE")
            {
                int n;
                in >> n;
            }
            else if (tok == "GNB")
            {
                int id;
                double x, y;
                in >> id >> x >> y;
                gnbPos.push_back(Vector(x, y, 25.0));
            }
            else if (tok == "UE")
            {
                double x, y, r;
                in >> x >> y >> r;
                uePos.push_back(Vector(x, y, 1.5));
                ueRate.push_back(r);
            }
        }
    }
    if (simcap > 0.0)
        simTime = simcap;
    simTime += 2.0; // margen para vaciar buffers
    uint32_t numGnb = gnbPos.size();
    uint32_t numBg = carga ? uePos.size() : 0;
    std::cout << "Escenario: " << numGnb << " gNBs, " << numBg
              << " UEs de fondo, carga=" << carga << " slicing=" << slicing << "\n";

    // ---- Nodos ----
    NodeContainer gnbNodes;
    gnbNodes.Create(numGnb);
    NodeContainer ueAmbNodes;
    ueAmbNodes.Create(1);
    NodeContainer ueBgNodes;
    ueBgNodes.Create(numBg);

    // ---- Movilidad ----
    MobilityHelper gnbMob;
    gnbMob.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    gnbMob.Install(gnbNodes);
    for (uint32_t i = 0; i < numGnb; ++i)
        gnbNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(gnbPos[i]);

    Ns2MobilityHelper ns2(traceFile);
    ns2.Install(ueAmbNodes.Begin(), ueAmbNodes.End());

    MobilityHelper bgMob;
    bgMob.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    bgMob.Install(ueBgNodes);
    for (uint32_t i = 0; i < numBg; ++i)
        ueBgNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(uePos[i]);

    // ---- NR ----
    Ptr<NrPointToPointEpcHelper> epcHelper = CreateObject<NrPointToPointEpcHelper>();
    Ptr<HandoverBeamformingHelper> beamHelper = CreateObject<HandoverBeamformingHelper>();
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    nrHelper->SetBeamformingHelper(beamHelper);
    nrHelper->SetEpcHelper(epcHelper);

    // ---- Aceleración: canal cuasi-estático ----
    // El coste dominante es recalcular la matriz MIMO 3GPP cada 100 ms para
    // cada par gNB-UE. Para una ventana corta de estudio de carga basta con
    // calcular el canal una sola vez (los ejemplos de 5G-LENA hacen esto).
    Config::SetDefault("ns3::ThreeGppChannelModel::UpdatePeriod", TimeValue(MilliSeconds(0)));
    nrHelper->SetChannelConditionModelAttribute("UpdatePeriod", TimeValue(MilliSeconds(0)));
    // Beamforming: calcular los haces una sola vez (y de nuevo en cada
    // handover vía ReplaceBeamformingTask), no periódicamente.
    beamHelper->SetAttribute("BeamformingPeriodicity", TimeValue(Seconds(10000.0)));

    // Scheduler round-robin por OFDMA para todas las configuraciones: el
    // aislamiento del slicing viene de dedicar espectro (2ª banda), no del
    // scheduler.
    nrHelper->SetSchedulerTypeId(TypeId::LookupByName("ns3::NrMacSchedulerOfdmaRR"));

    // ---- Espectro ----
    // Sin slicing: 1 banda de `bandwidth`, todos los flujos compiten en ella.
    // Con slicing: 2 bandas DEDICADAS que suman el mismo espectro total:
    //   banda URLLC (bwURLLC) para los signos vitales (aislada), y
    //   banda eMBB (bandwidth - bwURLLC) para el video + los autos.
    // Es el "network slicing" clásico por bandwidth part (patrón cttc-nr-demo).
    CcBwpCreator ccBwpCreator;
    double bwURLLC = 2e6; // ancho reservado a URLLC cuando hay slicing
    BandwidthPartInfoPtrVector allBwps;
    uint32_t bwpURLLC = 0, bwpEMBB = 0;
    OperationBandInfo band1, band2;
    if (!slicing)
    {
        CcBwpCreator::SimpleOperationBandConf conf(frequency, bandwidth, 1,
                                                   BandwidthPartInfo::UMa);
        band1 = ccBwpCreator.CreateOperationBandContiguousCc(conf);
        nrHelper->InitializeOperationBand(&band1);
        allBwps = CcBwpCreator::GetAllBwps({band1});
    }
    else
    {
        CcBwpCreator::SimpleOperationBandConf confU(frequency, bwURLLC, 1,
                                                    BandwidthPartInfo::UMa);
        CcBwpCreator::SimpleOperationBandConf confE(frequency + bandwidth,
                                                    bandwidth - bwURLLC, 1,
                                                    BandwidthPartInfo::UMa);
        band1 = ccBwpCreator.CreateOperationBandContiguousCc(confU);
        band2 = ccBwpCreator.CreateOperationBandContiguousCc(confE);
        nrHelper->InitializeOperationBand(&band1);
        nrHelper->InitializeOperationBand(&band2);
        allBwps = CcBwpCreator::GetAllBwps({band1, band2});
        bwpURLLC = 0;
        bwpEMBB = 1;
    }

    nrHelper->SetGnbPhyAttribute("Numerology", UintegerValue(numerology));
    nrHelper->SetGnbPhyAttribute("TxPower", DoubleValue(43.0));
    nrHelper->SetUePhyAttribute("TxPower", DoubleValue(23.0));
    nrHelper->SetUeAntennaAttribute("NumRows", UintegerValue(2));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumRows", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(8));

    // Enrutado de bearers -> bandwidth part (5QI): vitales a la banda URLLC,
    // el resto a la banda eMBB (con slicing ambas difieren; sin slicing todo
    // va a la BWP 0).
    nrHelper->SetGnbBwpManagerAlgorithmAttribute("DGBR_INTER_SERV_87", UintegerValue(bwpURLLC));
    nrHelper->SetGnbBwpManagerAlgorithmAttribute("NGBR_LOW_LAT_EMBB", UintegerValue(bwpEMBB));
    nrHelper->SetGnbBwpManagerAlgorithmAttribute("NGBR_VIDEO_TCP_DEFAULT", UintegerValue(bwpEMBB));
    nrHelper->SetUeBwpManagerAlgorithmAttribute("DGBR_INTER_SERV_87", UintegerValue(bwpURLLC));
    nrHelper->SetUeBwpManagerAlgorithmAttribute("NGBR_LOW_LAT_EMBB", UintegerValue(bwpEMBB));
    nrHelper->SetUeBwpManagerAlgorithmAttribute("NGBR_VIDEO_TCP_DEFAULT", UintegerValue(bwpEMBB));

    NetDeviceContainer gnbDevs = nrHelper->InstallGnbDevice(gnbNodes, allBwps);
    NetDeviceContainer ueAmbDevs = nrHelper->InstallUeDevice(ueAmbNodes, allBwps);
    NetDeviceContainer ueBgDevs = nrHelper->InstallUeDevice(ueBgNodes, allBwps);

    for (auto it = gnbDevs.Begin(); it != gnbDevs.End(); ++it)
        DynamicCast<NrGnbNetDevice>(*it)->UpdateConfig();
    for (auto it = ueAmbDevs.Begin(); it != ueAmbDevs.End(); ++it)
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();
    for (auto it = ueBgDevs.Begin(); it != ueBgDevs.End(); ++it)
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();

    // ---- Núcleo + hospital ----
    Ptr<Node> pgw = epcHelper->GetPgwNode();
    NodeContainer remoteHostContainer;
    remoteHostContainer.Create(1);
    Ptr<Node> remoteHost = remoteHostContainer.Get(0);
    InternetStackHelper internet;
    internet.Install(remoteHostContainer);

    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", DataRateValue(DataRate("100Gbps")));
    p2p.SetChannelAttribute("Delay", TimeValue(MilliSeconds(5)));
    NetDeviceContainer internetDevices = p2p.Install(pgw, remoteHost);
    Ipv4AddressHelper ipv4h;
    ipv4h.SetBase("1.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer internetIfaces = ipv4h.Assign(internetDevices);
    Ipv4Address remoteHostAddr = internetIfaces.GetAddress(1);

    Ipv4StaticRoutingHelper routingHelper;
    Ptr<Ipv4StaticRouting> remoteHostRouting =
        routingHelper.GetStaticRouting(remoteHost->GetObject<Ipv4>());
    remoteHostRouting->AddNetworkRouteTo(Ipv4Address("7.0.0.0"), Ipv4Mask("255.0.0.0"), 1);

    internet.Install(ueAmbNodes);
    internet.Install(ueBgNodes);
    Ipv4InterfaceContainer ueAmbIp = epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueAmbDevs));
    Ipv4InterfaceContainer ueBgIp = epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueBgDevs));

    for (uint32_t i = 0; i < ueAmbNodes.GetN(); ++i)
    {
        Ptr<Ipv4StaticRouting> r =
            routingHelper.GetStaticRouting(ueAmbNodes.Get(i)->GetObject<Ipv4>());
        r->SetDefaultRoute(epcHelper->GetUeDefaultGatewayAddress(), 1);
    }
    for (uint32_t i = 0; i < ueBgNodes.GetN(); ++i)
    {
        Ptr<Ipv4StaticRouting> r =
            routingHelper.GetStaticRouting(ueBgNodes.Get(i)->GetObject<Ipv4>());
        r->SetDefaultRoute(epcHelper->GetUeDefaultGatewayAddress(), 1);
    }

    nrHelper->AttachToClosestEnb(ueAmbDevs, gnbDevs);
    nrHelper->AttachToClosestEnb(ueBgDevs, gnbDevs);

    // ---- Handover (solo la ambulancia) ----
    g_beamHelper = beamHelper;
    g_ueDev = DynamicCast<NrUeNetDevice>(ueAmbDevs.Get(0));
    for (auto it = gnbDevs.Begin(); it != gnbDevs.End(); ++it)
    {
        Ptr<NrGnbNetDevice> g = DynamicCast<NrGnbNetDevice>(*it);
        g_gnbs.push_back(g);
        g_celdas[g->GetCellId()] = g;
        for (uint16_t cid : g->GetCellIds())
            g_celdas[cid] = g;
    }
    for (uint32_t i = 0; i < numGnb; ++i)
        for (uint32_t j = i + 1; j < numGnb; ++j)
            epcHelper->AddX2Interface(gnbNodes.Get(i), gnbNodes.Get(j));
    g_ueDev->GetRrc()->TraceConnectWithoutContext("HandoverEndOk",
                                                  MakeCallback(&HandoverCompletado));
    Simulator::Schedule(MilliSeconds(500), &ComprobarHandover, margenHo);

    // ---- Aplicaciones (downlink hospital -> UEs) ----
    // El QoS/slicing de 5G-LENA está bien soportado en downlink (es el patrón
    // de los ejemplos oficiales). El hospital transmite a la ambulancia los
    // signos vitales (URLLC) y el video (eMBB); a los autos, streams eMBB.
    uint16_t portVitales = 5000, portVideo = 5001;
    Ipv4Address ambAddr = ueAmbIp.GetAddress(0);
    ApplicationContainer serverApps, clientApps;

    // Servidores (sinks) en las UEs receptoras
    UdpServerHelper srvVitales(portVitales);
    UdpServerHelper srvVideo(portVideo);
    serverApps.Add(srvVitales.Install(ueAmbNodes.Get(0)));
    serverApps.Add(srvVideo.Install(ueAmbNodes.Get(0)));

    // 1) SIGNOS VITALES (URLLC): 100 B cada 20 ms (~40 kbps), crítico
    UdpClientHelper appVitales(ambAddr, portVitales);
    appVitales.SetAttribute("MaxPackets", UintegerValue(0xFFFFFFFF));
    appVitales.SetAttribute("Interval", TimeValue(MilliSeconds(20)));
    appVitales.SetAttribute("PacketSize", UintegerValue(100));
    clientApps.Add(appVitales.Install(remoteHost));

    // 2) VIDEO (eMBB): 4 Mbps
    UdpClientHelper appVideo(ambAddr, portVideo);
    appVideo.SetAttribute("MaxPackets", UintegerValue(0xFFFFFFFF));
    appVideo.SetAttribute("Interval", TimeValue(Seconds(1200.0 * 8 / 4e6)));
    appVideo.SetAttribute("PacketSize", UintegerValue(1200));
    clientApps.Add(appVideo.Install(remoteHost));

    // 3) UEs de fondo (eMBB): stream de tasa aleatoria por auto
    uint16_t portBg = 6000;
    for (uint32_t i = 0; i < numBg; ++i)
    {
        UdpServerHelper s(portBg + i);
        serverApps.Add(s.Install(ueBgNodes.Get(i)));
        UdpClientHelper c(ueBgIp.GetAddress(i), portBg + i);
        c.SetAttribute("MaxPackets", UintegerValue(0xFFFFFFFF));
        c.SetAttribute("PacketSize", UintegerValue(1200));
        c.SetAttribute("Interval", TimeValue(Seconds(1200.0 * 8 / (ueRate[i] * 1e6))));
        clientApps.Add(c.Install(remoteHost));
    }

    // ---- Bearers dedicados (solo con slicing) ----
    // Filtros por puerto LOCAL (destino en la UE) porque el tráfico es DL.
    if (slicing)
    {
        // Vitales -> URLLC (DGBR, prioridad alta)
        GbrQosInformation qv;
        qv.gbrDl = 200e3;
        EpsBearer urllc(EpsBearer::DGBR_INTER_SERV_87, qv);
        Ptr<EpcTft> tftV = Create<EpcTft>();
        EpcTft::PacketFilter pfV;
        pfV.localPortStart = portVitales;
        pfV.localPortEnd = portVitales;
        tftV->Add(pfV);
        nrHelper->ActivateDedicatedEpsBearer(ueAmbDevs.Get(0), urllc, tftV);

        // Video -> eMBB
        EpsBearer embb(EpsBearer::NGBR_LOW_LAT_EMBB);
        Ptr<EpcTft> tftE = Create<EpcTft>();
        EpcTft::PacketFilter pfE;
        pfE.localPortStart = portVideo;
        pfE.localPortEnd = portVideo;
        tftE->Add(pfE);
        nrHelper->ActivateDedicatedEpsBearer(ueAmbDevs.Get(0), embb, tftE);

        // Autos de fondo -> eMBB
        for (uint32_t i = 0; i < numBg; ++i)
        {
            EpsBearer e(EpsBearer::NGBR_LOW_LAT_EMBB);
            Ptr<EpcTft> t = Create<EpcTft>();
            EpcTft::PacketFilter pf;
            pf.localPortStart = portBg + i;
            pf.localPortEnd = portBg + i;
            t->Add(pf);
            nrHelper->ActivateDedicatedEpsBearer(ueBgDevs.Get(i), e, t);
        }
    }

    serverApps.Start(Seconds(0.3));
    clientApps.Start(Seconds(1.0));
    clientApps.Stop(Seconds(simTime - 0.5));

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();

    nrHelper->EnableTraces(); // trazas PHY/MAC (RxPacketTrace: RB/MCS/tbSize por UE)

    g_wallStart = std::chrono::steady_clock::now();
    Simulator::Schedule(Seconds(2.0), &Progreso, simTime);
    Simulator::Stop(Seconds(simTime));
    Simulator::Run();

    // ---- Mapeo RNTI -> UE (para interpretar RxPacketTrace) ----
    std::cout << "MAPEO,amb," << g_ueDev->GetRrc()->GetRnti() << "\n";
    for (uint32_t i = 0; i < numBg; ++i)
    {
        Ptr<NrUeNetDevice> bg = DynamicCast<NrUeNetDevice>(ueBgDevs.Get(i));
        std::cout << "MAPEO,bg" << i << "," << bg->GetRrc()->GetRnti()
                  << "," << ueRate[i] << "\n";
    }

    // ---- Resultados: solo los flujos de la ambulancia ----
    monitor->CheckForLostPackets();
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    auto stats = monitor->GetFlowStats();
    double dur = simTime - 1.5;

    std::cout << "\n===== FASE 3 [" << etiqueta << "] =====\n";
    for (auto const& flow : stats)
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(flow.first);
        std::string nombre;
        if (t.destinationPort == portVitales)
            nombre = "SIGNOS_VITALES_URLLC";
        else if (t.destinationPort == portVideo)
            nombre = "VIDEO_eMBB";
        else
            continue; // omitir los flujos de fondo en el resumen
        double thr = flow.second.rxBytes * 8.0 / dur / 1e6;
        double delay = flow.second.rxPackets
                           ? flow.second.delaySum.GetMicroSeconds() / 1e3 / flow.second.rxPackets
                           : 0;
        double jitter = flow.second.rxPackets > 1
                            ? flow.second.jitterSum.GetMicroSeconds() / 1e3 /
                                  (flow.second.rxPackets - 1)
                            : 0;
        double loss = flow.second.txPackets
                          ? 100.0 * (flow.second.txPackets - flow.second.rxPackets) /
                                flow.second.txPackets
                          : 0;
        std::cout << nombre << " thr=" << thr << "Mbps lat=" << delay << "ms jit=" << jitter
                  << "ms loss=" << loss << "%\n";
        std::cout << "CSV," << etiqueta << "," << nombre << "," << thr << "," << delay << ","
                  << jitter << "," << loss << "\n";
    }

    Simulator::Destroy();
    return 0;
}
