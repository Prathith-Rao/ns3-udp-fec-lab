"""Real ns-3 execution, result loading, aggregation and trace-replay helpers."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
MODES = {'plain':'Plain UDP', 'duplicate':'Duplication', 'fixed':'Fixed XOR (k=4)',
         'interleaved':'Fixed interleaved XOR', 'loss-adaptive':'Loss-only adaptive',
         'adaptive':'Deadline-aware adaptive'}
SCENARIOS = {'steady':'Scattered loss', 'burst':'Burst loss', 'changing':'Clean → scattered → burst → recovery'}
T95 = {2:12.706204736,3:4.302652730,4:3.182446305,5:2.776445105,6:2.570581836,
       7:2.446911851,8:2.364624252,9:2.306004135,10:2.262157163,20:2.093024054,30:2.045229642}


def default_ns3_root():
    if os.getenv('NS3_ROOT'):
        return Path(os.environ['NS3_ROOT']).expanduser()
    for parent in [HERE.parent, *HERE.parents]:
        if (parent/'ns3').is_file():
            return parent
    return Path.home()/'ns3-work/ns-3.45'


def source_hash():
    digest = hashlib.sha256()
    for name in ['udp-fec-lab.cc','fec_policy.h']:
        digest.update((HERE/'src'/name).read_bytes())
    return digest.hexdigest()


def runtime_available(root):
    native = os.getenv('FEC_LAB_EXECUTABLE')
    return bool(native and Path(native).is_file()) or (Path(root)/'ns3').is_file()


def install_source(root):
    root = Path(root)
    if not (root/'ns3').is_file():
        raise ValueError('Select your ns-3.45 root folder, containing the ns3 launcher.')
    for name in ['udp-fec-lab.cc','fec_policy.h']:
        target = root/'scratch'/name
        original = HERE/'src'/name
        if target.exists() and target.read_bytes() != original.read_bytes():
            # Preserve any earlier local version before installing this version.
            backup = target.with_name(target.name+'.previous')
            if not backup.exists():
                shutil.copy2(target, backup)
        shutil.copy2(original, target)


def run_case(settings, root=None, destination=None):
    root = Path(root or default_ns3_root()).expanduser().resolve()
    base = Path(destination or HERE/'results').resolve()
    base.mkdir(parents=True, exist_ok=True)
    case_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
    folder = base/case_id
    folder.mkdir()
    prefix = folder/'run'
    native = os.getenv('FEC_LAB_EXECUTABLE')
    options = {'mode':'adaptive','scenario':'changing','packets':400,'intervalMs':20,
               'deadlineMs':150,'loss':.10,'budget':.5,'target':.97,'run':1,'group':4,
               'depth':1,'burstLength':3,'feedbackLoss':0,'trace':1,'animation':1}
    unknown = set(settings)-set(options)-{'dropPackets'}
    if unknown:
        raise ValueError(f'Unknown settings: {sorted(unknown)}')
    options.update(settings)
    if options['mode'] not in MODES or options['scenario'] not in SCENARIOS:
        raise ValueError('Unknown mode or scenario')
    tokens = [f'--{name}={value}' for name,value in options.items() if value != '']
    tokens.append('--output=run')
    if native:
        command = [native,*tokens]
        cwd = folder
    else:
        install_source(root)
        command = [sys.executable,str(root/'ns3'),'run',shlex.join(['udp-fec-lab',*tokens]),'-j','2','--cwd',str(folder)]
        cwd = root
    try:
        result = subprocess.run(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                text=True,timeout=600)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Simulation/build exceeded ten minutes. Check the build in an Ubuntu terminal.') from error
    (folder/'execution.log').write_text(result.stdout,encoding='utf-8')
    if result.returncode:
        raise RuntimeError('ns-3 execution failed.\n'+result.stdout[-12000:])
    summary_file = Path(str(prefix)+'-summary.json')
    if not summary_file.is_file():
        raise RuntimeError('ns-3 did not produce a summary.\n'+result.stdout[-5000:])
    provenance = {'created_utc':datetime.now(timezone.utc).isoformat(),'source_sha256':source_hash(),
                  'platform':sys.platform,'settings':options,'command':command,
                  'evidence':'Measured ns-3.45 output; not a Python reimplementation.'}
    (folder/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    summary = load_case(summary_file)
    validate_case(summary)
    return summary


def load_case(path):
    path = Path(path)
    item = json.loads(path.read_text(encoding='utf-8-sig'))
    if item.get('schema') != 2 or item.get('engine') != 'ns-3.45':
        raise ValueError(f'Unsupported result schema: {path}')
    item['_prefix'] = str(path)[:-len('-summary.json')]
    item['_file'] = str(path)
    n = item['packets']
    item['delivery_percent'] = 100*item['delivered']/n
    item['timely_percent'] = 100*item['timely']/n
    item['residual_percent'] = 100*(n-item['delivered'])/n
    item['parity_percent'] = 100*item['tx_parity']/n
    item['extra_forward_percent'] = 100*(item['tx_data']+item['tx_parity']-n)/n
    item['observed_loss_percent'] = 100*item['link_drops']/item['link_arrivals'] if item['link_arrivals'] else 0
    item['app_bytes_per_timely'] = ((item['tx_forward_app_bytes']+item['tx_feedback_app_bytes'])/item['timely']
                                    if item['timely'] else None)
    return item


def load_cases():
    files = list((HERE/'data'/'demo-runs').glob('**/*-summary.json'))
    files += list((HERE/'data'/'study-runs').glob('**/*-summary.json'))
    files += [p for p in (HERE/'results').glob('**/*-summary.json') if 'validation' not in p.relative_to(HERE/'results').parts]
    cases = []
    for path in files:
        try:
            cases.append(load_case(path))
        except (OSError,ValueError,KeyError,json.JSONDecodeError):
            continue
    return sorted(cases,key=lambda r:r['_file'])


def read_table(case,suffix):
    import pandas as pd
    path = Path(case['_prefix']+suffix)
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def validate_case(case):
    n = case['packets']
    if not (0<=case['timely']<=case['delivered']<=n and
            0<=case['timely_recovered']<=case['recovered']<=case['delivered']):
        raise ValueError('Inconsistent delivery counts')
    if case['tx_data']+case['tx_parity'] != case['link_arrivals']:
        raise ValueError('Not all transmitted packets reached the final link')
    if case['tx_forward_app_bytes'] != (case['tx_data']+case['tx_parity'])*(case['payload_bytes']+45):
        raise ValueError('Application byte accounting is inconsistent')
    if case['tx_feedback_app_bytes'] != case['tx_feedback']*69:
        raise ValueError('Feedback byte accounting is inconsistent')
    table = read_table(case,'-packets.csv')
    if len(table)!=n or table['sequence'].tolist()!=list(range(n)):
        raise ValueError('Packet records are incomplete')
    if int(table['delivered'].sum())!=case['delivered'] or int(table['timely'].sum())!=case['timely']:
        raise ValueError('Packet records do not match summary')
    if int(table['recovered'].sum())!=case['recovered']:
        raise ValueError('Recovered packet count mismatch')
    observed = table['delivered'].eq(1) & table['delay_ms'].le(case['deadline_ms']+1e-6)
    if not observed.equals(table['timely'].eq(1)):
        raise ValueError('Deadline classifications are inconsistent')
    return True


def ci95(values):
    values = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not values:
        return None,None,0
    mean = statistics.mean(values)
    if len(values)<2:
        return mean,None,len(values)
    if len(values) not in T95:
        # Prevent a falsely labelled exact t interval when unsupported n is requested.
        return mean,None,len(values)
    half = T95[len(values)]*statistics.stdev(values)/math.sqrt(len(values))
    return mean,half,len(values)


def case_label(case):
    path=Path(case['_file'])
    if 'demo-runs' in path.parts:
        return f"DEMO: {path.parent.parent.name} · {MODES[case['mode']]}"
    if 'study-runs' in path.parts:
        return f"STUDY: {MODES[case['mode']]} · {case['scenario']} · run {case['run']}"
    return f"{MODES[case['mode']]} · {case['scenario']} · run {case['run']} · {path.parent.name}"


def case_zip(case):
    prefix = Path(case['_prefix'])
    memory = io.BytesIO()
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in prefix.parent.iterdir():
            if path.is_file():
                archive.write(path,arcname=path.name)
    return memory.getvalue()


def replay_data(case):
    events = read_table(case,'-events.csv')
    if events.empty:
        return {'paths':[],'recoveries':[],'frames':[],'end':1}
    paths=[]
    for wire,frame in events[events['wire_id']>0].groupby('wire_id'):
        frame = frame.sort_values('time_s')
        transmits = frame[frame['event']=='NET_TX']
        if transmits.empty:
            continue
        points = [{'t':float(r.time_s),'node':int(r.node)} for r in transmits.itertuples()]
        terminal = frame[frame['event'].isin(['RX','DROP'])]
        status='unknown'
        if not terminal.empty:
            last=terminal.iloc[-1]
            points.append({'t':float(last.time_s),'node':int(last.node)})
            status='drop' if last.event=='DROP' else 'received'
        first=transmits.iloc[0]
        paths.append({'wire':int(wire),'kind':first.kind,'seq':int(first.sequence),
                      'block':int(first.block),'points':points,'status':status})
    recoveries=[{'t':float(r.time_s),'seq':int(r.sequence),'late':r.detail=='late'}
                for r in events[events['event']=='RECOVER'].itertuples()]
    frames=[{'t':float(r.time_s),'k':int(r.k),'d':int(r.depth)}
            for r in events[events['event']=='FRAME'].itertuples()]
    return {'paths':paths,'recoveries':recoveries,'frames':frames,'end':float(events['time_s'].max())+.15}
