"""Streamlit dashboard backed by measured ns-3 output."""
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import lab_backend as backend
st.set_page_config(page_title='Packet Recovery Lab',page_icon='📡',layout='wide')
st.markdown('''<style>.block-container{padding-top:1.5rem;max-width:1350px}h1{letter-spacing:-.035em}div[data-testid="stMetric"]{background:white;border:1px solid #dce5ee;border-radius:12px;padding:15px}.hero{background:linear-gradient(110deg,#15354c,#176b87);color:white;padding:26px 30px;border-radius:16px;margin-bottom:20px}.hero h1{color:white;margin:0;font-size:2.2rem}.hero p{color:#dcecf4;margin:6px 0 0}</style>''',unsafe_allow_html=True)
st.markdown('<div class="hero"><h1>Packet Recovery Lab</h1><p>Follow the packets. Inspect the decisions. Compare the cost of recovery.</p></div>',unsafe_allow_html=True)
with st.sidebar:
 st.title('Experiment controls')
 root=st.text_input('ns-3.45 folder',value=str(backend.default_ns3_root()))
 available=backend.runtime_available(root)
 st.caption('Simulation engine connected' if available else 'Saved results are available. Set your ns-3 folder to run new experiments.')
 with st.form('simulation_form'):
  mode=st.selectbox('Protection method',list(backend.MODES),index=5,format_func=backend.MODES.get)
  scenario=st.selectbox('Channel scenario',list(backend.SCENARIOS),index=2,format_func=backend.SCENARIOS.get)
  loss=st.slider('Impaired-channel packet loss (%)',0,40,10)
  deadline=st.slider('Playback deadline (ms)',30,250,150,10)
  budget=st.select_slider('Maximum parity / source traffic',options=[0.,.125,.25,.5,1.],value=.5,format_func=lambda x:f'{100*x:g}%')
  packets=st.selectbox('Source packets',[200,400,1000,2000],index=1)
  seed_run=st.number_input('Random run number',min_value=1,max_value=1000,value=1)
  with st.expander('Advanced settings'):
   target=st.slider('Planning delivery target (%)',90,99,97)
   feedback_loss=st.slider('Feedback-path loss (%)',0,50,0)
   animation=st.checkbox('Export NetAnim XML',value=True)
  submitted=st.form_submit_button('Run ns-3 simulation',type='primary')
 st.caption('Budget constrains adaptive parity choices. Cost measurements also include feedback. Fixed baselines retain their specified protection.')
 if submitted:
  if not available:st.error('The ns3 launcher was not found. Select your Ubuntu ns-3.45 folder.')
  else:
   settings=dict(mode=mode,scenario=scenario,loss=loss/100,deadlineMs=deadline,budget=budget,packets=packets,run=int(seed_run),target=target/100,feedbackLoss=feedback_loss/100,animation=int(animation))
   try:
    with st.spinner('Running the ns-3 experiment...'):new_case=backend.run_case(settings,root=root)
    st.session_state['case_choice']=new_case['_file'];st.success('Simulation completed and saved.')
   except (ValueError,OSError,RuntimeError) as error:st.error(str(error))
