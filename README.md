# ns-3 UDP FEC Lab

**Project title:** Deadline-Aware Adaptive Interleaved XOR Recovery for UDP Streams Using ns-3.

A Network Programming AAT project by Prathith Suresh Rao, S Nagashree and Prakrithi Jain. The new C++ simulator implements real UDP feedback, changing channel conditions, an adaptive group-size/interleaving policy, a parity cap, packet traces and NetAnim export. Streamlit supplies the interactive interface. Your original udp-fec.cc and 250-run baseline remain separate.

## Start in Ubuntu / VS Code WSL

Use **Ubuntu or Ubuntu on WSL2** with an existing, configured **ns-3.45** installation, Git, Python 3 and the ns-3 build dependencies. Build ns-3 first and verify its examples run. The ns-3 framework itself is not included in this repository. Official setup: https://www.nsnam.org/docs/release/3.45/installation/html/

Clone directly inside the ns-3.45 directory so its parent contains the ns3 launcher:

    cd ~/ns3-work/ns-3.45
    git clone https://github.com/Prathith-Rao/ns3-udp-fec-lab.git
    cd ns3-udp-fec-lab
    bash setup.sh
    bash launch.sh

Open http://localhost:8501 in your Windows browser. Leave the Ubuntu terminal running.

Setup first extracts the included measured-data.zip archive into data/, then asks for your Ubuntu password to install python3-venv, creates a project-only Python environment, installs Streamlit/Plotly/pandas, and copies the two new C++ files into scratch/. It never overwrites scratch/udp-fec.cc. The first new simulation may take a few minutes to build. The dashboard works with included measured results before that build.

Edit the canonical C++ files under src/, rather than their installed scratch/ copies. New experiments are saved under results/ and are excluded from Git by default. Curated measurements are versioned in measured-data.zip and unpacked into data/ by setup.sh.

## What the three tabs do

- **Simulation & replay:** select a measured run; play/pause/seek packets through sender → router → receiver; see DATA, PARITY, reverse FEEDBACK, drops and receiver recovery; inspect delivery delays, individual packets and controller decisions.
- **Performance analysis:** explore the existing 250-run baseline or the new repeated study, with run-level 95% Student-t intervals and delivery/delay/traffic metrics. Settings, platform and source version are kept in separate comparison groups.
- **Method & evidence:** policy explanation, assumptions and contribution boundaries.

The controls in the sidebar affect the **next** simulation. They do not alter an already saved run or its replay. Choose settings, click **Run ns-3 simulation**, then inspect the new result. This is offline replay after a discrete-event simulation; it is not real-time network emulation.

## A short viva demonstration

1. Select **DEMO: fixed-two-losses**. Eight source packets are sent. Two consecutive DATA packets are forced to drop: only six originals are delivered because one ordinary XOR group contains both losses.
2. Select **DEMO: interleaved-two-losses**. The same forced final-link arrival positions lose those two DATA packets. Interleaving puts them into different XOR groups. Both are reconstructed: eight originals delivered, within the 150 ms deadline.
3. Select **DEMO: adaptive**. This changing-channel demo starts clean, develops scattered loss, develops burst loss and recovers. Replay near 5.403 s to see a drop/recovery, then inspect **Controller decisions**. It moves between no parity, ordinary XOR and depth-2 interleaving as reports arrive.
4. Open **Performance analysis → Adaptive lab runs** and select a 1,000-packet condition. Each bar represents ten runs, not one fortunate demo. Compare timely delivery and application bytes per timely packet.
5. For a new live experiment, use adaptive / changing / 10% impaired loss / 150 ms / 50% budget / 400 packets. Click Run. Then try a 30 ms deadline: useful repair cannot fit the planning constraint, so the full controller avoids sending ineffective parity.

Packet sequence numbers start at zero. Forced-drop positions start at one and count forward-link arrivals, including parity; they are only for deterministic validation/demonstration. The two named demos were checked to lose the intended source DATA packets.

## New measurements and validation

From the cloned project folder:

    .venv/bin/python smoke_checks.py

This executes 12 real ns-3 scenarios: clean delivery, one/two losses, interleaving, late repair, final partial group, parity loss, duplicate loss, total forward loss, tight deadline, zero budget and reverse feedback loss.

For a repeatable 180-run study:

    .venv/bin/python run_study.py --repeats 10 --packets 1000

This compares six methods across scattered, burst and changing loss, with ten RNG runs per method/scenario. It saves to results/study-<time>/. Refresh Streamlit afterwards. To resume a particular interrupted study, supply its folder with --out; its manifest must match the requested study.

The included data/study-runs contains 180 actual ns-3.45 runs generated on Windows using a separate native build. The dashboard distinguishes platforms. Re-run the study on Ubuntu to produce a new Ubuntu evidence set. data/demo-runs contains eight actual traced simulations. data/baseline.csv contains your earlier 250 validated runs.

Additional package check, using Streamlit's testing API:

    .venv/bin/python tests/dashboard_checks.py

