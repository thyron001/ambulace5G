/*
 * Demo: Ambulancia inteligente con 5G NR (5G-LENA)
 * - UE móvil (ambulancia) -> gNB -> Servidor remoto (hospital)
 * - 3 flujos: signos vitales (URLLC), video (eMBB), GPS
 * - Métricas: throughput, latencia, jitter, pérdida de paquetes (FlowMonitor)
 */

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/applications-module.h"
#include "ns3/mobility-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/nr-module.h"
#include "ns3/antenna-module.h"

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("Ambulancia5G");

int main(int argc, char* argv[])
{
    // ----- Parámetros generales -----
    double simTime = 30.0;          // segundos
    double frequency = 28e9;        // 28 GHz (mmWave)
    double bandwidth = 100e6;       // 100 MHz
    double ambSpeed = 13.9;         // 50 km/h en m/s
    uint16_t numerology = 3;        // numerología 5G NR (mmWave)

    CommandLine cmd(__FILE__);
    cmd.AddValue("simTime", "Duración de la simulación (s)", simTime);
    cmd.Parse(argc, argv);

    // ----- Nodos -----
    NodeContainer gnbNodes;
    gnbNodes.Create(1);
    NodeContainer ueNodes;
    ueNodes.Create(1);   // la ambulancia

    // ----- Movilidad -----
    // gNB fija a 10 m de altura
    MobilityHelper gnbMobility;
    gnbMobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    gnbMobility.Install(gnbNodes);
    gnbNodes.Get(0)->GetObject<MobilityModel>()->SetPosition(Vector(0.0, 0.0, 10.0));

    // Ambulancia: velocidad constante, pasa cerca de la gNB
    MobilityHelper ueMobility;
    ueMobility.SetMobilityModel("ns3::ConstantVelocityMobilityModel");
    ueMobility.Install(ueNodes);
    ueNodes.Get(0)->GetObject<MobilityModel>()->SetPosition(Vector(-200.0, 30.0, 1.5));
    ueNodes.Get(0)->GetObject<ConstantVelocityMobilityModel>()
        ->SetVelocity(Vector(ambSpeed, 0.0, 0.0)); // se mueve en eje X

    // ----- Configuración NR (5G-LENA) -----
    Ptr<NrPointToPointEpcHelper> epcHelper = CreateObject<NrPointToPointEpcHelper>();
    Ptr<IdealBeamformingHelper> beamHelper = CreateObject<IdealBeamformingHelper>();
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    nrHelper->SetBeamformingHelper(beamHelper);
    nrHelper->SetEpcHelper(epcHelper);

    // Una banda con un componente de portadora
    CcBwpCreator ccBwpCreator;
    CcBwpCreator::SimpleOperationBandConf bandConf(frequency, bandwidth, 1,
                                                   BandwidthPartInfo::UMa);
    OperationBandInfo band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf);
    nrHelper->InitializeOperationBand(&band);
    BandwidthPartInfoPtrVector allBwps = CcBwpCreator::GetAllBwps({band});

    // Numerología y potencia
    nrHelper->SetGnbPhyAttribute("Numerology", UintegerValue(numerology));
    nrHelper->SetGnbPhyAttribute("TxPower", DoubleValue(30.0));
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

    // Conectar UE a la gNB
    nrHelper->AttachToClosestEnb(ueDevs, gnbDevs);

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
