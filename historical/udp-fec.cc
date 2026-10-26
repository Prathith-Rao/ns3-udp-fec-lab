// UDP audio traffic experiment for ns-3.45.
// Copy to scratch/udp-fec.cc. Run: ./ns3 run "udp-fec --mode=fec --loss=0.1"
// All payloads are synthetic. This program does not implement an audio codec or RTP.

#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

using namespace ns3;

// A real serialized application header: 25 bytes, using network byte order.
// Each block has uniformly spaced source packets. Metadata lets the receiver
// derive a missing packet's ID and original generation time without sender state.
class AudioHeader : public Header
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::ProjectAudioHeader")
                                .SetParent<Header>()
                                .AddConstructor<AudioHeader>();
        return tid;
    }
    TypeId GetInstanceTypeId() const override { return GetTypeId(); }
    uint32_t GetSerializedSize() const override { return 25; }
    void Serialize(Buffer::Iterator i) const override
    {
        i.WriteHtonU32(0x55464543);
        i.WriteU8(parity ? 1 : 0);
        i.WriteHtonU32(base);
        i.WriteHtonU16(index);
        i.WriteHtonU16(count);
        i.WriteHtonU64(baseTimeNs);
        i.WriteHtonU32(intervalNs);
    }
    uint32_t Deserialize(Buffer::Iterator i) override
    {
        NS_ABORT_MSG_IF(i.ReadNtohU32() != 0x55464543, "Invalid application header");
        const auto kind = i.ReadU8();
        NS_ABORT_MSG_IF(kind > 1, "Invalid packet kind");
        parity = kind == 1;
        base = i.ReadNtohU32();
        index = i.ReadNtohU16();
        count = i.ReadNtohU16();
        baseTimeNs = i.ReadNtohU64();
        intervalNs = i.ReadNtohU32();
        return GetSerializedSize();
    }
    void Print(std::ostream& os) const override
    {
        os << (parity ? "PARITY" : "DATA") << " base=" << base << " index=" << index;
    }
    bool parity{false};
    uint32_t base{0};
    uint16_t index{0};
    uint16_t count{0};
    uint64_t baseTimeNs{0};
    uint32_t intervalNs{0};
};

// Validation hook plus independent random packet loss. It operates at the
// receiver's point-to-point NetDevice, so deliberately lost packets never reach UDP.
// Forced positions are 1-based arrivals at this interface, NOT source packet IDs.
class ExperimentLoss : public ErrorModel
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::ProjectExperimentLoss")
                                .SetParent<ErrorModel>()
                                .AddConstructor<ExperimentLoss>();
        return tid;
    }
    ExperimentLoss() : random(CreateObject<UniformRandomVariable>()) {}
    void Configure(double probability, const std::set<uint64_t>& positions)
    {
        loss = probability;
        forced = positions;
        random->SetStream(1);
    }
    uint64_t arrivals{0};
    uint64_t dropped{0};

  private:
    bool DoCorrupt(Ptr<Packet>) override
    {
        ++arrivals;
        const bool randomDrop = random->GetValue() < loss;
        const bool drop = forced.count(arrivals) != 0 || randomDrop;
        dropped += drop;
        return drop;
    }
    void DoReset() override { arrivals = dropped = 0; }
    double loss{0};
    std::set<uint64_t> forced;
    Ptr<UniformRandomVariable> random;
};

struct Delivery
{
    bool received{false};
    bool recovered{false};
    double delayMs{0};
};

struct Block
{
    AudioHeader header;
    std::map<uint16_t, std::vector<uint8_t>> data;
    std::vector<uint8_t> parity;
};

class AudioExperiment
{
  public:
    std::string mode{"plain"};
    uint32_t packets{200};
    uint32_t group{4};
    uint32_t payload{160};
    uint32_t intervalMs{20};
    double deadlineMs{150};
    bool verbose{false};
    Ptr<Socket> sender;
    Ptr<Socket> receiver;
    Address destination;
    std::vector<Delivery> deliveries;
    uint64_t txPackets{0};
    uint64_t txAppBytes{0};
    uint64_t rxPackets{0};
    uint64_t duplicateData{0};

    // A reproducible payload pattern is an integrity oracle ONLY. Decoding below
    // uses received data and parity, never this generator to fill a missing packet.
    std::vector<uint8_t> MakePayload(uint32_t sequence) const
    {
        std::mt19937 rng(0x91a2b3c4U ^ sequence);
        std::vector<uint8_t> bytes(payload);
        for (auto& byte : bytes)
        {
            byte = static_cast<uint8_t>(rng() & 0xffU);
        }
        return bytes;
    }

