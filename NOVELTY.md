# Contribution and experimental design

## Defensible contribution

This is a course-project contribution: an implemented and evaluated receiver-feedback policy combining XOR group size, burst interleaving, a playback deadline and a hard cumulative parity cap. XOR coding, interleaving and adaptive FEC are established methods; do not claim to have invented them or proved a globally novel algorithm.

Working title: **Deadline-Aware Adaptive Interleaved XOR Recovery for UDP Streams Using ns-3**.

Research question: can a lightweight sender choose useful protection from delayed receiver observations, improving timely recovery under changing/burst loss without always paying duplication's traffic cost?

The user-facing simulator and dashboard are tools for demonstrating and evaluating that question. A GUI alone is not the research contribution.

## Actual network and data plane

Three ns-3 nodes: sender → router → receiver. Access link 5 Mbps / 2 ms; final link 2 Mbps / 20 ms. IPv4 routing is populated normally. UDP source port 9001 communicates with receiver port 9000; feedback travels back through the same topology. There is no direct simulator-state channel into the controller.

A deterministic 160-byte synthetic payload is generated every 20 ms by default. It represents audio-like traffic, not encoded/playable audio. All methods share the same network, payload and source interval.

For group size k, one XOR parity packet combines k DATA payloads. A decoder can recover exactly one missing payload when parity and the other k−1 payloads arrive. It verifies the recovered bytes against the deterministic source pattern; that pattern is a validation assertion, not a recovery oracle.

At depth d=2, alternate packets enter two separate XOR groups. For k=4:
- group A: source sequences 0, 2, 4, 6;
- group B: source sequences 1, 3, 5, 7.

Each group's parity is sent immediately after its final original. Interleaving separates some consecutive losses but increases waiting time. A short final group carries its actual count in the serialized header. The implementation handles that group.

Serialized 45-byte headers communicate kind, wire ID, sequence, block/base, k, depth, group index/count, generation time and source interval. A separate trace tag correlates network callbacks only; decoding uses bytes carried in the packet.

## Receiver measurements

Every 500 ms, the receiver reports a new range of originals whose configured deadlines have expired. It measures:
- raw original DATA delivery by deadline, before considering reconstructed packets;
- longest missing run inside that report;
- 95th percentile of observed raw DATA delay.

A 24-byte report plus the 45-byte header is sent as a real UDP packet. Feedback loss can be configured independently. All six methods send the same scheduled receiver reports, including fixed baselines, so comparison accounts for that measurement cost.

The receiver assumes the stream start, interval and total source count are configured and known. No stream-start handshake is modeled. Longest-gap detection resets at report boundaries. Missing feedback produces no update; there is no ACK/retransmission or feedback timeout fallback. Initial planning uses a 5% loss prior and 25 ms delay estimate, explicitly the same for both adaptive variants.

## Policy

Loss estimate p-hat is smoothed by EWMA with alpha=0.5. Candidate group sizes are 8, 4 and 2; k=1 means send DATA without parity. Full adaptation prefers depth 2 when a report contains a missing run of at least two. If no depth-2 repair fits, it tries depth 1.

For an independent-loss planning model, the estimated eventual delivery probability is:

    R_hat(k) = 1 − p_hat + p_hat × (1 − p_hat)^k

This counts direct success or recovery from one original loss with the other k−1 originals and parity received. It ignores burst correlation. It is a planning estimate, not a guarantee or a fitted predictor of all observed results.

Full adaptation rejects a candidate unless:

    1/k <= B
    (k−1) × d × I + L_hat95 + 5 ms <= D

B is the maximum nominal parity/source fraction, I the source interval and D the deadline. The 5 ms allowance is fixed. The second constraint estimates repair waiting time plus measured path delay. A p95 estimate cannot guarantee every packet meets its deadline.

Within the preferred feasible depth, the controller picks the cheapest configuration predicted to meet the reliability target (default 0.97). If none meets it, it picks the strongest permitted protection and logs that the target is infeasible. If no repair fits, it sends no parity.

Stronger protection or deeper interleaving can start after one report; lowering protection requires two consecutive reports proposing the same setting. Deadline-unsafe existing protection can be replaced immediately. Accepted changes apply at the next frame boundary; the in-progress frame is completed. The event trace records the configuration actually applied, separate from the feedback-time decision.

A second guard enforces actual cumulative traffic:

    txParity + 1 <= B × originalsGenerated

A parity packet that would violate that guard is skipped and logged. This also handles partial groups. The cap is on application parity/source traffic; it excludes feedback and network headers. Feedback is counted separately in total application cost. Reconstructed packets consume receiver work, not link transmissions.

