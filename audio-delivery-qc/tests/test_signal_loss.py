"""Exact digital absence, independent of heuristic candidate detection."""
from copy import deepcopy
import numpy as np
import pytest

from audio_qc.signal_loss import StreamingSignalLoss, METHOD
from audio_qc.config import load_config
from audio_qc.models import AudioFile
from audio_qc.rules import assess_file, measurement_requirements


def collect(data, rate=1000, cap=1000, block=17, complete=True):
    stream = StreamingSignalLoss(rate, data.shape[1], {'min_duration_ms': 5, 'max_events': cap})
    for start in range(0, len(data), block):
        stream.feed(data[start:start+block])
    return stream.finish(complete=complete)


def test_long_drop_exact_interval_and_channels_across_blocks():
    data = np.ones((64000, 2)) * .1
    data[300:63700] = 0
    facts, events = collect(data)
    assert facts['complete'] and not facts['truncated']
    event, = events
    assert (event.sample_index, event.cluster_last_sample, event.duration_seconds) == (300, 63699, 63.4)
    assert event.measurements['end_sample_exclusive'] == 63700
    assert event.channels == [1, 2]
    assert event.severity is None
    assert all(e.severity is None for e in event.channel_events)


def test_categories_total_short_channel_and_edges():
    data = np.ones((100, 3))
    data[:, 0] = 0
    data[:10, 1] = 0
    data[90:, 2] = 0
    facts, events = collect(data)
    assert {e.measurements['kind'] for e in events} == {'TOTAL', 'LEADING', 'TRAILING'}
    assert facts['channel_event_counts'] == {'INTERNAL': 0, 'TOTAL': 1, 'LEADING': 1, 'TRAILING': 1}
    facts, events = collect(np.zeros((2, 2)))
    assert events[0].event_type == 'MOS (SILENT FILE)'
    assert events[0].channels == [1, 2]


def test_subthreshold_nonfinite_and_signed_zero():
    data = np.ones((100, 1))
    data[10:14] = 0
    data[20:30] = np.nan
    data[40:45] = -0.0
    _, events = collect(data)
    assert [e.sample_index for e in events] == [40]


def test_cap_counts_exact_consolidated_intervals_and_keeps_scanning():
    data = np.ones((200, 2))
    data[:10] = 0  # edge must not consume critical cap
    data[20:30] = data[50:60] = data[100:110] = 0
    facts, events = collect(data, cap=1)
    assert facts['checked_sample_frames'] == 200
    assert facts['channel_event_counts']['INTERNAL'] == 6
    assert facts['omitted_channel_events'] == 4 and facts['truncated']
    assert len(events) == 2
    assert all(e.channels == [1, 2] for e in events)


def test_interrupted_open_run_not_misclassified_as_total_or_trailing():
    facts, events = collect(np.zeros((100, 1)), complete=False)
    assert not facts['complete'] and not events
    assert facts['open_runs'] == [{'channel': 1, 'start_sample': 0, 'observed_end_sample_exclusive': 100}]


def test_policy_no_mutation_fail_coverage_and_execution_only_plan():
    config = load_config()
    assert not config['defects']['enabled']
    plan = measurement_requirements(config)
    assert plan.defect_options is None
    assert plan.signal_loss_options == {'min_duration_ms': 5, 'max_events': 1000}
    data = np.ones((100, 2)); data[20:50] = 0
    facts, events = collect(data)
    audio = AudioFile('test.wav', 'test.wav', sample_rate=1000, channels=2,
                      measurements={'signal_loss': facts}, defects=events)
    before = deepcopy(audio)
    result = assess_file(audio, config)
    assert next(c.status for c in result.checks if c.code == 'signal_loss_internal') == 'FAIL'
    assert result.defects[0].severity == 'FAIL'
    assert audio == before
    config['signal_loss']['fail_internal'] = False
    assert assess_file(audio, config).defects[0].severity == 'WARNING'
    config['signal_loss']['min_duration_ms'] = 1
    assert any(c.status == 'INCOMPLETE' for c in assess_file(audio, config).checks)


def test_missing_required_signal_measurement_cannot_pass():
    audio = AudioFile('test.wav', 'test.wav')
    result = assess_file(audio, load_config())
    assert result.status == 'INCOMPLETE'


@pytest.mark.integration
def test_scanner_critical_check_with_candidates_disabled(tmp_path):
    from audio_qc.synthetic import write_wav
    from audio_qc.scanner import inspect_file
    data = np.full((48000, 2), .01); data[12000:36000] = 0
    path = tmp_path / 'drop.wav'; write_wav(path, data)
    signature = (path.read_bytes(), path.stat().st_mtime_ns)
    config = load_config(); config['loudness']['enabled'] = False
    audio = inspect_file(path, config)
    event, = [e for e in audio.defects if e.detection_method == METHOD]
    assert (event.sample_index, event.measurements['end_sample_exclusive']) == (12000, 36000)
    assert audio.status == event.severity == 'FAIL'
    assert (path.read_bytes(), path.stat().st_mtime_ns) == signature


