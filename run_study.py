"""Run a fair repeated study and save real ns-3 evidence for the dashboard."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import lab_backend as lab

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats",type=int,choices=[3,5,10,20],default=10)
    parser.add_argument("--packets",type=int,default=1000)
    parser.add_argument("--deadline",type=int,default=150)
    parser.add_argument("--loss",type=float,default=.10)
    parser.add_argument("--out",default="")
    args=parser.parse_args()
    if not 8<=args.packets<=10000 or not 0<=args.loss<=.4:
        parser.error("Use 8..10000 packets and loss 0..0.4.")
    destination=Path(args.out) if args.out else lab.HERE/"results"/("study-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    destination.mkdir(parents=True,exist_ok=True)
    modes=["plain","duplicate","fixed","interleaved","loss-adaptive","adaptive"]
    scenarios=["steady","burst","changing"]
    specification=dict(source_sha256=lab.source_hash(),repeats=args.repeats,packets=args.packets,
                       deadline=args.deadline,loss=args.loss,budget=.5,modes=modes,scenarios=scenarios)
    manifest=destination/"study.json"
    if manifest.exists() and json.loads(manifest.read_text())!=specification:
        raise SystemExit("This folder belongs to a different study. Choose a new --out folder.")
    manifest.write_text(json.dumps(specification,indent=2))
    done={}
    for path in destination.glob("**/*-summary.json"):
        case=lab.load_case(path)
        done[(case["mode"],case["scenario"],case["run"])]=case
    total=len(modes)*len(scenarios)*args.repeats
    summaries=[]
    for scenario in scenarios:
        for mode in modes:
            for run in range(1,args.repeats+1):
                key=(mode,scenario,run)
                if key in done:
                    case=done[key]
                else:
                    case=lab.run_case(dict(mode=mode,scenario=scenario,run=run,packets=args.packets,
                                           deadlineMs=args.deadline,loss=args.loss,budget=.5,
                                           animation=0,trace=0),destination=destination)
                summaries.append(case)
                print(f"[{len(summaries)}/{total}] {mode}, {scenario}, run {run}",flush=True)
    fields=["mode","scenario","run","packets","deadline_ms","loss_setting","timely_percent",
            "delivery_percent","mean_delay_ms","p95_delay_ms","app_bytes_per_timely",
            "extra_forward_percent","observed_loss_percent","controller_changes"]
    with (destination/"study.csv").open("w",newline="") as target:
        writer=csv.DictWriter(target,fieldnames=fields,extrasaction="ignore")
        writer.writeheader();writer.writerows(summaries)
    print(f"\nStudy complete: {destination}\nRefresh the dashboard and select Adaptive lab runs.")
if __name__=="__main__":
    main()