## Ablations

1. Plain UDP: no extra DATA or parity.
2. Duplication: each DATA sent twice, 100% extra forward packets.
3. Fixed XOR: k=4, depth 1, 25% nominal parity.
4. Fixed interleaved XOR: k=4, depth 2, 25% nominal parity.
5. Loss-only adaptive: same loss estimator, budget, reliability predictor and hysteresis; depth 1, without the deadline feasibility filter.
6. Full adaptive: deadline filter plus burst-triggered interleaving.

The full-versus-loss-only comparison evaluates the combined extension; fixed versus fixed-interleaved isolates interleaving. A future finer ablation could add deadline-aware/non-interleaved adaptation to isolate each controller feature separately. Do not claim the present six methods fully isolate every feature.

## Loss experiments

- steady: independent packet loss at p.
- burst: two-state Gilbert loss, zero losses in good state and all arrivals lost in bad state. Bad→good probability is 1/L; good→bad is p/[L(1−p)]. L=3 by default. Initial state is sampled at stationary p.
- changing: four equal source-duration quarters: clean (p=0.005), independent loss at configured p, burst loss at configured p, clean (p=0.005).

The model evolves on packet arrivals, including parity and extra copies. Methods therefore do not experience identical per-original loss masks under a shared RNG run. State time spans also depend on sending rate. Report configured AND observed forward loss; avoid claiming pathwise paired packet-loss comparisons. This is a deliberate simple channel model, not a measured wireless trace. Channel phase changes may be offset at the receiver by propagation time.

The provided 180-run study uses six methods × three scenarios × ten RNG runs, 1,000 originals, p=0.1, D=150 ms and B=0.5. Preserve all outcomes. For final submission, generate the same study in Ubuntu and identify its source hash/platform.

Recommended extensions for report experiments: repeat with --deadline 60 and --deadline 100, each into a new study folder, to test deadline sensitivity. The dashboard's sidebar also allows budget and reverse feedback-loss sensitivity runs. One interactive run illustrates behavior; ten independent runs support a mean/interval.

## Metrics and statistics

- Timely delivery = originals first delivered by deadline / originals sent.
- Eventual delivery = unique originals eventually delivered / originals sent.
- Recovery count = originals first delivered by XOR reconstruction.
- Residual loss = originals never delivered / originals sent.
- Mean/p95 delay = delay of delivered originals; this conditions on delivery.
- Extra forward traffic = (DATA transmissions + parity − originals) / originals.
- Application bytes per timely original = (all forward app bytes + all feedback app bytes) / timely originals.

A never-delivered packet has no delay observation. Do not silently assign zero delay. Compare delay alongside delivery to avoid rewarding methods that lose difficult packets. Cost with zero timely deliveries is undefined.

Confidence intervals use the Student-t interval across independent run-level metrics, not across individual packets. Ten runs use t(9,0.975)=2.262157. The dashboard suppresses CIs for a single run and unsupported sample counts rather than inventing precision. Displayed intervals are pointwise, not familywise or a formal superiority test. Adaptive results need not dominate fixed methods.

The 250-run historical baseline has a different app header and no feedback accounting. It remains useful background; do not pool it with new lab cost estimates.

## Mapping into the required report

- Abstract: problem, implemented policy, experiment matrix and measured conclusions.
- Objectives: recover timely packets, bound parity, demonstrate feedback/animation, compare ablations.
- Introduction: UDP timeliness versus reliability, burst loss and repair-delay tradeoff.
- Literature review: at least 12 actual refereed papers as required; cover XOR/FEC, streaming codes, interleaving, adaptive feedback and deadline-aware recovery. Verify each citation. The package is not a completed literature review.
- Gap/problem: simple fixed protection ignores channel changes and repair usefulness; frame this as the project's design/evaluation question.
- Methodology: topology, sockets/header, encoder/decoder, report format, equations, controller flow, channel model and assumptions.
- Implementation: explain src/udp-fec-lab.cc and fec_policy.h, then the Python execution and presentation layers.
- Results: deterministic correctness examples plus complete repeated-run graphs, traffic tradeoffs and interval interpretation.
- Conclusion: bounded claims supported by results, limitations and future finer ablation / real trace / larger topology.
- References: verified literature, official ns-3/NetAnim/Streamlit documentation and version information.

Useful starting related work, not a claim of novelty: https://www.eecg.utoronto.ca/~salma/papers/fong-acmmm19.pdf
