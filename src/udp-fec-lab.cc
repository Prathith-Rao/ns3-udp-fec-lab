// Adaptive interleaved UDP FEC lab for ns-3.45. Synthetic payloads, not an audio codec.
#include "fec_policy.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/netanim-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
using namespace ns3;
enum Kind : uint8_t
{
    DATA = 0,
    PARITY = 1,
    FEEDBACK = 2
};
const char *KindName(uint8_t k) { return k == DATA ? "DATA" : k == PARITY ? "PARITY" : "FEEDBACK"; }
class LabHeader : public Header
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId t =
            TypeId("ns3::FecLabHeader").SetParent<Header>().AddConstructor<LabHeader>();
        return t;
    }
    TypeId GetInstanceTypeId() const override { return GetTypeId(); }
    uint32_t GetSerializedSize() const override { return 45; }
    void Serialize(Buffer::Iterator i) const override
    {
        i.WriteHtonU32(0x46454332);
        i.WriteU8(kind);
        i.WriteHtonU64(wire);
        i.WriteHtonU32(sequence);
        i.WriteHtonU32(block);
        i.WriteHtonU32(base);
        i.WriteHtonU16(k);
        i.WriteHtonU16(depth);
        i.WriteHtonU16(index);
        i.WriteHtonU16(count);
        i.WriteHtonU64(baseTime);
        i.WriteHtonU32(interval);
    }
    uint32_t Deserialize(Buffer::Iterator i) override
    {
        NS_ABORT_MSG_IF(i.ReadNtohU32() != 0x46454332, "Invalid header");
        kind = i.ReadU8();
        wire = i.ReadNtohU64();
        sequence = i.ReadNtohU32();
        block = i.ReadNtohU32();
        base = i.ReadNtohU32();
        k = i.ReadNtohU16();
        depth = i.ReadNtohU16();
        index = i.ReadNtohU16();
        count = i.ReadNtohU16();
        baseTime = i.ReadNtohU64();
        interval = i.ReadNtohU32();
        return GetSerializedSize();
    }
    void Print(std::ostream &os) const override
    {
        os << KindName(kind) << " seq=" << sequence << " block=" << block << " k=" << k
           << " d=" << depth;
    }
    uint8_t kind{DATA};
    uint64_t wire{0}, baseTime{0};
    uint32_t sequence{0}, block{0}, base{0}, interval{0};
    uint16_t k{1}, depth{1}, index{0}, count{1};
};
// This tag correlates trace events; decoding uses serialized headers, not tags.
class LabTag : public Tag
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId t = TypeId("ns3::FecLabTag").SetParent<Tag>().AddConstructor<LabTag>();
        return t;
    }
    TypeId GetInstanceTypeId() const override { return GetTypeId(); }
    uint32_t GetSerializedSize() const override { return 21; }
    void Serialize(TagBuffer b) const override
    {
        b.WriteU64(wire);
        b.WriteU32(sequence);
        b.WriteU32(block);
        b.WriteU8(kind);
        b.WriteU16(k);
        b.WriteU16(depth);
    }
    void Deserialize(TagBuffer b) override
    {
        wire = b.ReadU64();
        sequence = b.ReadU32();
        block = b.ReadU32();
        kind = b.ReadU8();
        k = b.ReadU16();
        depth = b.ReadU16();
    }
    void Print(std::ostream &os) const override { os << wire; }
    uint64_t wire{0};
    uint32_t sequence{0}, block{0};
    uint8_t kind{0};
    uint16_t k{1}, depth{1};
};
std::ofstream eventFile;
void LogEvent(const std::string &name, unsigned node, const LabTag &t,
              const std::string &detail = "")
{
    if (eventFile.is_open())
        eventFile << Simulator::Now().GetSeconds() << ',' << name << ',' << node << ',' << t.wire
                  << ',' << KindName(t.kind) << ',' << t.sequence << ',' << t.block << ',' << t.k
                  << ',' << t.depth << ',' << detail << '\n';
}
void NetworkTx(unsigned node, Ptr<const Packet> p, Ptr<Ipv4>, uint32_t)
{
    LabTag t;
    if (p->PeekPacketTag(t))
        LogEvent("NET_TX", node, t);
}
class LabLoss : public ErrorModel
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId t =
            TypeId("ns3::FecLabLoss").SetParent<ErrorModel>().AddConstructor<LabLoss>();
        return t;
    }
    LabLoss() : rng(CreateObject<UniformRandomVariable>()) { rng->SetStream(3); }
    std::string scenario{"changing"};
    double loss{.1}, duration{8}, meanBurst{3};
    uint64_t arrivals{0}, dropped{0};
    std::set<uint64_t> forced;

  private:
    bool bad{false};
    int previousPhase{-1};
    Ptr<UniformRandomVariable> rng;
    bool DoCorrupt(Ptr<Packet> p) override
    {
        ++arrivals;
        double probability = loss;
        bool clustered = scenario == "burst";
        int phase = 0;
        if (scenario == "changing")
        {
            double elapsed = std::max(0.0, Simulator::Now().GetSeconds() - 1);
            phase = std::min(3, int(elapsed / std::max(.001, duration / 4)));
            probability = (phase == 0 || phase == 3) ? .005 : loss;
            clustered = phase == 2;
        }
        if (phase != previousPhase)
        {
            bad = rng->GetValue() < probability;
            previousPhase = phase;
        }
        bool drop;
        if (!clustered)
            drop = rng->GetValue() < probability;
        else
        {
            drop = bad;
            if (bad)
            {
                if (rng->GetValue() < 1.0 / meanBurst)
                    bad = false;
            }
            else if (rng->GetValue() < probability / (meanBurst * (1 - probability)))
                bad = true;
        }
        drop = drop || forced.count(arrivals);
        if (drop)
        {
            ++dropped;
            LabTag t;
            if (p->PeekPacketTag(t))
                LogEvent("DROP", 2, t, "final_link");
        }
        return drop;
    }
    void DoReset() override
    {
        arrivals = dropped = 0;
        bad = false;
        previousPhase = -1;
    }
};
struct Delivery
{
    bool received{false}, recovered{false};
    double delay{0};
};
struct RxBlock
{
    LabHeader h;
    std::map<unsigned, std::vector<uint8_t>> data;
    std::vector<uint8_t> parity;
};
struct TxBlock
{
    uint32_t id{0}, base{0};
    unsigned count{1};
    std::vector<uint8_t> parity;
};
class Lab
{
  public:
    std::string mode{"adaptive"}, scenario{"changing"}, output{"results/lab/demo"};
    uint32_t packets{400}, payload{160}, intervalMs{20}, fixedK{4}, fixedDepth{1};
    uint64_t run{1};
    double deadlineMs{150}, budget{.5}, target{.97}, loss{.1};
    bool trace{true}, animation{true};
    Ptr<Socket> sender, receiver;
    Address destination, source;
    Ptr<LabLoss> errors;
    std::vector<Delivery> deliveries;
    std::vector<double> rawArrival;
    std::unique_ptr<AnimationInterface> animator;
    std::ofstream controls;
    uint64_t txData{0}, txParity{0}, txFeedback{0}, txDataBytes{0}, txFeedbackBytes{0},
        duplicateCount{0}, feedbackReceived{0}, changes{0};
    void Initialise()
    {
        deliveries.resize(packets);
        rawArrival.assign(packets, -1);
        if (mode == "plain" || mode == "duplicate")
        {
            chosenK = 1;
            chosenDepth = 1;
        }
        else
        {
            chosenK = fixedK;
            chosenDepth = fixedDepth;
        }
        if (mode == "adaptive" || mode == "loss-adaptive")
        {
            auto c = fecproject::Choose(.05, 1, 25, intervalMs, deadlineMs, budget, target,
                                        mode == "adaptive");
            chosenK = c.k;
            chosenDepth = c.depth;
        }
        controls.open(output + "-control.csv");
        NS_ABORT_MSG_IF(!controls, "Cannot create results directory");
        controls << "time_s,loss_estimate,max_burst,delay95_ms,k,depth,candidate_k,candidate_depth,"
                    "predicted_delivery,estimated_repair_ms,target_estimated_met,action,reason\n"
                 << std::fixed << std::setprecision(6);
    }
    uint64_t GenNs(uint32_t s) const
    {
        return 1000000000ULL + uint64_t(s) * intervalMs * 1000000ULL;
    }
    std::vector<uint8_t> Payload(uint32_t s) const
    {
        std::mt19937 rng(0x91a2b3c4U ^ s);
        std::vector<uint8_t> v(payload);
        for (auto &b : v)
            b = uint8_t(rng() & 255U);
        return v;
    }
    void Generate(uint32_t seq)
    {
        if (seq == nextFrame)
        {
            frameK = chosenK;
            frameDepth = chosenDepth;
            frameStart = seq;
            nextFrame = std::min(packets, seq + frameK * frameDepth);
            encoders.clear();
            for (unsigned col = 0; col < frameDepth && seq + col < packets; ++col)
            {
                TxBlock b;
                b.id = nextBlock++;
                b.base = seq + col;
                b.count = std::min(frameK, 1U + (packets - 1 - b.base) / frameDepth);
                b.parity.assign(payload, 0);
                encoders.push_back(std::move(b));
            }
            LabTag t;
            t.k = frameK;
            t.depth = frameDepth;
            t.sequence = seq;
            LogEvent("FRAME", 0, t, "configuration_applied");
        }
        unsigned off = seq - frameStart, col = off % frameDepth, index = off / frameDepth;
        auto &b = encoders[col];
        LabHeader h;
        h.sequence = seq;
        h.block = b.id;
        h.base = b.base;
        h.k = frameK;
        h.depth = frameDepth;
        h.index = index;
        h.count = b.count;
        h.baseTime = GenNs(b.base);
        h.interval = intervalMs * 1000000U;
        auto data = Payload(seq);
        Send(sender, destination, h, data);
        if (mode == "duplicate")
            Send(sender, destination, h, data);
        if (frameK > 1)
        {
            for (unsigned j = 0; j < payload; ++j)
                b.parity[j] ^= data[j];
            if (index + 1 == b.count)
            {
                h.kind = PARITY;
                h.sequence = b.base;
                h.index = 0;
                if ((mode != "adaptive" && mode != "loss-adaptive") ||
                    double(txParity + 1) <= budget * double(seq + 1) + 1e-9)
                    Send(sender, destination, h, b.parity);
                else
                {
                    auto t = ToTag(h);
                    LogEvent("PARITY_SKIPPED", 0, t, "budget_cap");
                }
            }
        }
        if (seq + 1 < packets)
            Simulator::Schedule(MilliSeconds(intervalMs), &Lab::Generate, this, seq + 1);
    }
    void Receive(Ptr<Socket> socket)
    {
        Address from;
        while (auto p = socket->RecvFrom(from))
        {
            LabHeader h;
            NS_ABORT_MSG_IF(p->GetSize() < h.GetSerializedSize(), "Short packet");
            p->RemoveHeader(h);
            NS_ABORT_MSG_IF(h.kind > PARITY || h.count == 0 || h.count > 8 || h.depth < 1 ||
                                h.depth > 2 || h.index >= h.count ||
                                uint64_t(h.base) + (h.count - 1) * h.depth >= packets ||
                                p->GetSize() != payload,
                            "Invalid data header");
            LogEvent("RX", 2, ToTag(h));
            std::vector<uint8_t> bytes(payload);
            p->CopyData(bytes.data(), payload);
            if (h.kind == DATA)
            {
                NS_ABORT_MSG_IF(h.sequence >= packets || h.sequence != h.base + h.index * h.depth,
                                "Invalid sequence");
                if (rawArrival[h.sequence] < 0)
                    rawArrival[h.sequence] = Simulator::Now().GetSeconds();
                Record(h, h.index, bytes, false);
            }
            if (h.k == 1)
                continue;
            auto &block = decoder[h.block];
            block.h = h;
            if (h.kind == PARITY)
                block.parity = bytes;
            else
                block.data.emplace(h.index, bytes);
            if (!block.parity.empty() && block.data.size() + 1 == h.count)
            {
                unsigned missing = 0;
                while (block.data.count(missing))
                    ++missing;
                auto recovered = block.parity;
                for (const auto &part : block.data)
                    for (unsigned j = 0; j < payload; ++j)
                        recovered[j] ^= part.second[j];
                Record(block.h, missing, recovered, true);
                block.data.emplace(missing, std::move(recovered));
            }
        }
    }
    void Feedback()
    {
        double now = Simulator::Now().GetSeconds(),
               eligible = (now - deadlineMs / 1000.0 - 1) * 1000 / intervalMs;
        int end = std::min(int(packets) - 1, int(std::floor(eligible + 1e-8)));
        if (end >= int(nextFeedbackSequence))
        {
            unsigned received = 0, longest = 0, consecutive = 0;
            std::vector<double> delays;
            for (unsigned seq = nextFeedbackSequence; seq <= unsigned(end); ++seq)
            {
                double generated = GenNs(seq) / 1e9;
                bool arrived = rawArrival[seq] >= 0 &&
                               rawArrival[seq] <= generated + deadlineMs / 1000.0 + 1e-9;
                if (arrived)
                {
                    ++received;
                    consecutive = 0;
                    delays.push_back(1000 * (rawArrival[seq] - generated));
                }
                else
                    longest = std::max(longest, ++consecutive);
            }
            std::sort(delays.begin(), delays.end());
            double d95 = delays.empty() ? lastDelay
                                        : delays[std::size_t(std::ceil(.95 * delays.size())) - 1];
            std::vector<uint8_t> bytes;
            for (uint32_t v :
                 {nextFeedbackSequence, uint32_t(end), uint32_t(end) - nextFeedbackSequence + 1,
                  received, longest, uint32_t(std::ceil(d95 * 1000))})
                for (int shift = 24; shift >= 0; shift -= 8)
                    bytes.push_back(uint8_t(v >> shift));
            LabHeader h;
            h.kind = FEEDBACK;
            h.sequence = nextFeedbackSequence;
            h.baseTime = Simulator::Now().GetNanoSeconds();
            Send(receiver, source, h, bytes);
            nextFeedbackSequence = unsigned(end) + 1;
        }
        if (nextFeedbackSequence < packets)
            Simulator::Schedule(MilliSeconds(500), &Lab::Feedback, this);
    }
    void ReceiveFeedback(Ptr<Socket> socket)
    {
        Address from;
        while (auto p = socket->RecvFrom(from))
        {
            LabHeader h;
            p->RemoveHeader(h);
            NS_ABORT_MSG_IF(h.kind != FEEDBACK || p->GetSize() != 24, "Invalid feedback");
            LogEvent("RX", 0, ToTag(h));
            ++feedbackReceived;
            std::vector<uint8_t> bytes(24);
            p->CopyData(bytes.data(), 24);
            uint32_t v[6]{};
            for (unsigned i = 0; i < 6; ++i)
                for (unsigned j = 0; j < 4; ++j)
                    v[i] = (v[i] << 8) | bytes[4 * i + j];
            NS_ABORT_MSG_IF(v[2] == 0 || v[3] > v[2], "Invalid report counts");
            double sample = 1.0 - double(v[3]) / v[2];
            estimatedLoss = haveFeedback ? .5 * estimatedLoss + .5 * sample : sample;
            haveFeedback = true;
            lastDelay = v[5] / 1000.0;
            if (mode != "adaptive" && mode != "loss-adaptive")
                continue;
            auto c = fecproject::Choose(estimatedLoss, v[4], lastDelay, intervalMs, deadlineMs,
                                        budget, target, mode == "adaptive");
            bool different = c.k != chosenK || c.depth != chosenDepth;
            std::string action = "keep";
            if (different)
            {
                double oldCost = chosenK == 1 ? 0 : 1.0 / chosenK,
                       newCost = c.k == 1 ? 0 : 1.0 / c.k;
                if (c.k == pendingK && c.depth == pendingDepth)
                    ++pendingReports;
                else
                {
                    pendingK = c.k;
                    pendingDepth = c.depth;
                    pendingReports = 1;
                }
                bool unsafe = (chosenK - 1) * chosenDepth * intervalMs + lastDelay + 5 > deadlineMs;
                if (newCost > oldCost || c.depth > chosenDepth || pendingReports >= 2 ||
                    (mode == "adaptive" && unsafe))
                {
                    chosenK = c.k;
                    chosenDepth = c.depth;
                    ++changes;
                    action = "switch_next_frame";
                    pendingReports = 0;
                    if (animator)
                        animator->UpdateNodeDescription(0, "Sender k=" + std::to_string(chosenK) +
                                                               " d=" + std::to_string(chosenDepth));
                }
                else
                    action = "hold_for_second_report";
            }
            else
                pendingReports = 0;
            controls << Simulator::Now().GetSeconds() << ',' << estimatedLoss << ',' << v[4] << ','
                     << lastDelay << ',' << chosenK << ',' << chosenDepth << ',' << c.k << ','
                     << c.depth << ',' << c.predicted << ',' << c.repairMs << ',' << c.targetMet
                     << ',' << action << ',' << c.reason << '\n';
            auto t = ToTag(h);
            t.k = chosenK;
            t.depth = chosenDepth;
            LogEvent("CONTROL", 0, t, action);
        }
    }
    void Save()
    {
        unsigned delivered = 0, timely = 0, recovered = 0, timelyRecovered = 0;
        double sum = 0;
        std::vector<double> delays;
        std::ofstream pf(output + "-packets.csv");
        pf << "sequence,generated_s,delivered,recovered,delay_ms,timely\n"
           << std::fixed << std::setprecision(6);
        for (unsigned seq = 0; seq < packets; ++seq)
        {
            const auto &d = deliveries[seq];
            bool onTime = d.received && d.delay <= deadlineMs + 1e-6;
            delivered += d.received;
            timely += onTime;
            recovered += d.recovered;
            timelyRecovered += d.recovered && onTime;
            if (d.received)
            {
                sum += d.delay;
                delays.push_back(d.delay);
            }
            pf << seq << ',' << GenNs(seq) / 1e9 << ',' << d.received << ',' << d.recovered << ',';
            if (d.received)
                pf << d.delay;
            pf << ',' << onTime << '\n';
        }
        std::sort(delays.begin(), delays.end());
        std::ofstream s(output + "-summary.json");
        NS_ABORT_MSG_IF(!s || !pf, "Cannot save results");
        s << std::fixed << std::setprecision(8)
          << "{\n\"schema\":2,\"engine\":\"ns-3.45\",\"mode\":\"" << mode << "\",\"scenario\":\""
          << scenario << "\",\"run\":" << run << ",\"packets\":" << packets
          << ",\"payload_bytes\":" << payload << ",\"interval_ms\":" << intervalMs
          << ",\"deadline_ms\":" << deadlineMs << ",\"loss_setting\":" << loss
          << ",\"parity_budget\":" << budget << ",\"target\":" << target
          << ",\"delivered\":" << delivered << ",\"timely\":" << timely
          << ",\"recovered\":" << recovered << ",\"timely_recovered\":" << timelyRecovered
          << ",\"tx_data\":" << txData << ",\"tx_parity\":" << txParity
          << ",\"tx_feedback\":" << txFeedback << ",\"feedback_received\":" << feedbackReceived
          << ",\"controller_changes\":" << changes << ",\"tx_forward_app_bytes\":" << txDataBytes
          << ",\"tx_feedback_app_bytes\":" << txFeedbackBytes
          << ",\"link_arrivals\":" << errors->arrivals << ",\"link_drops\":" << errors->dropped
          << ",\"duplicate_data\":" << duplicateCount << ",\"mean_delay_ms\":";
        if (delivered)
            s << sum / delivered;
        else
            s << "null";
        s << ",\"p95_delay_ms\":";
        if (delivered)
            s << delays[std::size_t(std::ceil(.95 * delays.size())) - 1];
        else
            s << "null";
        s << ",\"animation\":" << (animation ? "true" : "false") << "\n}\n";
        std::cout << mode << ": timely=" << timely << '/' << packets << " recovered=" << recovered
                  << " parity=" << txParity << " feedback=" << txFeedback << " changes=" << changes
                  << "\nResults: " << output << "-summary.json\n";
    }