simulation_tab,performance_tab,method_tab=st.tabs(['Simulation & replay','Performance analysis','Method & evidence'])
cases=backend.load_cases();lookup={c['_file']:c for c in cases}
with simulation_tab:
 if not cases:st.info('Run a short ns-3 experiment. Your validated baseline is already available under Performance analysis.')
 else:
  options=list(lookup)
  if st.session_state.get('case_choice') not in lookup:
   preferred=[c['_file'] for c in cases if c['mode']=='adaptive' and c['scenario']=='changing' and Path(c['_prefix']+'-events.csv').is_file()]
   st.session_state['case_choice']=preferred[-1] if preferred else options[-1]
  selected=st.selectbox('Saved simulation',options,format_func=lambda p:backend.case_label(lookup[p]),key='case_choice')
  case=lookup[selected]
  if 'demo-runs' in Path(selected).parts:st.caption('Included measured demo: ns-3.45 on Windows. New runs execute in your selected Ubuntu environment.')
  cols=st.columns(4)
  cols[0].metric('Timely delivery',f"{case['timely_percent']:.2f}%")
  cols[1].metric('Packets reconstructed',str(case['recovered']))
  cols[2].metric('Added forward traffic',f"{case['extra_forward_percent']:.1f}%")
  cols[3].metric('Controller switches',str(case['controller_changes']))
  st.subheader('Packet path replay')
  replay=backend.replay_data(case)
  if replay['paths']:
   template=(backend.HERE/'replay.html').read_text(encoding='utf-8-sig')
   safe=json.dumps(replay,allow_nan=False).replace('</','<\\/')
   embedded=template.replace('__TRACE_DATA__',safe)
   if hasattr(st,'iframe'):st.iframe(embedded,height=425,alt='Recorded ns-3 packet paths and receiver recovery')
   else:components.html(embedded,height=425,scrolling=False)
  else:st.info('No event trace was recorded for this run.')
  left,right=st.columns([1.4,1]);packet_table=backend.read_table(case,'-packets.csv');control=backend.read_table(case,'-control.csv')
  with left:
   st.subheader('Delivery timeline')
   if not packet_table.empty:
    fig=go.Figure()
    for recovered,name,color in [(0,'Direct delivery','#216cb2'),(1,'XOR recovery','#159879')]:
     part=packet_table[(packet_table.delivered==1)&(packet_table.recovered==recovered)]
     fig.add_trace(go.Scatter(x=part.sequence,y=part.delay_ms,mode='markers',name=name,marker=dict(color=color,size=5),hovertemplate='Packet %{x}<br>Delay %{y:.3f} ms<extra></extra>'))
    fig.add_hline(y=case['deadline_ms'],line_dash='dash',line_color='#bb4a35',annotation_text='Playback deadline')
    fig.update_layout(height=310,xaxis_title='Original packet sequence',yaxis_title='First delivery delay (ms)',margin=dict(l=10,r=10,t=25,b=20),legend_orientation='h')
    st.plotly_chart(fig,key='timeline')
  with right:
   st.subheader('Traffic and delivery')
   fig=go.Figure(go.Bar(x=['Original DATA','Extra copies','PARITY','FEEDBACK'],y=[case['packets'],case['tx_data']-case['packets'],case['tx_parity'],case['tx_feedback']],marker_color=['#216cb2','#6ba1cc','#ad7200','#7855b3']))
   fig.update_layout(height=310,yaxis_title='Packets sent',margin=dict(l=10,r=10,t=25,b=20));st.plotly_chart(fig,key='traffic')
   st.caption(f"Observed forward loss: {case['observed_loss_percent']:.2f}%. Feedback is counted separately.")
  st.subheader('Controller decisions')
  if control.empty:st.caption('Fixed configuration. Receiver reports are still sent and counted.')
  else:
   fig=go.Figure()
   for column,label in [('k','Group size k'),('depth','Interleaving depth')]:fig.add_trace(go.Scatter(x=control.time_s,y=control[column],mode='lines+markers',name=label,line_shape='hv'))
   fig.update_layout(height=270,xaxis_title='Simulation time (s)',yaxis_title='Chosen configuration',legend_orientation='h',margin=dict(l=10,r=10,t=15,b=20));st.plotly_chart(fig,key='decisions')
   st.caption('Changes apply at the next frame boundary. k=1 means no parity. Candidate predictions are estimates, not delivery guarantees.');st.dataframe(control,hide_index=True)
  with st.expander('Inspect individual packets'):
   seq=st.number_input('Packet sequence to inspect',0,int(case['packets'])-1,0)
   st.dataframe(packet_table[packet_table.sequence==seq],hide_index=True)
   events=backend.read_table(case,'-events.csv')
   if not events.empty:st.dataframe(events[events.sequence==seq],hide_index=True)
  a,b=st.columns(2)
  with a:st.download_button('Download this run and evidence',backend.case_zip(case),file_name='ns3-run-evidence.zip',mime='application/zip')
  xml=Path(case['_prefix']+'-netanim.xml')
  if xml.is_file():
   with b:st.download_button('Download NetAnim animation',xml.read_bytes(),file_name='fec-demo.xml',mime='application/xml')
  st.caption('Replay uses actual ns-3 event timestamps. NetAnim provides a separate offline packet-path view.')

