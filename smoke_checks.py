"""Run deterministic end-to-end checks against the actual ns-3 implementation."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import lab_backend as lab

def main():
    tests=[
        ("plain",dict(mode="plain",dropPackets=""),dict(delivered=8,recovered=0,tx_parity=0)),
        ("fixed_one_loss",dict(mode="fixed",dropPackets="2"),dict(delivered=8,recovered=1,tx_parity=2)),
        ("fixed_two_losses",dict(mode="fixed",dropPackets="2,3"),dict(delivered=6,recovered=0)),
        ("interleaved_two_losses",dict(mode="interleaved",dropPackets="2,3"),dict(delivered=8,recovered=2,timely=8)),
        ("interleaved_late",dict(mode="interleaved",dropPackets="1,2",deadlineMs=100),dict(delivered=8,recovered=2,timely=6)),
        ("partial_interleaved",dict(mode="interleaved",packets=7,dropPackets="2,3"),dict(delivered=7,recovered=2)),
        ("parity_lost",dict(mode="fixed",dropPackets="5"),dict(delivered=8,recovered=0)),
        ("duplicate_one_copy",dict(mode="duplicate",dropPackets="2"),dict(delivered=8,tx_data=16)),
        ("all_forward_lost",dict(mode="fixed",dropPackets="1,2,3,4,5,6,7,8,9,10"),dict(delivered=0,recovered=0)),
        ("tight_deadline",dict(mode="adaptive",deadlineMs=30),dict(tx_parity=0)),
        ("zero_budget",dict(mode="adaptive",budget=0),dict(tx_parity=0)),
        ("no_feedback",dict(mode="adaptive",packets=100,feedbackLoss=1),dict(feedback_received=0,controller_changes=0)),
    ]
    failures=[]
    for name,settings,expected in tests:
        args=dict(scenario="steady",loss=0,packets=8,animation=1,trace=1,group=4)
        args.update(settings)
        try:
            result=lab.run_case(args,destination=lab.HERE/"results"/"validation")
            for field,value in expected.items():
                assert result[field]==value,f"{field}: expected {value}, got {result[field]}"
            tree=ET.parse(result["_prefix"]+"-netanim.xml")
            assert tree.getroot().tag=="anim","Invalid animation XML"
            events=lab.read_table(result,"-events.csv")
            assert set(events[events.event=="NET_TX"].node)=={0,1,2},"Missing real network path traces"
            if settings.get("mode")=="adaptive":
                assert result["tx_parity"]<=result["parity_budget"]*result["packets"]+1e-9
            print("PASS",name,flush=True)
        except (AssertionError,ValueError,RuntimeError,OSError) as error:
            print("FAIL",name,str(error),flush=True);failures.append(name)
    print(f"\n{len(tests)-len(failures)}/{len(tests)} real ns-3 checks passed.")
    return bool(failures)
if __name__=="__main__":
    raise SystemExit(main())
