"""Opt-in real binary tests; never install Essentia into the application runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


@pytest.fixture
def experimental_python():
    path = os.environ.get('XQC_ESSENTIA_PYTHON')
    if not path:
        pytest.skip('Optional real Essentia checks: set XQC_ESSENTIA_PYTHON to isolated interpreter')
    return path


def invoke(python, code, *arguments):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(map(str, [root/'src', root/'scripts']))}
    result = subprocess.run([python, '-c', code, *map(str, arguments)], env=env,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        pytest.fail(f'Isolated runtime exited {result.returncode}: {result.stderr[-6000:]}')
    return result


def test_real_binding_state_silence_and_file_edges(experimental_python):
    result = invoke(experimental_python, '''
import json, numpy as np
from click_experiment.essentia_detector import ClickDetector, detect, runtime
from types import SimpleNamespace
x = np.zeros((2048,6)); x[[0,255,256,1023,2047],4]=.7
pcm=SimpleNamespace(rate=48000,channels=6,start=0,end=len(x),read=lambda a,b: x[a:b])
clip=dict(start_sample=0,end_sample=len(x),channels=list(range(1,7)))
r=detect(pcm,clip,{})
d=ClickDetector(sampleRate=48000.0,frameSize=512,hopSize=256)
frame=np.zeros(512,dtype=np.float32); frame[256]=.7
a=d(frame); b=d(np.zeros(512,dtype=np.float32)); c=d(frame)
print(json.dumps(dict(result=r, counts=[len(a[0]),len(b[0]),len(c[0])],
                     positions=[round(float(a[0][0])*48000),round(float(c[0][0])*48000)],runtime=runtime())))
''')
    data = json.loads(result.stdout)
    assert data['counts'] == [1, 0, 1]
    assert data['positions'] == [256, 768]
    events = data['result']['events']
    # LPC may extend the detected interval beyond an injected single sample.
    # Coordinate preservation does not imply perfect localization by the detector.
    assert len(events) == 4
    assert all(e['channel'] == 5 for e in events)
    assert events[0]['sample_index'] == 0
    assert events[-1]['end_sample'] == 2048
    for sample in (0, 255, 256, 1023, 2047):
        assert any(e['sample_index'] <= sample < e['end_sample'] for e in events)


@pytest.mark.integration
def test_real_detector_finds_baseline_miss_and_retains_bwf_source(experimental_python, tmp_path):
    from audio_qc.synthetic import sine, write_wav
    from hashlib import sha256
    # The standalone fixture below injects a positive step: production requires
    # paired opposite edges <=5 ms; this detector can find the leading transient.
    x = sine(2, frequency=220, amplitude=.03); x[48000:,0] += .3
    path = write_wav(tmp_path/'step.wav', x, bits=24, bext=True, time_reference=172800000)
    before = (sha256(path.read_bytes()).hexdigest(), path.stat().st_size, path.stat().st_mtime_ns)
    result = invoke(experimental_python, '''
import json,sys
from click_experiment.audio import PCMClip,detect_clip,score_events
from click_experiment.essentia_detector import detect
c=dict(file=sys.argv[1],sample_rate=48000,start_sample=20000,end_sample=80000,channels=[1])
with PCMClip(c) as pcm:
 issues,capped=detect_clip(pcm,c)
 r=detect(pcm,c,{})
 print(json.dumps(dict(baseline=[e['sample_index'] for e in score_events(pcm,issues)],essentia=r)))
''', path)
    data = json.loads(result.stdout)
    assert not any(abs(s-48000) <= 48 for s in data['baseline'])
    assert any(abs(e['sample_index']-48000) <= 48 for e in data['essentia']['events'])
    assert before == (sha256(path.read_bytes()).hexdigest(), path.stat().st_size, path.stat().st_mtime_ns)


@pytest.mark.integration
def test_complete_benchmark_freezes_all_methods_before_holdout(experimental_python, tmp_path):
    import yaml
    from test_click_experiment import make_corpus
    manifest, clips = make_corpus(tmp_path)
    for c in clips:
        for a in c['annotations']:
            a.update(qc_disposition='reject' if a['kind'] == 'technical_click' else 'acceptable', basis='operator')
    manifest.write_text(yaml.safe_dump({'schema_version': 2, 'clips': clips}))
    result = invoke(experimental_python, '''
import json,sys
from pathlib import Path
from click_experiment import benchmark
original=benchmark.run_worker
def checked(clip, family, variants, output, index, **kwargs):
 if clip['split']=='validation':
  frozen=json.loads((output/'frozen_selection.json').read_text())
  assert set(frozen['selected'])=={'temporal','prediction','essentia'}
  if family!='baseline': assert len(variants)==1
 return original(clip,family,variants,output,index,**kwargs)
benchmark.run_worker=checked
r=benchmark.run(Path(sys.argv[1]),Path(sys.argv[2]))
print(json.dumps({'decision':r['decision'],'source_integrity':r['source_integrity']}))
''', manifest, tmp_path/'results')
    value = json.loads(result.stdout)
    assert value['decision']['decision'] == 'INSUFFICIENT_EVIDENCE'
    assert value['source_integrity'] is True
    output = tmp_path/'results'
    report = json.loads((output/'results.json').read_text())
    assert report['schema_version'] == 2
    methods = report['metrics']['validation']['all']
    assert set(methods) == {'baseline', 'temporal', 'prediction', 'essentia'}
    assert methods['baseline']['technical']['true_positives'] == 2
    assert methods['baseline']['technical']['false_alarms'] == 2
    assert methods['baseline']['technical']['recall'] == 1
    assert report['resources']['validation']['essentia']['peak_rss_bytes'] > 0
    assert report['resources']['validation']['temporal']['dependency'] == 'baseline'
    assert (output/'EXPERIMENT_COMPLETE.json').exists()
    html = (output/'report.html').read_text()
    assert 'Essentia' in html and 'Netflix' in html and 'noopener' in html
    assert (output/'candidates.csv').read_text().count('essentia') > 0
    assert report['essentia']['distribution'] == '2.1b6.dev1438'


@pytest.mark.integration
@pytest.mark.parametrize('failure', ['detector','evidence','report'])
def test_operational_failures_cannot_accept_or_lose_source_measurements(experimental_python, tmp_path, failure):
    import yaml
    from test_click_experiment import make_corpus
    manifest, clips = make_corpus(tmp_path)
    for c in clips:
        for a in c['annotations']:
            a.update(qc_disposition='reject' if a['kind']=='technical_click' else 'acceptable',basis='operator')
    manifest.write_text(yaml.safe_dump(dict(schema_version=2,clips=clips)))
    invoke(experimental_python, '''
import json,sys
from pathlib import Path
from click_experiment import benchmark, benchmark_report
failure=sys.argv[3]
if failure=='detector':
 original=benchmark.run_worker
 def failed(clip,family,variants,output,index,**kwargs):
  name,r=original(clip,family,variants,output,index,**kwargs)
  if family=='essentia':
   r['error']='controlled native error'
   (output/name).write_text(json.dumps(r))
  return name,r
 benchmark.run_worker=failed
elif failure=='evidence':
 original=benchmark.export_snippets
 def failed(audio,*args,**kwargs):
  audio.operational('snippet_export','controlled disk full',required=True)
 benchmark.export_snippets=failed
else:
 def failed(*args): raise PermissionError('controlled denied report')
 benchmark_report.render=failed
try: r=benchmark.run(Path(sys.argv[1]),Path(sys.argv[2]))
except PermissionError:
 assert failure=='report'
else:
 assert r['decision']['decision']!='VIABLE'
 assert r['source_integrity']
 assert r['metrics']['validation']['all']['baseline']['technical']['true_positives']==2
''',manifest,tmp_path/'results',failure)
    output=tmp_path/'results'
    baseline=json.loads((output/'clip_0001_baseline.json').read_text())
    assert baseline['variants']['baseline']['events']
    if failure=='report':
        assert (output/'EXPERIMENT_ERROR.json').exists()
        assert not (output/'EXPERIMENT_COMPLETE.json').exists()


@pytest.mark.parametrize('rate',[48000,192000])
def test_long_local_clock_at_large_integer_origin(experimental_python, rate):
    result=invoke(experimental_python, '''
import json,sys,numpy as np
from click_experiment.essentia_detector import detect
rate=int(sys.argv[1]); origin=2**54+7; first=origin+512; end=first+60*rate
class PCM:
 start=origin; channels=1
 def read(self,a,b):
  assert 0<=b-a<=512
  x=np.zeros((b-a,1))
  if a<=end-10<b: x[end-10-a,0]=.7
  return x
p=PCM(); p.rate=rate; p.end=end
r=detect(p,dict(start_sample=first,end_sample=end,channels=[1]),{})
print(json.dumps(dict(capped=r['capped'],intervals=[
 [e['sample_index']-first,e['end_sample']-first] for e in r['events']])))
''',rate)
    data=json.loads(result.stdout)
    assert not data['capped']
    assert any(a <= 60*rate-10 < b for a,b in data['intervals'])
    assert all(0 <= a < b <= 60*rate for a,b in data['intervals'])
