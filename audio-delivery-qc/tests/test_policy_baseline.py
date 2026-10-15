"""Golden data captured from M2.1 before the M3 production refactor."""
import json
from pathlib import Path

import numpy as np
import pytest

from audio_qc.config import load_config
from audio_qc.reports import build_report, write_reports
from audio_qc.scanner import discover, inspect_file
from audio_qc.synthetic import sine, write_wav


CASES = ('FILM_48K', 'BROADCAST_EBU_R128', 'CUSTOM', 'defects_and_zero_rule',
         'true_peak_only', 'levels_disabled')


def baseline_policy(case):
    config = load_config(preset=case if case in CASES[:3] else 'FILM_48K')
    if case == 'defects_and_zero_rule':
        config['defects']['enabled'] = True
        config['defects']['max_candidates'] = 1
        config['defects']['dropouts']['fail_zero_run_ms'] = 800
    elif case == 'true_peak_only':
        config['loudness']['enabled'] = False
        config['true_peak']['maximum'] = -6
    elif case == 'levels_disabled':
        config['loudness']['enabled'] = False
    return config


def baseline_media(folder):
    write_wav(folder/'clean.wav', sine(), bext=True, time_reference=172800000)
    write_wav(folder/'nested'/'wrong_format.wav', sine(4, rate=44100), rate=44100, bits=16)
    write_wav(folder/'clipped.wav', sine(amplitude=1.3))
    write_wav(folder/'silence.wav', np.zeros((48000, 1)))
    clicks = sine(3, amplitude=.03, frequency=220)
    clicks[47996:47999] += .7
    clicks[48000:48008] += .8
    clicks[96000] += .7
    write_wav(folder/'clicks.wav', clicks, bext=True, time_reference=172800000)
    zeros = sine(3, amplitude=.04, frequency=220)
    zeros[48000:96000] = 0
    write_wav(folder/'zero_run.wav', zeros)
    with (folder/'broken.wav').open('xb') as handle:
        handle.write(b'corrupt audio')
    return discover(folder)[0]


def normalized(audio, folder):
    result = json.loads(json.dumps(audio.to_dict()).replace(str(folder), '<SOURCE>'))
    # M3.1 adds issue structure. These mono golden fixtures must still retain
    # every legacy value; never rewrite the pre-M3 golden data.
    for event in result['defects']:
        if 'channel_events' in event:
            assert event.pop('channels') == [event['channel']]
            channel_event, = event.pop('channel_events')
            assert {k: v for k, v in channel_event.items() if k != 'severity'} == {
                k: v for k, v in event.items() if k != 'severity'}
            assert channel_event['severity'] is None
    return result


@pytest.mark.integration
@pytest.mark.parametrize('case', CASES)
def test_pre_m3_reports_and_decisions_unchanged(tmp_path, case):
    source = tmp_path/'media'
    paths = baseline_media(source)
    policy = baseline_policy(case)
    files = [inspect_file(path, policy, with_hash=True) for path in paths]
    golden = json.loads((Path(__file__).parent/'fixtures'/'m3_baseline.json').read_text())
    assert [normalized(audio, source) for audio in files] == golden[case]
    report = build_report(source, files, [], policy, {}, 0)
    output = tmp_path/'reports'
    output.mkdir()
    write_reports(report, output)
    saved = json.loads((output/'QC_REPORT.json').read_text())
    assert saved['schema_version'] == 3
    assert saved['status'] == report['status']
    assert all((output/name).is_file() for name in ('QC_REPORT.html','QC_REPORT.csv','QC_DEFECTS.csv'))
    assert 'http://' not in (output/'QC_REPORT.html').read_text()
