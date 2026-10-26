"""Deterministic operational acceptance; writes only new synthetic/output files.

Run from the project directory. --baseline-source accepts an extracted old src/
for a numerical comparison using this same Python/FFmpeg environment.
"""
import argparse
from contextlib import nullcontext, redirect_stdout, redirect_stderr
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from audio_qc.cli import main
from audio_qc.config import load_config
from audio_qc.process import check_tools, ToolError
from audio_qc.scanner import inspect_file
from audio_qc.synthetic import sine, write_wav


def fingerprint(path):
    stat = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def verify(output, baseline_source=None):
    output.mkdir(parents=True, exist_ok=False)
    media = output / 'media'
    paths = {
        'valid': write_wav(media/'valid.wav', sine(), bext=True),
        'silent': write_wav(media/'silent.wav', np.zeros((192000, 1)), bext=True),
        'loud': write_wav(media/'loud.wav', sine(amplitude=.5), bext=True),
        'stereo': write_wav(media/'stereo.wav', sine(channels=2), bext=True),
        'surround': write_wav(media/'surround.wav', sine(channels=6), mask=0x3f, bext=True),
        'lra': write_wav(media/'lra.wav', np.concatenate([sine(20, amplitude=x) for x in (.03,.1,.3)]), bext=True),
    }
    clicks = sine()
    clicks[48000] += .6
    paths['click'] = write_wav(media/'click.wav', clicks, bext=True)
    fingerprints = {key: fingerprint(path) for key, path in paths.items()}
    scenarios = {}

    def scenario(name, source, expected, injection=None, options=()):
        folder = output/name
        out, err = StringIO(), StringIO()
        with (injection or nullcontext()), redirect_stdout(out), redirect_stderr(err):
            code = main([str(source), '--preset', 'BROADCAST_EBU_R128', '--output', str(folder), *options])
        recovery = name == 'F_report_error'
        report = json.loads((folder/('QC_RECOVERY.json' if recovery else 'QC_REPORT.json')).read_text())
        actual = (code, report['audio_compliance'], report['execution_status'])
        assert actual == expected, (name, actual, expected)
        assert (folder/'QC_COMPLETE.json').exists() != recovery
        if not recovery:
            html = (folder/'QC_REPORT.html').read_text()
            assert f'>{report["audio_compliance"]}</span>' in html
            assert f'Execution: <b>{report["execution_status"]}</b>' in html
        else:
            assert 'HTML report:' not in out.getvalue()
        audio = report['files'][0]
        scenarios[name] = {'exit_code': code, 'audio_compliance': report['audio_compliance'],
                           'execution_status': report['execution_status'],
                           'measurement_outcomes': audio['measurement_outcomes'],
                           'operational_diagnostics': audio['operational_diagnostics'] + report['operational_diagnostics'],
                           'reports_agree': not recovery, 'recovery_only': recovery}
        (folder/'acceptance-console.txt').write_text(out.getvalue()+'\nSTDERR:\n'+err.getvalue())
        assert {k: fingerprint(p) for k,p in paths.items()} == fingerprints
        return audio

    valid = scenario('A_valid', paths['valid'], (0, 'PASS', 'COMPLETED'))
    assert valid['measurement_outcomes']['integrated_lufs']['state'] == 'SUCCESS'
    scenario('B_loudness', paths['loud'], (1, 'FAIL', 'COMPLETED'))
    peak_policy = output/'peak.yaml'
    peak_policy.write_text('true_peak:\n  maximum: -25\n')
    scenario('B_true_peak', paths['valid'], (1, 'FAIL', 'COMPLETED'), options=['--config',str(peak_policy)])
    failed = scenario('C_measurement_error', paths['valid'], (2, 'INCOMPLETE', 'PARTIAL'),
                      patch('audio_qc.scanner.measure_loudness', side_effect=ToolError('Acceptance: FFmpeg failed')))
    assert failed['measurement_outcomes']['integrated_lufs']['state'] == 'ERROR'
    evidence = scenario('D_evidence_error', paths['click'], (2, 'WARNING', 'PARTIAL'),
                        patch('audio_qc.cli.export_snippets', side_effect=PermissionError('Acceptance: evidence denied')),
                        ['--export-defect-snippets'])
    assert not any(c['status'] == 'FAIL' for c in evidence['checks'])
    assert len(evidence['defects']) == 1
    silent = scenario('E_silence', paths['silent'], (1, 'FAIL', 'COMPLETED'))
    assert silent['measurement_outcomes']['integrated_lufs']['state'] == 'UNAVAILABLE'
    assert silent['measurements']['integrated_lufs'] is None
    scenario('F_report_error', paths['valid'], (2, 'PASS', 'FAILED'),
             patch('audio_qc.reports.write_html', side_effect=OSError('Acceptance: report disk full')))

    policy = load_config(preset='BROADCAST_EBU_R128')
    policy['defects']['enabled'] = True
    measured = {key: inspect_file(path, policy).measurements for key, path in paths.items()}
    comparison = None
    if baseline_source:
        inputs = output/'baseline-input.json'
        inputs.write_text(json.dumps({key: str(path) for key,path in paths.items()}))
        program = '''import json,sys
from pathlib import Path
from audio_qc.config import load_config
from audio_qc.scanner import inspect_file
policy=load_config(preset="BROADCAST_EBU_R128")
policy["defects"]["enabled"]=True
paths=json.load(open(sys.argv[1]))
print(json.dumps({key:inspect_file(Path(path),policy).measurements for key,path in paths.items()},allow_nan=False))
'''
        old = subprocess.run([sys.executable, '-c', program, str(inputs)], check=True, capture_output=True, text=True,
                             env={**os.environ, 'PYTHONPATH':str(baseline_source.resolve())})
        previous = json.loads(old.stdout)
        assert measured == previous, 'Acoustic measurements differ from baseline'
        comparison = {'identical':True,'files':len(paths),'baseline_source':str(baseline_source),
                      'metrics':'All measurements dictionaries compared exactly; no float tolerance'}
        (output/'baseline-measurements.json').write_text(json.dumps(previous, indent=2))
    assert {k: fingerprint(p) for k,p in paths.items()} == fingerprints
    result = {'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              'tracked_changes':subprocess.check_output(['git','diff','--stat','HEAD'],text=True).strip(),
              'python':sys.version,'platform':platform.platform(),'tools':check_tools(),
              'fixtures':'Synthetic 48 kHz / 24-bit mono, stereo and 5.1 WAVs; no client programme audio',
              'scenarios':scenarios,'source_integrity':{'unchanged':True,'fingerprints':fingerprints},
              'baseline_comparison':comparison, 'measurements':measured}
    (output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-source',type=Path)
    args=parser.parse_args()
    verify(args.output.resolve(),args.baseline_source)