with performance_tab:
 dataset=st.radio('Results to analyse',['Validated 250-run baseline','Adaptive lab runs'],horizontal=True)
 metrics={'timely_percent':'Timely delivery (%)','delivery_percent':'Eventual delivery (%)','mean_delay_ms':'Mean delay of delivered packets (ms)','app_bytes_per_timely':'Application bytes per timely packet'}
 metric=st.selectbox('Performance metric',list(metrics),format_func=metrics.get)
 if dataset=='Validated 250-run baseline':
  raw=pd.read_csv(backend.HERE/'data/baseline.csv');raw['timely_percent']=100*raw.timely_ratio;raw['delivery_percent']=100*raw.delivery_ratio;raw['app_bytes_per_timely']=raw.app_bytes_per_timely_packet
  rows=[]
  for (label,p),group in raw.groupby(['label','loss'],sort=False):
   mean,half,n=backend.ci95(group[metric].tolist());rows.append({'Method':label,'Loss (%)':100*p,'Mean':mean,'95% interval half-width':half,'Runs':n})
  table=pd.DataFrame(rows);fig=go.Figure()
  for label in table.Method.unique():
   group=table[table.Method==label];fig.add_trace(go.Scatter(x=group['Loss (%)'],y=group.Mean,name=label,mode='lines+markers',error_y=dict(type='data',array=group['95% interval half-width'])))
  fig.update_layout(height=440,xaxis_title='Configured independent loss (%)',yaxis_title=metrics[metric],legend_orientation='h');st.plotly_chart(fig,key='baseline')
  st.caption('Validated ns-3.45 measurements: 1,000 source packets per run; 150 ms deadline; 10 independent runs per condition. This earlier cost measurement excludes feedback and uses a smaller application header; cost values cannot be pooled with new lab runs.')
  st.dataframe(table,hide_index=True)
  st.download_button('Download baseline measurements',(backend.HERE/'data/baseline.csv').read_bytes(),file_name='validated-baseline.csv',mime='text/csv')
 else:
  usable=[]
  for case_item in cases:
   provenance=Path(case_item['_file']).parent/'provenance.json'
   if provenance.exists():
    p=json.loads(provenance.read_text(encoding='utf-8-sig'))
    if not p['settings'].get('dropPackets'):
     item=dict(case_item);item['_fingerprint']=p.get('source_sha256','unknown');item['_platform']=p.get('platform','unknown');item['_feedback_loss']=p['settings'].get('feedbackLoss',0);item['_burst_length']=p['settings'].get('burstLength',3);item['_fixed_group']=p['settings'].get('group',4);usable.append(item)
  if not usable:st.info('Run experiments or use run_study.py to create repeated adaptive measurements.')
  else:
   def comparison_key(c):return (c['scenario'],c['loss_setting'],c['deadline_ms'],c['parity_budget'],c['target'],c['packets'],c['interval_ms'],c['_fingerprint'],c['_platform'],c['_feedback_loss'],c['_burst_length'],c['_fixed_group'])
   groups={comparison_key(c) for c in usable}
   def comparison_name(key):
    s,p,d,b,t,n,i,sha,platform,fl,burst,k=key;return f'{s} | loss {100*p:g}% | deadline {d:g} ms | budget {100*b:g}% | {n} packets | feedback loss {100*fl:g}% | {platform} | {sha[:6]}'
   key=st.selectbox('Comparable experiment settings',sorted(groups),format_func=comparison_name)
   subset=[c for c in usable if comparison_key(c)==key]
   unique={(c['mode'],c['run']):c for c in subset};rows=[]
   for method in backend.MODES:
    samples=[c for c in unique.values() if c['mode']==method]
    if samples:
     mean,half,n=backend.ci95([c[metric] for c in samples]);rows.append({'Method':backend.MODES[method],'Mean':mean,'95% interval half-width':half,'Independent runs':n})
   table=pd.DataFrame(rows)
   fig=go.Figure(go.Bar(x=table.Method,y=table.Mean,marker_color='#176b87',error_y=dict(type='data',array=table['95% interval half-width'].fillna(0))))
   fig.update_layout(height=400,yaxis_title=metrics[metric],margin=dict(t=25,b=30));st.plotly_chart(fig,key='lab_comparison');st.dataframe(table,hide_index=True)
   st.caption('Single runs have no confidence interval. Repeated RNG run IDs count once. Lab cost includes reverse feedback; keep this separate from the earlier baseline.')
   with st.expander('Create a repeatable study'):
    st.code('python run_study.py --repeats 10 --packets 1000',language='bash')
    st.write('Compare all methods under the same channel scenarios. Refresh this page after the study finishes.')
with method_tab:
 st.subheader('What is being proposed?')
 st.write('A lightweight receiver-feedback controller selects XOR group size and interleaving depth using a playback deadline and parity-traffic budget. XOR and interleaving are established techniques. The contribution is this implemented policy and its controlled evaluation.')
 st.markdown('''1. Receiver reports raw DATA losses, the longest missing run and observed delivery delay every 500 ms.
2. Sender smooths loss and considers groups of 8, 4 and 2.
3. The full controller considers depth 2 when consecutive losses are observed, then rejects repairs predicted to miss the deadline.
4. It chooses the cheapest predicted feasible protection. An infeasible target is recorded rather than guaranteed.
5. Stronger protection can start promptly; reducing protection requires two consistent reports. Changes apply at frame boundaries.''')
 st.latex(r'(k-1)\,d\,I+\widehat{L}_{95}+5\ \mathrm{ms}\leq D')
 st.caption('This planning constraint includes a fixed safety allowance. A 95th-percentile estimate does not guarantee every packet meets the deadline.')
 st.markdown('''**Viva demonstration:** compare fixed XOR and interleaved XOR with the same two forced losses. Inspect reconstruction and its deadline. Then play a changing-channel adaptive run and show the feedback and controller decisions.

**Evidence:** the simulator is C++ ns-3. Streamlit launches it and reads its files. Packet animation is an offline trace replay. Network simulation is not reimplemented in Python.

**Scope:** synthetic fixed-size audio-like payloads; one sender, router and receiver. No codec, perceived quality or energy model is measured. Buffer storage is finite-run storage. Feedback assumes a configured source interval and stream length. Burst transitions are indexed by packet arrivals; report observed loss as well as configured loss.''')
 st.link_button('NetAnim documentation','https://www.nsnam.org/wiki/NetAnim')
 st.link_button('Related research on adaptive streaming codes','https://www.eecg.utoronto.ca/~salma/papers/fong-acmmm19.pdf')