def test_tc_end_exclusive_bwf_and_html(tmp_path):
    from audio_qc.reports import build_report, write_reports
    from audio_qc.timecode import file_timecode
    data = np.full((96000, 2), .1); data[24000:72000] = 0
    facts, events = collect(data, rate=48000)
    config = load_config()
    audio = AudioFile('test.wav', 'test.wav', sample_rate=48000, channels=2,
                      bwf={'present': True, 'time_reference': 172800000},
                      measurements={'signal_loss': facts}, defects=events)
    audio = assess_file(audio, config)
    enriched = file_timecode(audio, config['timecode'])
    event = enriched['defects'][0]
    assert event['timecode'] == '01:00:00:12'
    assert event['end_timecode_exclusive'] == '01:00:01:12'
    assert 'end_timecode_exclusive' not in audio.defects[0].measurements
    report = build_report('test.wav', [audio], [], config, {}, 0)
    write_reports(report, tmp_path)
    html = (tmp_path/'QC_REPORT.html').read_text()
    assert 'Digital signal loss / MOS (Missing of sound)' in html
    assert 'End TC (exclusive)' in html and '24000–72000 (exclusive)' in html
    assert report['files'][0]['status'] == 'FAIL'


@pytest.mark.parametrize('failure', ['error', 'cancel'])
def test_partial_decode_preserves_closed_facts_and_no_false_complete(monkeypatch, failure):
    from contextlib import contextmanager
    from io import BytesIO
    from audio_qc.samples import analyze_samples
    from audio_qc.process import ToolError, ScanCancelled
    data = np.ones((100, 1)); data[20:40] = 0; data[60:] = 0
    @contextmanager
    def broken(*args, **kwargs):
        yield BytesIO(data.astype('<f8').tobytes())
        raise ToolError('decoder failed') if failure == 'error' else ScanCancelled()
    monkeypatch.setattr('audio_qc.samples.stream_process', broken)
    config = load_config()
    audio = AudioFile('test.wav', 'test.wav', channels=1, sample_rate=1000)
    with pytest.raises((ToolError, ScanCancelled)):
        analyze_samples('test.wav', audio, measurement_requirements(config))
    assert not audio.measurements['signal_loss']['complete']
    assert [e.sample_index for e in audio.defects] == [20]
    assert assess_file(audio, config).status == 'INCOMPLETE'


def test_frozen_click_configuration_compatibility(monkeypatch):
    import sys
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'scripts'))
    from click_experiment import audio
    assert audio.check_baseline()['configuration_compatibility']
    config = load_config(); config['defects']['clicks']['sensitivity'] = 'high'
    monkeypatch.setattr(audio, 'load_config', lambda: config)
    with pytest.raises(ValueError, match='baseline'):
        audio.check_baseline()


@pytest.mark.integration
def test_click_cap_does_not_hide_later_loss(tmp_path):
    from audio_qc.synthetic import sine, write_wav
    from audio_qc.scanner import inspect_file
    config = load_config(); config['loudness']['enabled'] = False
    config['defects'].update(enabled=True, max_candidates=1)
    data = sine(4, amplitude=.03, frequency=220)
    data[30000] += .7; data[80000] += .7
    data[120000:180000] = 0
    data[180000] = .03  # Force a nonzero exit; the quantized sine crosses zero here.
    audio = inspect_file(write_wav(tmp_path/'cap.wav', data), config)
    assert any(c.code == 'defects_capped' for c in audio.checks)
    assert audio.status == 'FAIL'
    event, = [e for e in audio.defects if e.detection_method == METHOD]
    assert (event.sample_index, event.measurements['end_sample_exclusive']) == (120000, 180000)
    assert audio.measurements['signal_loss']['checked_sample_frames'] == len(data)


def test_bounded_records_still_count_late_critical_and_total():
    data = np.ones((100000, 2))
    data[:, 1] = 0
    for first in range(10, 99990, 10):
        data[first:first+5, 0] = 0
    facts, events = collect(data, cap=3, block=8192)
    assert len(events) == 3 and facts['truncated']
    assert facts['channel_event_counts']['INTERNAL'] == 9998
    assert facts['channel_event_counts']['TOTAL'] == 1
    config = load_config()
    audio = AudioFile('bounded.wav', 'bounded.wav', sample_rate=1000, channels=2,
                      measurements={'signal_loss': facts}, defects=events)
    checks = assess_file(audio, config).checks
    assert next(c.status for c in checks if c.code == 'signal_loss_total') == 'FAIL'
    assert next(c.status for c in checks if c.code == 'signal_loss_records') == 'WARNING'


@pytest.mark.parametrize('block', [1, 8, 23, 1000])
def test_interval_results_independent_of_decode_block_size(block):
    data = np.ones((100, 2)); data[:10, 0] = 0; data[30:50] = 0; data[80:, 1] = 0
    assert collect(data, block=block) == collect(data, block=17)


@pytest.mark.parametrize('field,value', [('enabled', 'yes'), ('min_duration_ms', 0),
                                         ('min_duration_ms', float('nan')), ('max_events', True),
                                         ('max_events', 0), ('fail_total', 1)])
def test_strict_signal_configuration(field, value):
    from audio_qc.config import resolve_config, ConfigError
    with pytest.raises(ConfigError, match='signal_loss'):
        resolve_config({'signal_loss': {field: value}})


def test_edges_are_information_total_warning_config_and_explicit_disable():
    config = load_config()
    data = np.ones((100, 2)); data[:10, 0] = 0; data[90:, 1] = 0
    facts, events = collect(data)
    audio = AudioFile('edges.wav', 'edges.wav', sample_rate=1000, channels=2,
                      measurements={'signal_loss': facts}, defects=events)
    assert all(e.severity == 'INFO' for e in assess_file(audio, config).defects)
    facts, events = collect(np.zeros((100, 2)))
    audio.measurements['signal_loss'], audio.defects = facts, events
    config['signal_loss']['fail_total'] = False
    assert assess_file(audio, config).defects[0].severity == 'WARNING'
    config['signal_loss']['enabled'] = False
    assert measurement_requirements(config).signal_loss_options is None
    assert not assess_file(audio, config).defects
