"""Dashboard data audit and headless interaction checks; no WSL installation required."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lab_backend as lab
from streamlit.testing.v1 import AppTest

cases=lab.load_cases()
assert len(cases)>=188
for case in cases:
    lab.validate_case(case)
    provenance=json.loads((Path(case["_file"]).parent/"provenance.json").read_text())
    if case["mode"] in ("adaptive","loss-adaptive"):
        assert case["tx_parity"]<=case["parity_budget"]*case["packets"]+1e-9
    if "study-runs" in Path(case["_file"]).parts:
        assert provenance["source_sha256"]==lab.source_hash()
study=[c for c in cases if "study-runs" in Path(c["_file"]).parts]
assert len(study)==180
assert len({(c["scenario"],c["mode"],c["run"]) for c in study})==180
demo=next(c for c in cases if c["mode"]=="adaptive" and "demo-runs" in Path(c["_file"]).parts)
replay=lab.replay_data(demo)
assert {p["kind"] for p in replay["paths"]}=={"DATA","PARITY","FEEDBACK"}
assert any(f["d"]==2 for f in replay["frames"])
assert any(f["k"]==1 for f in replay["frames"])
assert {p["node"] for path in replay["paths"] for p in path["points"]}=={0,1,2}
assert abs(lab.ci95([1,2,3,4,5,6,7,8,9,10])[0]-5.5)<1e-9
app=AppTest.from_file(str(lab.HERE/"app.py"),default_timeout=60).run()
assert not app.exception,[e.message for e in app.exception]
assert len(app.metric)==4
app.radio[0].set_value("Adaptive lab runs").run()
assert not app.exception,[e.message for e in app.exception]
assert any(len(t.value)==6 for t in app.dataframe)
for metric in ["mean_delay_ms","app_bytes_per_timely","delivery_percent"]:
    widget=next(w for w in app.selectbox if w.label=="Performance metric")
    widget.set_value(metric).run()
    assert not app.exception,[e.message for e in app.exception]
print(f"PASS {len(cases)} measured cases audited; 180 unique repeated study runs.")
print("PASS trace includes three nodes, data, parity, feedback and changing frame decisions.")
print("PASS Streamlit saved replay, both datasets and all four performance metrics.")