    void Generate(uint32_t sequence)
    {
        const uint32_t base = sequence / group * group;
        AudioHeader h;
        h.base = base;
        h.index = static_cast<uint16_t>(sequence - base);
        h.count = static_cast<uint16_t>(std::min(group, packets - base));
        h.baseTimeNs = 1000000000ULL + uint64_t(base) * intervalMs * 1000000ULL;
        h.intervalNs = intervalMs * 1000000U;
        const auto data = MakePayload(sequence);
        Send(h, data);
        if (mode == "duplicate")
        {
            Send(h, data); // Adjacent copies; this choice matters under burst loss.
        }
        if (mode == "fec")
        {
            if (h.index == 0)
            {
                encoder.assign(payload, 0);
            }
            for (uint32_t j = 0; j < payload; ++j)
            {
                encoder[j] ^= data[j];
            }
            if (h.index + 1 == h.count)
            {
                h.parity = true;
                h.index = 0;
                Send(h, encoder);
            }
        }
        if (sequence + 1 < packets)
        {
            Simulator::Schedule(MilliSeconds(intervalMs),
                                &AudioExperiment::Generate, this, sequence + 1);
        }
    }

    void Receive(Ptr<Socket> socket)
    {
        Address from;
        while (auto packet = socket->RecvFrom(from))
        {
            ++rxPackets;
            AudioHeader h;
            NS_ABORT_MSG_IF(packet->GetSize() < h.GetSerializedSize(), "Short header");
            packet->RemoveHeader(h);
            NS_ABORT_MSG_IF(h.count == 0 || h.count > group || h.index >= h.count ||
                                uint64_t(h.base) + h.count > packets ||
                                h.intervalNs != intervalMs * 1000000U ||
                                packet->GetSize() != payload,
                            "Invalid packet metadata or payload size");
            std::vector<uint8_t> bytes(payload);
            packet->CopyData(bytes.data(), payload);
            if (!h.parity)
            {
                Record(h, h.index, bytes, false);
            }
            if (mode != "fec")
            {
                continue;
            }
            auto& block = blocks[h.base];
            block.header = h;
            if (h.parity)
            {
                block.parity = bytes;
            }
            else
            {
                block.data.emplace(h.index, bytes);
            }
            // One parity symbol can resolve exactly one missing DATA symbol.
            if (!block.parity.empty() && block.data.size() + 1 == h.count)
            {
                uint16_t missing = 0;
                while (block.data.count(missing))
                {
                    ++missing;
                }
                auto reconstructed = block.parity;
                for (const auto& item : block.data)
                {
                    for (uint32_t j = 0; j < payload; ++j)
                    {
                        reconstructed[j] ^= item.second[j];
                    }
                }
                Record(block.header, missing, reconstructed, true);
                block.data.emplace(missing, std::move(reconstructed));
            }
        }
    }

