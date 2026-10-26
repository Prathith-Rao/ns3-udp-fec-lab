# Verification record — 25 October 2026

## Executed successfully

- Built the delivered C++ application against the official **ns-3.45** source using Windows native GCC 14.2. The same ns-3 socket, routing, point-to-point, ErrorModel and AnimationInterface APIs are used by the Ubuntu build.
- Ran **12/12 deterministic real ns-3 integration checks** in smoke_checks.py. Checks include byte-correct XOR reconstruction (C++ assertions), fixed two-loss failure, interleaved two-loss recovery, late repair, partial groups, parity loss, duplication, total forward loss, tight deadlines, zero budget and complete feedback loss.
- Parsed generated NetAnim XML from each integration case. It has an anim root. Real IPv4 Tx trace records include nodes 0, 1 and 2.
- Generated **eight traced measured demos**, including the same two-loss fixed/interleaved comparison.
- Completed **180 actual ns-3 study runs**: six methods × three scenarios × ten independent run IDs, each with 1,000 originals.
- Audited all 188 included demo/study cases against their per-packet records: complete sequence ranges, unique delivery counts, deadline classification, reconstructed counts, application byte accounting and adaptive cumulative parity caps.
- Confirmed the included study provenance matches the delivered combined C++/policy SHA-256:
  741fe4177adfd14e576f4afaf89b04299c2baca6a46e0e0c4247eeecfefc90e0
- Tested the Streamlit interface using AppTest: measured saved replay loads, old/new data selections work, all four performance metrics render without application exceptions.
- Tested the actual interface in headless Google Chrome: replay seek/play/pause, adaptive performance comparison and the **Run ns-3 simulation** button. The button launched the compiled ns-3 application, completed, and saved readable evidence. No browser JavaScript errors were observed.
- Visually inspected dashboard/replay and performance screenshots. The replay snapshot includes an actual loss and receiver recovery.
- Confirmed shell scripts use LF newlines without a BOM.

Python test environment: Python 3.13; Streamlit 1.66.1; Plotly 6.9.0; pandas 2.3.3. requirements.txt permits compatible earlier/current versions; the interface uses the modern iframe API when available and a compatibility fallback otherwise.

The native test copy needed a compiler-warning suppression for an unrelated ns-3 Wi-Fi source file under GCC 14, despite Wi-Fi not being part of the experiment. That test-build-only change affects warning treatment, not the network model. Delivered application source has no Windows-specific networking changes. The native simulator binaries and compiler environment are not distributed.

## Checks remaining on your Ubuntu installation

Direct access to your WSL environment was unavailable to the agent. Consequently setup.sh, the Ubuntu ns3-launcher subprocess path and the Qt NetAnim window were **not executed inside your WSL installation**. The package is prepared for that existing ns-3.45 installation; use the README commands, then run smoke_checks.py there.

NetAnim XML is verified, but the separate Qt viewer itself has not been installed/launched in local testing. The embedded Streamlit replay has been executed and tested in a real browser. Bash syntax checking through local MSYS was unavailable because that runtime could not create its process object; scripts were inspected and LF endings checked.

The included experiments are clearly labeled as Windows measurements. New WSL runs receive separate platform provenance and comparison groups. Do not describe included results as having been generated on your Ubuntu machine.

The pre-existing 250-run dataset is copied without changing its measurements. It uses a different application header/feedback accounting and is presented separately.

## User-provided WSL NetAnim build log

The subsequent user-provided terminal log confirms Qt dependencies installed, CMake configured, and Ninja completed [48/48] Linking CXX executable netanim. Launch failed because the earlier guide incorrectly used build/bin/netanim. The current default CMake build emits build/netanim. The guide now uses that path and the installer detects either executable layout. This log confirms a successful WSL build, but does not yet confirm the Qt window opens.

## Subsequent Ubuntu confirmation — 26 October 2026

The project owner subsequently confirmed the dashboard and Qt NetAnim viewer work in WSL. Their exported archive contains ten real Ubuntu execution records with the same combined C++ source hash, corresponding to four unique configurations. These are included as data/demo-runs/ubuntu-* in the public repository. This archive is evidence of those runs, not of a new 180-run Ubuntu study or an independently witnessed full Ubuntu integration-test run. The earlier native-build validation record above is retained as dated evidence.
