"""Collect repeated ns-3 UDP/FEC experiments and plot measured results.

Run inside ns-3.45: python3 run_experiments.py
Plot existing results only: python3 run_experiments.py --plot-only
Requires matplotlib; the rest uses Python's standard library.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shlex
import statistics
import subprocess
import sys


CONFIGS = [("plain", 4, "Plain UDP"), ("duplicate", 4, "Duplication"),
           ("fec", 2, "XOR k=2"), ("fec", 4, "XOR k=4"), ("fec", 8, "XOR k=8")]
LOSSES = [0.0, 0.01, 0.05, 0.10, 0.20]
COLORS = ["#555555", "#ae5820", "#267a46", "#176db0", "#8052a0"]
METRICS = ["delivery_ratio", "timely_ratio", "residual_loss_ratio", "mean_delay_ms",
           "p95_delay_ms", "app_bytes_per_timely_packet", "recovered_ratio",
           "timely_recovered_ratio", "observed_link_loss_ratio", "extra_tx_ratio"]
# Two-sided Student t 0.975 quantiles for the allowed repetition counts.
T95 = {5: 2.776445105, 10: 2.262157163, 20: 2.093024054, 30: 2.045229642}


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def write_csv(path, rows, fields=None):
    if not rows:
        raise ValueError("No result rows to write")
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def numeric(value):
    if value is None or str(value).strip() == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite metric: {value}")
    return number


def estimate(values):
    """Confidence interval across independent RUNS, not individual packets."""
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"mean": "", "ci95": "", "n": 0}
    mean = statistics.mean(clean)
    if len(clean) == 1:
        return {"mean": mean, "ci95": "", "n": 1}
    # Missing observations must not silently change the t quantile.
    if len(clean) not in T95:
        raise ValueError("Incomplete metric sample; inspect missing or undefined observations")
    half = T95[len(clean)] * statistics.stdev(clean) / math.sqrt(len(clean))
    return {"mean": mean, "ci95": half, "n": len(clean)}


def enrich(row):
    generated = int(row["generated"])
    delivered = int(row["unique_delivered"])
    timely = int(row["timely_delivered"])
    recovered = int(row["recovered"])
    timely_recovered = int(row["timely_recovered"])
    tx = int(row["tx_packets"])
    arrivals = int(row["link_arrivals"])
    drops = int(row["link_drops"])
    group = int(row["group"])
    mode = row["mode"]
    expected_tx = (2 * generated if mode == "duplicate" else
                   generated + math.ceil(generated / group) if mode == "fec" else generated)
    if not (generated > 0 and 0 <= timely <= delivered <= generated and
            0 <= timely_recovered <= recovered <= delivered and
            timely_recovered <= timely and 0 <= drops <= arrivals):
        raise ValueError("Invalid delivery or drop counts in simulation output")
    if tx != expected_tx or arrivals != tx:
        raise ValueError("Transmission mismatch or an upstream loss; inspect simulation logs")
    if int(row["rx_packets"]) != arrivals - drops:
        raise ValueError("Packets disappeared between final-link arrival and UDP reception")
    if float(row["loss"]) == 0 and (delivered != generated or drops != 0):
        raise ValueError("Zero-loss baseline failed")
    # Derive ratios from integer counts rather than the simulator's rounded ratios.
    row.update(delivery_ratio=delivered / generated, timely_ratio=timely / generated,
               residual_loss_ratio=(generated - delivered) / generated,
               recovered_ratio=recovered / generated,
               timely_recovered_ratio=timely_recovered / generated,
               observed_link_loss_ratio=drops / arrivals,
               extra_tx_ratio=(tx - generated) / generated)
    return row


def aggregate(rows):
    result = []
    for mode, group, label in CONFIGS:
        for loss in LOSSES:
            subset = [row for row in rows if row["mode"] == mode and
                      int(row["group"]) == group and float(row["loss"]) == loss]
            if not subset:
                raise ValueError(f"Missing condition: {label}, loss={loss}")
            if len({int(row["run"]) for row in subset}) != len(subset):
                raise ValueError("Duplicate run IDs within a condition")
            summary = {"label": label, "mode": mode, "group": group,
                       "loss": loss, "runs": len(subset)}
            for metric in METRICS:
                stats = estimate([numeric(row[metric]) for row in subset])
                for suffix, value in stats.items():
                    summary[f"{metric}_{suffix}"] = value
            result.append(summary)
    return result


def theory_delivery(mode, group, loss):
    # Independent equal-probability DATA/PARITY losses; complete groups; no queue loss.
    if mode == "plain":
        return 1 - loss
    if mode == "duplicate":
        return 1 - loss * loss
    return 1 - loss + loss * (1 - loss) ** group


def run_campaign(root, directory, repeats, packets):
    source = root / "scratch/udp-fec.cc"
    if not (root / "ns3").is_file() or not source.is_file():
        raise ValueError("Run from ns-3.45 with scratch/udp-fec.cc present")
    if any(character.isspace() for character in str(directory)):
        raise ValueError("Choose an output path without spaces for compatibility with ns3")
    if packets % 8:
        raise ValueError("Use a packet count divisible by 8 for complete protection groups")
    directory.mkdir(parents=True, exist_ok=True)
    specification = {
        "schema": 1, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "repeats": repeats, "packets": packets, "payload_bytes": 160,
        "interval_ms": 20, "deadline_ms": 150, "rng_seed": 12345,
        "run_ids": list(range(1, repeats + 1)), "losses": LOSSES,
        "configurations": CONFIGS,
        "interval_method": "Two-sided Student t 95% interval across run-level means",
    }
    manifest = directory / "experiment.json"
    # JSON normalisation makes tuple/list representations comparable after reloading.
    specification = json.loads(json.dumps(specification))
    if manifest.exists():
        if json.loads(manifest.read_text(encoding="utf-8")) != specification:
            raise ValueError("Existing campaign has different settings/source. Use --out with a new folder.")
    else:
        if any(directory.iterdir()):
            raise ValueError("Output directory is not empty and has no experiment manifest")
        manifest.write_text(json.dumps(specification, indent=2) + "\n", encoding="utf-8")
    runs_dir = directory / "runs"
    runs_dir.mkdir(exist_ok=True)
    rows = []
    build_checked = False
    total = len(CONFIGS) * len(LOSSES) * repeats
    print(f"Running {total} simulations: {len(CONFIGS)} configurations x "
          f"{len(LOSSES)} loss rates x {repeats} independent runs.", flush=True)
    for mode, group, label in CONFIGS:
        for loss in LOSSES:
            for run in range(1, repeats + 1):
                prefix = runs_dir / f"{mode}-k{group}-loss{round(loss * 100):02d}-run{run:02d}"
                summary_path = Path(str(prefix) + "-summary.csv")
                details_path = Path(str(prefix) + "-packets.csv")
                complete_path = Path(str(prefix) + ".complete")
                expected = {"mode": mode, "group": str(group), "run": str(run),
                            "generated": str(packets)}
                reused = summary_path.exists() and details_path.exists() and complete_path.exists()
                if not reused:
                    # First simulation checks the build; following runs reuse it.
                    command = [str(root / "ns3"), "run"]
                    if build_checked:
                        command.append("--no-build")
                    args = ["udp-fec", f"--mode={mode}", f"--group={group}",
                            f"--loss={loss}", f"--run={run}", f"--packets={packets}",
                            "--payload=160", "--intervalMs=20", "--deadlineMs=150",
                            f"--output={prefix}"]
                    command.append(shlex.join(args))
                    completed = subprocess.run(command, cwd=root, text=True,
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    Path(str(prefix) + ".log").write_text(completed.stdout, encoding="utf-8")
                    if completed.returncode:
                        raise RuntimeError(f"Simulation failed: {label}, loss={loss}, run={run}\n"
                                           f"{completed.stdout}")
                    build_checked = True
                recorded = read_csv(summary_path)
                if len(recorded) != 1:
                    raise ValueError(f"Expected one summary row: {summary_path}")
                row = recorded[0]
                if any(row[key] != value for key, value in expected.items()) or float(row["loss"]) != loss:
                    raise ValueError(f"Summary does not match requested condition: {summary_path}")
                row = enrich(row)
                complete_path.write_text("complete\n", encoding="utf-8")
                row.update(label=label, deadline_ms=150, interval_ms=20,
                           payload_bytes=160, prefix=str(prefix))
                rows.append(row)
                if len(rows) % repeats == 0:
                    print(f"[{len(rows):3}/{total}] {label:12} loss={100 * loss:2.0f}% complete",
                          flush=True)
    write_csv(directory / "all_runs.csv", rows)
    return rows


def make_plots(directory, rows, aggregated, plt):
    figures = directory / "figures"
    figures.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 120,
                         "savefig.dpi": 200})

    def save(fig, name):
        fig.savefig(figures / f"{name}.png", bbox_inches="tight")
        fig.savefig(figures / f"{name}.pdf", bbox_inches="tight")
        plt.close(fig)

    settings = [
        ("delivery_ratio", 100, "Unique packets delivered (%)", "Eventual delivery", "01_delivery"),
        ("timely_ratio", 100, "Original packets delivered within 150 ms (%)",
         "Delivery before the playback deadline", "02_timely_delivery"),
        ("residual_loss_ratio", 100, "Original packets never delivered (%)",
         "Residual loss after recovery", "03_residual_loss"),
        ("mean_delay_ms", 1, "Mean first delivery delay (ms)",
         "Latency of delivered packets", "04_delay"),
        ("app_bytes_per_timely_packet", 1, "Application bytes sent / timely original packet",
         "Communication cost of timely delivery", "05_communication_cost"),
    ]
    for metric, scale, ylabel, title, name in settings:
        fig, ax = plt.subplots(figsize=(8.0, 5.2))
        for (mode, group, label), color in zip(CONFIGS, COLORS):
            subset = [row for row in aggregated if row["mode"] == mode and row["group"] == group]
            ax.errorbar([row["loss"] * 100 for row in subset],
                        [numeric(row[f"{metric}_mean"]) * scale for row in subset],
                        yerr=[numeric(row[f"{metric}_ci95"]) * scale for row in subset],
                        color=color, label=label, marker="o", linewidth=1.6,
                        markersize=4, capsize=3)
            if metric == "delivery_ratio":
                fine = [i / 1000 for i in range(201)]
                ax.plot([p * 100 for p in fine],
                        [100 * theory_delivery(mode, group, p) for p in fine],
                        color=color, linestyle="--", linewidth=0.9, alpha=0.7)
        ax.set(xlabel="Configured independent packet loss (%)", ylabel=ylabel, title=title)
        ax.set_xticks([100 * loss for loss in LOSSES])
        ax.grid(alpha=0.22)
        ax.legend(fontsize=9, ncol=2)
        if metric in ("delivery_ratio", "timely_ratio"):
            ax.set_ylim(65, 101)
        if metric == "residual_loss_ratio":
            ax.set_ylim(bottom=0)
        footnote = "Points: run means; error bars: 95% Student t intervals across independent runs."
        if metric == "delivery_ratio":
            footnote += "\nDashed curves: independent-loss model for eventual delivery."
        elif metric == "mean_delay_ms":
            footnote += "\nLatency is conditional on delivery; assess with the delivery ratios."
        elif metric == "app_bytes_per_timely_packet":
            footnote += "\nIncludes the application header; excludes UDP, IP and link headers."
        fig.text(0.08, 0.01, footnote, fontsize=8, va="bottom")
        fig.tight_layout(rect=(0, 0.08, 1, 1))
        save(fig, name)

    # Aggregate CDF gives equal weight to each received packet across the ten runs.
    # It is descriptive, not a confidence interval or an independent-packet test.
    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    for (mode, group, label), color in zip(CONFIGS, COLORS):
        delays = []
        for row in rows:
            if row["mode"] == mode and int(row["group"]) == group and float(row["loss"]) == 0.10:
                for packet in read_csv(Path(row["prefix"] + "-packets.csv")):
                    if packet["delivered"] == "1":
                        delays.append(float(packet["delay_ms"]))
        delays.sort()
        if delays:
            ax.step(delays, [(i + 1) / len(delays) for i in range(len(delays))],
                    where="post", label=label, color=color, linewidth=1.5)
    ax.axvline(150, color="black", linestyle="--", linewidth=1, label="150 ms deadline")
    ax.set(xlabel="First delivery delay from original generation (ms)",
           ylabel="Fraction of delivered packets", title="Delivery delay at 10% packet loss",
           ylim=(0, 1.02))
    ax.grid(alpha=0.22)
    ax.legend(fontsize=9, ncol=2)
    fig.text(0.08, 0.01, "Pooled across runs, conditional on delivery; undelivered packets are excluded.",
             fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, "06_latency_distribution")


def report(directory, aggregated, specification):
    lines = ["# Independent packet loss experiment", "",
             f"Source packets per run: {specification['packets']}. "
             f"Independent runs per condition: {specification['repeats']}.", "",
             "Fixed settings: 160-byte source payload, 20 ms generation interval, "
             "150 ms playback deadline. All five configurations use the same source traffic.", "",
             "## Measured comparison at 10 percent packet loss", "",
             "| Mode | Eventual delivery | Timely delivery | Mean delay | App bytes per timely packet |",
             "|---|---:|---:|---:|---:|"]
    for row in aggregated:
        if row["loss"] != 0.1:
            continue
        def text_metric(metric, scale=1, decimals=2):
            mean = numeric(row[f"{metric}_mean"])
            half = numeric(row[f"{metric}_ci95"])
            if mean is None:
                return "Undefined"
            return f"{mean * scale:.{decimals}f} +/- {half * scale:.{decimals}f}"
        lines.append(f"| {row['label']} | {text_metric('delivery_ratio',100)}% | "
                     f"{text_metric('timely_ratio',100)}% | "
                     f"{text_metric('mean_delay_ms')} ms | "
                     f"{text_metric('app_bytes_per_timely_packet')} |")
    lines.extend(["", "Values are means +/- the half-width of a 95% Student t interval across runs.",
                  "", "## Interpretation limits", "",
                  "- Latency statistics exclude undelivered packets; read them alongside delivery ratios.",
                  "- Communication cost counts source payload and the application header, excluding transport/link headers.",
                  "- Larger groups delay availability of parity. Eventual recovery and timely recovery can differ.",
                  "- Duplication uses adjacent copies; these results describe independent loss, not burst loss.",
                  "- This is synthetic traffic. No perceived audio quality, MOS, or energy consumption was measured.",
                  "- The dashed theoretical curves assume complete equal-size groups and independent losses.",
                  "- The same run ID does not select identical lost source packets across modes.",
                  "- Existing simulations are reused only when the manifest and recorded settings match.",
                  "", "## Files", "",
                  "- all_runs.csv: every independent run and its measured metrics.",
                  "- aggregate.csv: means, 95% interval half-widths and sample sizes.",
                  "- experiment.json: settings and C++ source fingerprint.",
                  "- runs/: original per-run summaries, packet records and execution logs.",
                  "- figures/: six plots, each saved as PNG and PDF.", ""])
    (directory / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=list(T95), default=10)
    parser.add_argument("--packets", type=int, default=1000)
    parser.add_argument("--out", default="results/fec-campaign")
    parser.add_argument("--plot-only", action="store_true")
    args = parser.parse_args()
    if args.packets <= 0 or args.packets > 100000:
        parser.error("--packets must be between 1 and 100000")
    try:
        import matplotlib
        matplotlib.use("Agg")  # Generates figures without requiring a Linux GUI.
        import matplotlib.pyplot as plt
    except ImportError:
        parser.exit(1, "Install plotting support in Ubuntu: sudo apt install python3-matplotlib\n")
    root = Path.cwd()
    directory = Path(args.out).resolve()
    try:
        if args.plot_only:
            rows = read_csv(directory / "all_runs.csv")
        else:
            rows = run_campaign(root, directory, args.repeats, args.packets)
        specification = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
        aggregated = aggregate(rows)
        write_csv(directory / "aggregate.csv", aggregated)
        make_plots(directory, rows, aggregated, plt)
        report(directory, aggregated, specification)
        print(f"\nComplete. Results: {directory}\nRead RESULTS.md and open figures/.", flush=True)
        print("\nTimely delivery at 10% packet loss:")
        for row in aggregated:
            if row["loss"] == 0.1:
                print(f"  {row['label']:12} {100 * row['timely_ratio_mean']:.2f}% "
                      f"+/- {100 * row['timely_ratio_ci95']:.2f} percentage points")
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        parser.exit(1, f"Experiment stopped: {error}\nCompleted runs remain available for resuming.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