    void WriteResults(const std::string& prefix, double loss, uint64_t run,
                      const ExperimentLoss& error) const
    {
        uint32_t received = 0, timely = 0, recovered = 0, timelyRecovered = 0;
        double delaySum = 0;
        std::vector<double> delays;
        std::ofstream details(prefix + "-packets.csv");
        NS_ABORT_MSG_IF(!details, "Cannot create packet CSV; check output directory");
        details << "sequence,generated_s,delivered,recovered,delay_ms,timely\n";
        details << std::fixed << std::setprecision(6);
        for (uint32_t s = 0; s < packets; ++s)
        {
            const auto& d = deliveries[s];
            const bool onTime = d.received && d.delayMs <= deadlineMs + 1e-6;
            received += d.received;
            timely += onTime;
            recovered += d.recovered;
            timelyRecovered += d.recovered && onTime;
            if (d.received)
            {
                delaySum += d.delayMs;
                delays.push_back(d.delayMs);
            }
            details << s << ',' << 1.0 + s * intervalMs / 1000.0 << ','
                    << d.received << ',' << d.recovered << ',';
            if (d.received)
            {
                details << d.delayMs;
            }
            details << ',' << onTime << '\n';
        }
        std::sort(delays.begin(), delays.end());
        std::ofstream summary(prefix + "-summary.csv");
        NS_ABORT_MSG_IF(!summary, "Cannot create summary CSV");
        summary << "mode,run,loss,group,generated,tx_packets,tx_app_bytes,link_arrivals,"
                   "link_drops,rx_packets,unique_delivered,timely_delivered,recovered,"
                   "timely_recovered,duplicate_data,delivery_ratio,timely_ratio,"
                   "residual_loss_ratio,mean_delay_ms,p95_delay_ms,"
                   "app_bytes_per_timely_packet\n";
        summary << std::fixed << std::setprecision(6)
                << mode << ',' << run << ',' << loss << ',' << group << ','
                << packets << ',' << txPackets << ',' << txAppBytes << ','
                << error.arrivals << ',' << error.dropped << ',' << rxPackets << ','
                << received << ',' << timely << ',' << recovered << ','
                << timelyRecovered << ',' << duplicateData << ','
                << double(received) / packets << ',' << double(timely) / packets << ','
                << double(packets - received) / packets << ',';
        if (received)
        {
            summary << delaySum / received;
        }
        summary << ',';
        if (!delays.empty())
        {
            const auto index = static_cast<std::size_t>(std::ceil(0.95 * delays.size())) - 1;
            summary << delays[index];
        }
        summary << ',';
        if (timely)
        {
            summary << double(txAppBytes) / timely;
        }
        summary << '\n';
        std::cout << "\nMode: " << mode << " | generated: " << packets
                  << " | transmitted DATA + redundancy: " << txPackets
                  << "\nUnique delivered: " << received << '/' << packets
                  << "\nDelivered within " << deadlineMs << " ms: " << timely
                  << '/' << packets << "\nReconstructed with XOR: " << recovered
                  << " (timely: " << timelyRecovered << ')'
                  << "\nLink packet drops: " << error.dropped << '/' << error.arrivals
                  << "\nCSV files: " << prefix << "-summary.csv and " << prefix
                  << "-packets.csv\n";
    }

  private:
    std::vector<uint8_t> encoder;
    // Finite experiment: retain blocks until run completion for late-arrival accounting.
    // A continuous real-time application should expire these buffers periodically.
    std::map<uint32_t, Block> blocks;

    void Send(const AudioHeader& h, const std::vector<uint8_t>& bytes)
    {
        auto packet = Create<Packet>(bytes.data(), static_cast<uint32_t>(bytes.size()));
        packet->AddHeader(h);
        const uint32_t size = packet->GetSize();
        NS_ABORT_MSG_IF(sender->SendTo(packet, 0, destination) != static_cast<int>(size),
                        "UDP send failed");
        ++txPackets;
        txAppBytes += size;
    }
    void Record(const AudioHeader& h, uint16_t index,
                const std::vector<uint8_t>& bytes, bool recovered)
    {
        const uint32_t sequence = h.base + index;
        NS_ABORT_MSG_IF(bytes != MakePayload(sequence),
                        "Payload integrity check failed for sequence " << sequence);
        auto& d = deliveries[sequence];
        if (d.received)
        {
            duplicateData += !recovered;
            return;
        }
        const uint64_t generated = h.baseTimeNs + uint64_t(index) * h.intervalNs;
        NS_ABORT_MSG_IF(Simulator::Now().GetNanoSeconds() < static_cast<int64_t>(generated),
                        "Reception before generation");
        d.received = true;
        d.recovered = recovered;
        d.delayMs = (Simulator::Now().GetNanoSeconds() - generated) / 1e6;
        if (verbose)
        {
            std::cout << (recovered ? "RECOVERED" : "RECEIVED")
                      << " sequence=" << sequence << " delay_ms=" << d.delayMs
                      << " timely=" << (d.delayMs <= deadlineMs + 1e-6) << '\n';
        }
    }
};

