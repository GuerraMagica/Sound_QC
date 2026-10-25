"""Golden data captured from M2.1 before the M3 production refactor."""
import json
import math
from copy import deepcopy
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
    assert result.pop('audio_compliance') == result['status']
    result.pop('execution_status')
    result.pop('measurement_outcomes')
    result.pop('operational_diagnostics')
    signature = result['metadata'].pop('source_signature')
    stat = Path(audio.path).stat()
    assert signature == [stat.st_size, stat.st_mtime_ns, stat.st_ino]
    # Additive header/probe provenance was not present in the M3 snapshot.
    # Validate it separately; retain every original fact and check unchanged.
    if 'wave_format' in result['bwf']:
        header = result['bwf'].pop('wave_format')
        assert header['bit_depth'] == result['bit_depth']
        assert header['channels'] == result['channels']
        assert header['sample_rate'] == result['sample_rate']
        assert header['reason'] is None
    if 'bit_depth_provenance' in result['metadata']:
        provenance = result['metadata'].pop('bit_depth_provenance')
        assert provenance['source'] == 'FFPROBE'
        assert provenance['wave_bit_depth'] == result['bit_depth']
        assert provenance['reason'] is None
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


def assert_baseline_matches(actual, expected):
    """Keep golden facts exact apart from one IEEE-754 ULP for libm floats.

    ARM macOS and x86 Linux log10 differ by one ULP for the same PCM sample.
    This is a test-platform allowance, not a measurement rounding or QC margin.
    Integer sample positions, hashes, checks and statuses remain exact.
    """
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_baseline_matches(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert_baseline_matches(left, right)
    elif isinstance(expected, float):
        assert type(actual) is float
        assert abs(actual - expected) <= math.ulp(expected), (actual, expected)
    else:
        assert actual == expected


def test_baseline_allows_one_ulp_but_not_numeric_or_policy_regressions():
    expected = -1.8732272847067915
    adjacent = math.nextafter(expected, math.inf)
    assert_baseline_matches(adjacent, expected)
    for actual, original in ((math.nextafter(adjacent, math.inf), expected),
                             (2529768, 2529767), ("WARNING", "PASS")):
        with pytest.raises(AssertionError):
            assert_baseline_matches(actual, original)


@pytest.mark.integration
@pytest.mark.parametrize('case', CASES)
def test_pre_m3_reports_and_decisions_unchanged(tmp_path, case):
    source = tmp_path/'media'
    paths = baseline_media(source)
    policy = baseline_policy(case)
    files = [inspect_file(path, policy, with_hash=True) for path in paths]
    golden = json.loads((Path(__file__).parent/'fixtures'/'m3_baseline.json').read_text())
    expected = deepcopy(golden[case])
    for audio, previous in zip(files, expected):
        for check in previous['checks']:
            check['message'] = check['message'].replace('short, silent, below gate, or failed analysis', 'short, silent, below gate, or not measured')
        if audio.filename == 'broken.wav':
            # H3 intentionally moves the decode error out of acoustic checks.
            # Compare the exact original diagnostic and every other fact.
            prior = previous['checks'].pop(0)
            diagnostic, = audio.operational_diagnostics
            assert diagnostic.code == prior['code'] == 'inspection'
            assert diagnostic.message.replace(str(source), '<SOURCE>') == prior['message']
            assert diagnostic.required and diagnostic.affects_analysis
            assert audio.execution_status == 'FAILED'
            previous['status'] = 'INCOMPLETE'
        else:
            assert audio.execution_status == 'COMPLETED'
            assert not audio.operational_diagnostics
    assert_baseline_matches([normalized(audio, source) for audio in files], expected)
    report = build_report(source, files, [], policy, {}, 0)
    output = tmp_path/'reports'
    output.mkdir()
    write_reports(report, output)
    saved = json.loads((output/'QC_REPORT.json').read_text())
    assert saved['schema_version'] == 5
    assert saved['status'] == report['status']
    assert all((output/name).is_file() for name in ('QC_REPORT.html','QC_REPORT.csv','QC_DEFECTS.csv'))
    assert 'http://' not in (output/'QC_REPORT.html').read_text()
