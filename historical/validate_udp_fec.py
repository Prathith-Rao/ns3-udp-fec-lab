"""Run deterministic integration checks from the ns-3.45 root directory.

Requires scratch/udp-fec.cc. Uses Python's standard library only.
These are validation scenarios, not performance measurements.
"""

import csv
from pathlib import Path
import subprocess
import sys


def main():
    root = Path.cwd()
    if not (root / "ns3").is_file() or not (root / "scratch/udp-fec.cc").is_file():
        raise SystemExit("Run this script from the ns-3.45 folder after copying the C++ file into scratch/.")
    destination = root / "results/validation"
    destination.mkdir(parents=True, exist_ok=True)
    # Expectations are properties of the actual sender/network/decoder combination.
    cases = [
        ("plain_clean", "--mode=plain", {"unique_delivered": 8, "timely_delivered": 8,
                                         "recovered": 0, "tx_packets": 8}),
        ("duplicate_clean", "--mode=duplicate", {"unique_delivered": 8, "duplicate_data": 8,
                                                  "tx_packets": 16}),
        ("fec_clean", "--mode=fec", {"unique_delivered": 8, "recovered": 0, "tx_packets": 10}),
        ("plain_missing", "--mode=plain --dropPackets=2", {"unique_delivered": 7}),
        ("duplicate_missing", "--mode=duplicate --dropPackets=2", {"unique_delivered": 8}),
        ("fec_one_missing", "--mode=fec --dropPackets=2", {"unique_delivered": 8,
                                                           "recovered": 1, "timely_recovered": 1}),
        ("fec_two_missing", "--mode=fec --dropPackets=2,3", {"unique_delivered": 6, "recovered": 0}),
        ("fec_parity_missing", "--mode=fec --dropPackets=5", {"unique_delivered": 8, "recovered": 0}),
        ("fec_last_partial", "--mode=fec --packets=7 --dropPackets=7", {"unique_delivered": 7,
                                                                      "recovered": 1, "tx_packets": 9}),
        ("fec_late_recovery", "--mode=fec --dropPackets=2 --deadlineMs=50",
         {"unique_delivered": 8, "recovered": 1, "timely_delivered": 7, "timely_recovered": 0}),
        ("deadline_impossible", "--mode=fec --deadlineMs=1", {"unique_delivered": 8,
                                                             "timely_delivered": 0}),
        ("total_loss", "--mode=fec --loss=1", {"unique_delivered": 0, "recovered": 0,
                                               "link_drops": 10}),
    ]
    failed = 0
    for name, options, expected in cases:
        prefix = f"results/validation/{name}"
        arguments = (f"udp-fec --packets=8 --group=4 --loss=0 --run=1 "
                     f"--deadlineMs=150 --output={prefix} {options}")
        # argv form avoids a shell. ns3 receives the scenario as a single argument.
        result = subprocess.run([str(root / "ns3"), "run", arguments],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            print(f"FAIL {name}: simulation exited with {result.returncode}\n{result.stdout}")
            failed += 1
            continue
        with Path(prefix + "-summary.csv").open(newline="") as source:
            row = next(csv.DictReader(source))
        errors = [f"{key}: expected {value}, got {row[key]}"
                  for key, value in expected.items() if int(row[key]) != value]
        if errors:
            print(f"FAIL {name}: {'; '.join(errors)}")
            failed += 1
        else:
            print(f"PASS {name}")
    print(f"\n{len(cases) - failed}/{len(cases)} validation scenarios passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