int main(int argc, char* argv[])
{
    AudioExperiment experiment;
    double loss = 0;
    uint64_t run = 1;
    std::string dropPackets;
    std::string output = "udp-fec";
    bool pcap = false;
    CommandLine cmd(__FILE__);
    cmd.AddValue("mode", "plain, duplicate, or fec", experiment.mode);
    cmd.AddValue("packets", "Number of original source packets", experiment.packets);
    cmd.AddValue("group", "DATA packets per parity block, 2 to 32", experiment.group);
    cmd.AddValue("payload", "Fixed source payload size in bytes", experiment.payload);
    cmd.AddValue("intervalMs", "Source generation interval in ms, 1 to 1000", experiment.intervalMs);
    cmd.AddValue("deadlineMs", "Playback deadline relative to original generation", experiment.deadlineMs);
    cmd.AddValue("loss", "Independent loss probability on the final link", loss);
    cmd.AddValue("run", "Independent RNG run number", run);
    cmd.AddValue("dropPackets", "Validation only: comma-separated 1-based link arrival positions", dropPackets);
    cmd.AddValue("output", "Output filename prefix; parent directory must exist", output);
    cmd.AddValue("verbose", "Print each first delivery or recovery", experiment.verbose);
    cmd.AddValue("pcap", "Write a packet capture at the receiver", pcap);
    cmd.Parse(argc, argv);
    NS_ABORT_MSG_IF(experiment.mode != "plain" && experiment.mode != "duplicate" &&
                        experiment.mode != "fec", "Unknown mode");
    NS_ABORT_MSG_IF(!std::isfinite(loss) || loss < 0 || loss > 1, "loss must be in [0,1]");
    NS_ABORT_MSG_IF(experiment.packets == 0 || experiment.packets > 100000,
                    "packets must be between 1 and 100000");
    NS_ABORT_MSG_IF(experiment.group < 2 || experiment.group > 32, "group must be 2 to 32");
    NS_ABORT_MSG_IF(experiment.payload == 0 || experiment.payload > 1200,
                    "payload must be 1 to 1200 bytes to avoid IP fragmentation");
    NS_ABORT_MSG_IF(experiment.intervalMs == 0 || experiment.intervalMs > 1000,
                    "intervalMs must be 1 to 1000");
    NS_ABORT_MSG_IF(!std::isfinite(experiment.deadlineMs) || experiment.deadlineMs <= 0,
                    "deadlineMs must be finite and positive");
    std::set<uint64_t> positions;
    std::istringstream list(dropPackets);
    std::string entry;
    while (std::getline(list, entry, ','))
    {
        NS_ABORT_MSG_IF(entry.empty() || entry.find_first_not_of("0123456789") != std::string::npos,
                        "dropPackets requires positive integer positions");
        const auto value = std::stoull(entry);
        NS_ABORT_MSG_IF(value == 0, "dropPackets positions start at 1");
        positions.insert(value);
    }
    RngSeedManager::SetSeed(12345);
    RngSeedManager::SetRun(run);
    NodeContainer nodes;
    nodes.Create(3);
    InternetStackHelper internet;
    internet.Install(nodes);
    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", StringValue("5Mbps"));
    access.SetChannelAttribute("Delay", StringValue("2ms"));
    auto left = access.Install(NodeContainer(nodes.Get(0), nodes.Get(1)));
    PointToPointHelper uplink;
    uplink.SetDeviceAttribute("DataRate", StringValue("2Mbps"));
    uplink.SetChannelAttribute("Delay", StringValue("20ms"));
    auto right = uplink.Install(NodeContainer(nodes.Get(1), nodes.Get(2)));
    auto errors = CreateObject<ExperimentLoss>();
    errors->Configure(loss, positions);
    right.Get(1)->SetAttribute("ReceiveErrorModel", PointerValue(errors));
    Ipv4AddressHelper addresses;
    addresses.SetBase("10.1.1.0", "255.255.255.0");
    addresses.Assign(left);
    addresses.SetBase("10.1.2.0", "255.255.255.0");
    auto interfaces = addresses.Assign(right);
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    experiment.deliveries.resize(experiment.packets);
    experiment.receiver = Socket::CreateSocket(nodes.Get(2), UdpSocketFactory::GetTypeId());
    NS_ABORT_MSG_IF(experiment.receiver->Bind(InetSocketAddress(Ipv4Address::GetAny(), 9000)) != 0,
                    "Receiver bind failed");
    experiment.receiver->SetRecvCallback(MakeCallback(&AudioExperiment::Receive, &experiment));
    experiment.sender = Socket::CreateSocket(nodes.Get(0), UdpSocketFactory::GetTypeId());
    NS_ABORT_MSG_IF(experiment.sender->Bind() != 0, "Sender bind failed");
    experiment.destination = InetSocketAddress(interfaces.GetAddress(1), 9000);
    if (pcap)
    {
        uplink.EnablePcap(output, right.Get(1));
    }
    Simulator::Schedule(Seconds(1), &AudioExperiment::Generate, &experiment, 0U);
    // Leave two seconds after the last generation event for queued packets to drain.
    Simulator::Stop(Seconds(1) + MilliSeconds(uint64_t(experiment.packets - 1) *
                                           experiment.intervalMs) + Seconds(2));
    Simulator::Run();
    experiment.sender->Close();
    experiment.receiver->Close();
    experiment.WriteResults(output, loss, run, *errors);
    Simulator::Destroy();
    return 0;
}