  private:
    uint64_t nextWire{1};
    unsigned nextBlock{0}, frameStart{0}, nextFrame{0}, frameK{4}, frameDepth{1}, chosenK{4},
        chosenDepth{1}, pendingK{0}, pendingDepth{0}, pendingReports{0}, nextFeedbackSequence{0};
    double estimatedLoss{0}, lastDelay{25};
    bool haveFeedback{false};
    std::vector<TxBlock> encoders;
    std::map<uint32_t, RxBlock> decoder;
    LabTag ToTag(const LabHeader &h) const
    {
        LabTag t;
        t.wire = h.wire;
        t.sequence = h.sequence;
        t.block = h.block;
        t.kind = h.kind;
        t.k = h.k;
        t.depth = h.depth;
        return t;
    }
    void Send(Ptr<Socket> socket, const Address &address, LabHeader h,
              const std::vector<uint8_t> &bytes)
    {
        h.wire = nextWire++;
        auto p = Create<Packet>(bytes.data(), uint32_t(bytes.size()));
        p->AddHeader(h);
        p->AddPacketTag(ToTag(h));
        NS_ABORT_MSG_IF(socket->SendTo(p, 0, address) != int(p->GetSize()), "Send failed");
        if (h.kind == FEEDBACK)
        {
            ++txFeedback;
            txFeedbackBytes += p->GetSize();
        }
        else
        {
            txDataBytes += p->GetSize();
            if (h.kind == DATA)
                ++txData;
            else
                ++txParity;
        }
    }
    void Record(const LabHeader &h, unsigned index, const std::vector<uint8_t> &bytes,
                bool recovered)
    {
        unsigned seq = h.base + index * h.depth;
        NS_ABORT_MSG_IF(seq >= packets || bytes != Payload(seq), "Payload integrity failure");
        auto &d = deliveries[seq];
        if (d.received)
        {
            duplicateCount += !recovered;
            return;
        }
        d.received = true;
        d.recovered = recovered;
        uint64_t generated = h.baseTime + uint64_t(index) * h.depth * h.interval;
        d.delay = (Simulator::Now().GetNanoSeconds() - generated) / 1e6;
        if (recovered)
        {
            auto t = ToTag(h);
            t.sequence = seq;
            LogEvent("RECOVER", 2, t, d.delay <= deadlineMs + 1e-6 ? "timely" : "late");
        }
    }
};
int main(int argc, char **argv)
{
    Lab lab;
    double burst = 3, feedbackLoss = 0;
    std::string dropPackets;
    CommandLine cmd(__FILE__);
    cmd.AddValue("mode", "plain duplicate fixed interleaved loss-adaptive adaptive", lab.mode);
    cmd.AddValue("scenario", "steady burst changing", lab.scenario);
    cmd.AddValue("packets", "Source packets", lab.packets);
    cmd.AddValue("intervalMs", "Source interval", lab.intervalMs);
    cmd.AddValue("deadlineMs", "Playback deadline", lab.deadlineMs);
    cmd.AddValue("group", "Initial/fixed group 2 4 8", lab.fixedK);
    cmd.AddValue("depth", "Interleaving depth", lab.fixedDepth);
    cmd.AddValue("loss", "Loss in impaired phases", lab.loss);
    cmd.AddValue("burstLength", "Mean loss run length", burst);
    cmd.AddValue("budget", "Parity/DATA budget", lab.budget);
    cmd.AddValue("target", "Planning reliability target", lab.target);
    cmd.AddValue("run", "RNG run", lab.run);
    cmd.AddValue("feedbackLoss", "Reverse link loss", feedbackLoss);
    cmd.AddValue("dropPackets", "Forced final-link arrivals", dropPackets);
    cmd.AddValue("output", "Output prefix", lab.output);
    cmd.AddValue("trace", "Event trace", lab.trace);
    cmd.AddValue("animation", "NetAnim XML", lab.animation);
    cmd.Parse(argc, argv);
    const std::set<std::string> modes{"plain",       "duplicate",     "fixed",
                                      "interleaved", "loss-adaptive", "adaptive"};
    NS_ABORT_MSG_IF(!modes.count(lab.mode), "Unknown mode");
    NS_ABORT_MSG_IF(lab.scenario != "steady" && lab.scenario != "burst" &&
                        lab.scenario != "changing",
                    "Unknown scenario");
    NS_ABORT_MSG_IF(lab.packets < 1 || lab.packets > 10000 || lab.intervalMs < 1 ||
                        lab.intervalMs > 100,
                    "Invalid source settings");
    NS_ABORT_MSG_IF(!std::isfinite(lab.loss) || lab.loss < 0 || lab.loss > .4 ||
                        !std::isfinite(burst) || burst < 1 || burst > 20,
                    "Invalid loss settings");
    NS_ABORT_MSG_IF(!std::isfinite(lab.deadlineMs) || lab.deadlineMs < 1 || lab.deadlineMs > 1000 ||
                        !std::isfinite(lab.budget) || lab.budget < 0 || lab.budget > 1 ||
                        !std::isfinite(lab.target) || lab.target <= 0 || lab.target >= 1 ||
                        !std::isfinite(feedbackLoss) || feedbackLoss < 0 || feedbackLoss > 1,
                    "Invalid controller parameters");
    NS_ABORT_MSG_IF(lab.fixedK != 2 && lab.fixedK != 4 && lab.fixedK != 8,
                    "group must be 2 4 or 8");
    NS_ABORT_MSG_IF(lab.fixedDepth != 1 && lab.fixedDepth != 2, "depth must be 1 or 2");
    if (lab.mode == "interleaved")
        lab.fixedDepth = 2;
    if (lab.mode == "fixed" || lab.mode == "loss-adaptive")
        lab.fixedDepth = 1;
    RngSeedManager::SetSeed(12345);
    RngSeedManager::SetRun(lab.run);
    lab.Initialise();
    if (lab.trace)
    {
        eventFile.open(lab.output + "-events.csv");
        NS_ABORT_MSG_IF(!eventFile, "Cannot create trace");
        eventFile << "time_s,event,node,wire_id,kind,sequence,block,k,depth,detail\n"
                  << std::fixed << std::setprecision(9);
    }
    NodeContainer nodes;
    nodes.Create(3);
    InternetStackHelper stack;
    stack.Install(nodes);
    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", StringValue("5Mbps"));
    access.SetChannelAttribute("Delay", StringValue("2ms"));
    auto left = access.Install(NodeContainer(nodes.Get(0), nodes.Get(1)));
    PointToPointHelper core;
    core.SetDeviceAttribute("DataRate", StringValue("2Mbps"));
    core.SetChannelAttribute("Delay", StringValue("20ms"));
    auto right = core.Install(NodeContainer(nodes.Get(1), nodes.Get(2)));
    lab.errors = CreateObject<LabLoss>();
    lab.errors->scenario = lab.scenario;
    lab.errors->loss = lab.loss;
    lab.errors->meanBurst = burst;
    lab.errors->duration = double(lab.packets) * lab.intervalMs / 1000;
    std::stringstream forced(dropPackets);
    std::string part;
    while (std::getline(forced, part, ','))
    {
        NS_ABORT_MSG_IF(part.empty() || part.find_first_not_of("0123456789") != std::string::npos,
                        "Invalid drop list");
        auto value = std::stoull(part);
        NS_ABORT_MSG_IF(value == 0, "Drop positions start at 1");
        lab.errors->forced.insert(value);
    }
    right.Get(1)->SetAttribute("ReceiveErrorModel", PointerValue(lab.errors));
    auto reverse = CreateObject<RateErrorModel>();
    reverse->SetUnit(RateErrorModel::ERROR_UNIT_PACKET);
    reverse->SetRate(feedbackLoss);
    auto rr = CreateObject<UniformRandomVariable>();
    rr->SetStream(9);
    reverse->SetRandomVariable(rr);
    right.Get(0)->SetAttribute("ReceiveErrorModel", PointerValue(reverse));
    Ipv4AddressHelper ip;
    ip.SetBase("10.1.1.0", "255.255.255.0");
    auto a = ip.Assign(left);
    ip.SetBase("10.1.2.0", "255.255.255.0");
    auto b = ip.Assign(right);
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    lab.receiver = Socket::CreateSocket(nodes.Get(2), UdpSocketFactory::GetTypeId());
    lab.sender = Socket::CreateSocket(nodes.Get(0), UdpSocketFactory::GetTypeId());
    NS_ABORT_MSG_IF(lab.receiver->Bind(InetSocketAddress(Ipv4Address::GetAny(), 9000)) != 0 ||
                        lab.sender->Bind(InetSocketAddress(Ipv4Address::GetAny(), 9001)) != 0,
                    "Bind failed");
    lab.receiver->SetRecvCallback(MakeCallback(&Lab::Receive, &lab));
    lab.sender->SetRecvCallback(MakeCallback(&Lab::ReceiveFeedback, &lab));
    lab.destination = InetSocketAddress(b.GetAddress(1), 9000);
    lab.source = InetSocketAddress(a.GetAddress(0), 9001);
    for (unsigned n = 0; n < 3; ++n)
        nodes.Get(n)->GetObject<Ipv4>()->TraceConnectWithoutContext(
            "Tx", MakeBoundCallback(&NetworkTx, n));
    if (lab.animation)
    {
        AnimationInterface::SetConstantPosition(nodes.Get(0), 10, 30);
        AnimationInterface::SetConstantPosition(nodes.Get(1), 50, 30);
        AnimationInterface::SetConstantPosition(nodes.Get(2), 90, 30);
        lab.animator = std::make_unique<AnimationInterface>(lab.output + "-netanim.xml");
        lab.animator->EnablePacketMetadata(true);
        lab.animator->UpdateNodeDescription(0, "Audio sender");
        lab.animator->UpdateNodeDescription(1, "Router");
        lab.animator->UpdateNodeDescription(2, "Receiver and feedback");
        lab.animator->UpdateNodeColor(0, 30, 110, 210);
        lab.animator->UpdateNodeColor(1, 220, 160, 30);
        lab.animator->UpdateNodeColor(2, 35, 150, 95);
    }
    Simulator::Schedule(Seconds(1), &Lab::Generate, &lab, 0U);
    // Identical receiver reports are sent in every mode; their measured traffic is counted.
    Simulator::Schedule(Seconds(1.5), &Lab::Feedback, &lab);
    Simulator::Stop(
        Seconds(1 + double(lab.packets) * lab.intervalMs / 1000 + 2 + lab.deadlineMs / 1000));
    Simulator::Run();
    lab.Save();
    lab.sender->Close();
    lab.receiver->Close();
    lab.animator.reset();
    lab.controls.close();
    if (eventFile.is_open())
        eventFile.close();
    Simulator::Destroy();
    return 0;
}