The exact delivered 180-run study, source version, measured demos and interface checks are audited. The test also works after adding your own runs.

## Optional separate NetAnim window

The embedded replay already provides a basic packet-path demonstration. NetAnim is an additional ns-3-specific option, supported by the official documentation: https://www.nsnam.org/wiki/NetAnim

    bash install_netanim.sh
    ~/ns3-work/netanim/build/netanim

This installs the Qt build dependencies, clones official NetAnim and builds it under ~/ns3-work/netanim. It requires network access. On Windows 11 WSL2 with WSLg, its window should appear on Windows. Generated XML has been parsed and checked; the project owner has also confirmed that the Qt viewer opens and works in Ubuntu/WSLg.

In Streamlit, keep **Export NetAnim XML** checked before running. Use **Download NetAnim animation** and open the downloaded XML in NetAnim. Alternatively open results/<run-id>/run-netanim.xml directly from Ubuntu. Use the XML open button, zoom to fit, reduce playback speed, enable packet display/metadata if needed, and press Play. NetAnim shows link packets; the Streamlit replay additionally explains application-level recovery.

If a netanim folder already exists, the installer preserves it. Build the existing checkout explicitly:

    cmake -S ~/ns3-work/netanim -B ~/ns3-work/netanim/build -G Ninja
    cmake --build ~/ns3-work/netanim/build -j 2

The installer checks the actual executable location and prints it; some builds may instead use build/bin/netanim. The WSL path warning does not prevent compilation.

Official build instructions: https://gitlab.com/nsnam/netanim/-/blob/master/README.md

## Where the code and evidence are

- src/udp-fec-lab.cc: real socket applications, encoding/decoding, feedback, channels, trace callbacks and NetAnim.
- src/fec_policy.h: the project controller's decision rule.
- lab_backend.py: launches ns-3, validates counts and loads evidence.
- app.py + replay.html: Streamlit dashboard and timestamp-driven animation.
- smoke_checks.py: deterministic end-to-end simulator checks.
- run_study.py: repeated experiments.
- NOVELTY.md: contribution, equations, experiment design and report mapping.
- VERIFICATION.md: what was actually executed and what remains to check on WSL.
- results/<run-id>/: summary JSON, per-source-packet CSV, event trace, controller CSV, optional NetAnim XML, execution log and provenance.

Application-byte cost includes the serialized project header and receiver feedback. It excludes UDP/IP/link headers. A duplicate counts as extra DATA traffic; reconstructed packets are not new network transmissions. The new lab uses a 45-byte header, whereas the earlier baseline used 25 bytes and omitted feedback. Never combine their byte-cost values into a single comparative experiment.

## Stop and restart

Stop Streamlit with Ctrl+C in its Ubuntu terminal. Save your work and close VS Code normally. If desired, run wsl --shutdown in Windows PowerShell after all Ubuntu work stops.

Next time, open Ubuntu and run:

    cd ~/ns3-work/ns-3.45/ns3-udp-fec-lab
    bash launch.sh

No reinstallation is needed. Saved experiments remain on disk.

If localhost:8501 is already occupied, stop the earlier Streamlit terminal or use:

    .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502

Then open http://localhost:8502.

## Additional Ubuntu evidence

The data/demo-runs/ubuntu-* folders preserve ten execution records exported by the project owner from Ubuntu. These reduce to four unique settings, so they are demonstrations, not ten independent repetitions. The original eight native Windows demos and 180 native Windows study runs remain separately identified by their provenance. Repeated executions of the same settings are deduplicated in dashboard comparisons.

## Historical baseline implementation

The historical/ directory contains the earlier standalone udp-fec.cc, its twelve-scenario validation script, experiment runner and experiment notes. It produced the separately displayed 250-run baseline. To reproduce it, copy historical/udp-fec.cc into the ns-3 root scratch/ folder, then run the historical Python scripts from the ns-3 root, as described in historical/EXPERIMENTS.md. The baseline runner needs matplotlib; install it in a Python environment if re-running its plots. Do not mix its byte-cost measurements with the extended application.

## Scope and attribution

The contribution is the implemented deadline/budget-aware control policy, its comparison with a loss-only policy and fixed protection, and the measured analysis/replay workflow. XOR coding, interleaving, ns-3, Streamlit and NetAnim are existing techniques/tools; no claim of inventing them is made. Read NOVELTY.md and RESULTS.md for the exact assumptions and measured tradeoffs. The ns-3 and NetAnim frameworks are obtained separately from their official sources.

## Measured-data archive

To keep the repository easy to download, the complete per-packet/trace/provenance evidence is compressed in measured-data.zip (not simulated by Python). setup.sh extracts it automatically. To inspect saved measurements without installing or running ns-3, extract it with Python 3 first:

    python3 -m zipfile -e measured-data.zip .

Then create a Python environment, install requirements.txt, and run Streamlit or tests/dashboard_checks.py. The expanded data/ folder is ignored by Git; new simulation results remain separate under results/.
