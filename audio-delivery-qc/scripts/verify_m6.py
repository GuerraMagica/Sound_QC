"""Local synthetic M6 acceptance. New destinations only; no external services."""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
import struct
import subprocess
import sys
import time
from unittest.mock import patch
import numpy as np

from audio_qc.cli import main as cli_main
from audio_qc.config import load_config, save_config
from audio_qc.process import ToolError, check_tools
from audio_qc.scanner import inspect_file
from audio_qc.synthetic import chunk


def fingerprint(paths):
    results = {}
    for path in paths:
        digest = sha256()
        with path.open('rb') as stream:
            while block := stream.read(1024*1024):
                digest.update(block)
        stat = path.stat()
        results[str(path)] = dict(sha256=digest.hexdigest(), size=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return results


def fixture_helper():
    path = Path(__file__).resolve().parents[1]/'tests'/'m6_fixtures.py'
    spec = importlib.util.spec_from_file_location('m6_fixtures', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_programme_fixture


def memory_sources(directory, seconds):
    """Write PCM24 BWF in one-second blocks, never retain programme-sized arrays."""
    directory.mkdir()
    paths = []
    for index, role in enumerate(('L','R','C','LFE','Ls','Rs')):
        path = directory/f'Memory.{role}.wav'
        bext = bytearray(602)
        struct.pack_into('<QH', bext, 338, 172800000, 1)
        header = chunk(b'fmt ', struct.pack('<HHIIHH', 1, 1, 48000, 144000, 3, 24))+chunk(b'bext', bytes(bext))
        size = seconds*48000*3
        with path.open('xb') as stream:
            stream.write(b'RIFF'+struct.pack('<I',4+len(header)+8+size)+b'WAVE'+header+b'data'+struct.pack('<I',size))
            for second in range(seconds):
                t = np.arange(48000)/48000
                data = np.rint(.04*np.sin(2*np.pi*(100+index*137)*t)*2**23).astype('<i4')
                stream.write(data.view('u1').reshape(-1,4)[:,:3].tobytes())
        paths.append(path)
    return paths


def memory_case(root, seconds):
    source = root/f'sources-{seconds}'
    paths = memory_sources(source, seconds)
    before = fingerprint(paths)
    command = [sys.executable,'-m','audio_qc','inspect',str(source),'--detect-groups','--no-defects',
               '--output',str(root/f'report-{seconds}')]
    samples=[]
    with (root/f'memory-{seconds}.log').open('x') as log:
        proc=subprocess.Popen(command,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+180
            while proc.poll() is None:
                if time.monotonic()>deadline:
                    raise RuntimeError('Memory acceptance exceeded deadline')
                rows=subprocess.check_output(['ps','-axo','pid=,ppid=,rss='],text=True)
                processes=[tuple(map(int,line.split())) for line in rows.splitlines() if len(line.split())==3]
                children={pid for pid,ppid,rss in processes if ppid==proc.pid}
                samples.append({'elapsed':180-(deadline-time.monotonic()),
                    'parent_kib':next((rss for pid,ppid,rss in processes if pid==proc.pid),0),
                    'child_kib':max((rss for pid,ppid,rss in processes if pid in children),default=0)})
                time.sleep(.05)
            assert proc.returncode in (0,1), f'Memory scan failed: {proc.returncode}'
        finally:
            if proc.poll() is None:
                proc.send_signal(__import__('signal').SIGINT)
                proc.wait(timeout=10)
    assert fingerprint(paths)==before
    report=json.loads((root/f'report-{seconds}'/'QC_REPORT.json').read_text())
    assert report['programme_groups'][0]['programme_measurement']['measurements']['decoded_sample_frames']==seconds*48000
    assert samples and max(s['child_kib'] for s in samples)>0
    return {'seconds':seconds,'argv':command,'exit_code':proc.returncode,'samples':samples,
            'parent_peak_kib':max(s['parent_kib'] for s in samples),
            'child_peak_kib':max(s['child_kib'] for s in samples), 'source_integrity':True}


def verify(output, memory=False):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    make=fixture_helper()
    fixtures={layout:make(output/label,layout=layout) for layout,label in [('stereo','stereo'),('5.1','surround')]}
    silent=make(output/'silent',layout='stereo',case='silence')
    sources=[p for f in [*fixtures.values(),silent] for p in [*f['members'].values(),f['reference']]]
    before=fingerprint(sources)
    config=load_config(preset='CUSTOM')
    config['loudness'].update(enabled=True,target_lufs=-24,tolerance=20)
    config['defects']['enabled']=False
    equivalence=[]
    scenarios={}
    for label,fixture in [('A',fixtures['stereo']),('B',fixtures['stereo']),('C',fixtures['stereo']),
                           ('D',fixtures['stereo']),('E',silent),('F',fixtures['stereo']),('surround',fixtures['5.1'])]:
        case_config=json.loads(json.dumps(config))
        if label=='B': case_config['true_peak']['maximum']=-80
        cfg=output/f'{label}.yaml';save_config(cfg,case_config)
        destination=output/f'report-{label}'
        argv=['inspect',str(next(iter(fixture['members'].values())).parent),'--groups',str(fixture['manifest']),
              '--config',str(cfg),'--output',str(destination)]
        if label=='D': argv.append('--export-defect-snippets')
        else: argv.append('--no-defects')
        with ExitStack() as stack, (output/f'{label}.log').open('x') as log, redirect_stdout(log), redirect_stderr(log):
            if label=='C': stack.enter_context(patch('audio_qc.programme_measurement.run_loudness',side_effect=ToolError('Injected FFmpeg execution failure')))
            if label=='D': stack.enter_context(patch('audio_qc.cli.export_snippets',side_effect=OSError('Injected evidence permission denied')))
            if label=='F': stack.enter_context(patch('audio_qc.reports.write_html',side_effect=OSError(28,'Injected disk full')))
            code=cli_main(argv)
        report_path=destination/('QC_RECOVERY.json' if label=='F' else 'QC_REPORT.json')
        report=json.loads(report_path.read_text())
        g=report['programme_groups'][0];m=g['programme_measurement']
        record=dict(argv=argv,exit_code=code,audio_compliance=report['audio_compliance'],
                    execution_status=report['execution_status'],programme_state=m['state'],
                    integrated_lufs=m['measurements'].get('integrated_lufs'),
                    complete_marker=(destination/'QC_COMPLETE.json').exists(),report=str(report_path))
        if label!='surround': scenarios[label]=record
        if label in ('A','surround'):
            reference=inspect_file(fixture['reference'],case_config)
            deltas={}
            for metric in ('integrated_lufs','lra_lu','true_peak_dbtp'):
                value=m['measurements'][metric];expected=reference.measurements[metric]
                delta=abs(value-expected) if value is not None and expected is not None else None
                assert delta is not None and delta<=.1,(label,metric,delta)
                deltas[metric]=delta
            equivalence.append({'layout':g['layout'],'deltas':deltas,'reference':str(fixture['reference'])})
    assert scenarios['A']['exit_code']==0 and scenarios['A']['audio_compliance']=='PASS'
    assert scenarios['B']['exit_code']==1 and scenarios['B']['audio_compliance']=='FAIL'
    assert scenarios['C']['exit_code']==2 and scenarios['C']['audio_compliance']=='INCOMPLETE'
    assert scenarios['D']['exit_code']==2 and scenarios['D']['programme_state']=='SUCCESS'
    assert scenarios['E']['programme_state']=='SUCCESS' and scenarios['E']['integrated_lufs'] is None
    assert scenarios['F']['exit_code']==2 and not scenarios['F']['complete_marker']
    assert fingerprint(sources)==before
    result={'platform':platform.platform(),'python':sys.version,'backend':check_tools(),
            'scenarios':scenarios,'equivalence':equivalence,'source_integrity':True,'source_fingerprints':before,
            'scope':'Synthetic local operational acceptance; unit/integration AC evidence is in pytest logs',
            'limitations':['Professional DAW/reference meter comparison pending','Linux and Python 3.11 not verified by this local run']}
    if memory:
        records=[memory_case(output,n) for n in (30,600)]
        growth={key:records[1][key]-records[0][key] for key in ('parent_peak_kib','child_peak_kib')}
        result['memory']={'runs':records,'growth_kib':growth,'limit_kib':65536,
                          'passed':all(v<=65536 for v in growth.values())}
    (output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if memory:
        assert result['memory']['passed'], 'Memory growth exceeded proposed acceptance budget; inspect evidence'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--memory',action='store_true')
    args=parser.parse_args()
    result=verify(args.output,args.memory)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_fingerprints','memory')},ensure_ascii=False,indent=2))
