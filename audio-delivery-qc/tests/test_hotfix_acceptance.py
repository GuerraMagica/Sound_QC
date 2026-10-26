"""Release gate: execution failures must not masquerade as acoustic decisions."""
from contextlib import contextmanager
from copy import deepcopy
import errno
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from audio_qc.cli import main
from audio_qc.config import load_config
from audio_qc.diagnostics import RunLog, SafeFileHandler
from audio_qc.loudness import LoudnessParser
from audio_qc.models import MeasurementState as MS
from audio_qc.process import ToolError, stream_process
from audio_qc.rules import assess_file, measurement_requirements
from audio_qc.scanner import inspect_file, measure_file
from audio_qc.synthetic import sine, write_wav


def fingerprint(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


@pytest.fixture
def media(tmp_path):
    paths = {
        'valid': write_wav(tmp_path/'valid.wav', sine(), bext=True),
        'silent': write_wav(tmp_path/'silent.wav', np.zeros((192000, 1)), bext=True),
    }
    clicks = sine()
    clicks[48000] += .6
    paths['click'] = write_wav(tmp_path/'click.wav', clicks, bext=True)
    before = {k: fingerprint(p) for k, p in paths.items()}
    yield paths
    assert {k: fingerprint(p) for k, p in paths.items()} == before


def run(source, output, *options):
    code = main(['inspect', str(source), '--preset', 'BROADCAST_EBU_R128', '--output', str(output), *options])
    report = json.loads((output/'QC_REPORT.json').read_text())
    html = (output/'QC_REPORT.html').read_text()
    assert f'>{report["audio_compliance"]}</span>' in html
    assert f'Execution: <b>{report["execution_status"]}</b>' in html
    assert report['status'] == report['audio_compliance']
    marker = json.loads((output/'QC_COMPLETE.json').read_text())
    assert marker['execution_status'] == report['execution_status']
    assert all((output/name).is_file() for name in marker['reports'])
    return code, report, html


def fake_stream(lines):
    @contextmanager
    def stream(args, timeout, feed):
        for line in lines:
            feed(line)
        yield BytesIO()
    return stream


@pytest.mark.integration
def test_valid_success_and_undefined_are_distinct(media, tmp_path):
    for name, expected, state in [('valid', 'PASS', 'SUCCESS'), ('silent', 'FAIL', 'UNAVAILABLE')]:
        code, report, html = run(media[name], tmp_path/name)
        audio, = report['files']
        assert code == (1 if name == 'silent' else 0) and report['audio_compliance'] == expected
        assert report['execution_status'] == 'COMPLETED'
        assert audio['measurement_outcomes']['integrated_lufs']['state'] == state
        assert state in html and not audio['operational_diagnostics']
        if name == 'silent':
            assert any(c['code'] == 'signal_loss_total' and c['status'] == 'FAIL' for c in audio['checks'])
            assert audio['measurements']['integrated_lufs'] is None
            assert audio['measurements']['true_peak_dbtp'] is None
        else:
            assert audio['measurements']['integrated_lufs'] == pytest.approx(-23, abs=.1)
            assert audio['measurements']['true_peak_dbtp'] == -20


@pytest.mark.integration
@pytest.mark.parametrize('setting,code_name', [('loudness:\n  target_lufs: -30\n', 'integrated_loudness'),
                                               ('true_peak:\n  maximum: -25\n', 'true_peak')])
def test_real_noncompliance_is_completed(media, tmp_path, setting, code_name):
    config = tmp_path/'policy.yaml'
    config.write_text(setting)
    code, report, _ = run(media['valid'], tmp_path/'out', '--config', str(config))
    assert code == 1 and report['audio_compliance'] == 'FAIL'
    assert report['execution_status'] == 'COMPLETED'
    audio, = report['files']
    assert any(c['code'] == code_name and c['status'] == 'FAIL' for c in audio['checks'])
    assert not audio['operational_diagnostics']


@pytest.mark.integration
@pytest.mark.parametrize('error', [ToolError('FFmpeg decoder failed'), ToolError('Process exceeded configured timeout (1s)'), PermissionError('Cannot launch FFmpeg')])
def test_requested_measurement_failure_is_incomplete(media, tmp_path, monkeypatch, error):
    monkeypatch.setattr('audio_qc.scanner.measure_loudness', lambda *a: (_ for _ in ()).throw(error))
    code, report, html = run(media['valid'], tmp_path/'out')
    audio, = report['files']
    assert code == 2 and report['audio_compliance'] == 'INCOMPLETE'
    assert report['execution_status'] == 'PARTIAL'
    assert audio['measurement_outcomes']['integrated_lufs']['state'] == 'ERROR'
    assert audio['measurement_outcomes']['samples']['state'] == 'SUCCESS'
    assert audio['measurements']['decoded_sample_frames'] == 192000
    assert not any(c['status'] == 'FAIL' for c in audio['checks'])
    assert str(error) in html and audio['operational_diagnostics']


@pytest.mark.integration
@pytest.mark.parametrize('lines', [
    [], ['Summary:', 'True peak:', 'Peak: -20 dBFS'],
    ['lavfi.r128.I=-23', 'Summary:'],
    ['lavfi.r128.I=-23', 'lavfi.r128.I=nan', 'Summary:', 'True peak:', 'Peak: -20 dBFS'],
    ['lavfi.r128.I=-23', 'lavfi.r128.I=broken', 'Summary:', 'True peak:', 'Peak: -20 dBFS'],
    ['lavfi.r128.I=-23oops', 'Summary:', 'True peak:', 'Peak: -20 dBFS'],
    ['lavfi.r128.I=-23', 'Summary:', 'True peak:', 'Peak: nan dBFS'],
    ['lavfi.r128.I=-23', 'Summary:', 'True peak:', 'Peak: inf dBFS'],
    ['lavfi.r128.I=-23', 'Summary:', 'True peak:', 'Peak: nope dBFS'],
    ['lavfi.r128.I=-23', 'Summary:', 'True peak:', 'Peak: -20 dBFS', 'Summary:'],
])
def test_malformed_or_missing_output_never_passes(media, tmp_path, monkeypatch, lines):
    monkeypatch.setattr('audio_qc.loudness.stream_process', fake_stream(lines))
    code, report, _ = run(media['valid'], tmp_path/'out')
    assert code == 2 and report['status'] == 'INCOMPLETE'
    audio, = report['files']
    assert any(v['state'] == 'ERROR' for v in audio['measurement_outcomes'].values())
    for metric, outcome in audio['measurement_outcomes'].items():
        if outcome['state'] == 'ERROR':
            assert audio['measurements'].get(metric) is None


@pytest.mark.integration
def test_actual_subprocess_timeout_reaches_execution_status(media, tmp_path, monkeypatch):
    @contextmanager
    def timed(args, timeout, feed):
        with stream_process([sys.executable, '-c', 'import time; time.sleep(10)'], .05, feed) as pipe:
            yield pipe
    monkeypatch.setattr('audio_qc.loudness.stream_process', timed)
    code, report, _ = run(media['valid'], tmp_path/'out')
    assert code == 2 and report['execution_status'] == 'PARTIAL'
    assert 'timeout' in report['files'][0]['operational_diagnostics'][0]['message']


@pytest.mark.integration
@pytest.mark.parametrize('kind', ['permission', 'unexpected', 'ffmpeg', 'directory'])
def test_evidence_error_preserves_acoustic_findings(media, tmp_path, monkeypatch, kind):
    policy = load_config(preset='BROADCAST_EBU_R128')
    policy['defects']['enabled'] = True
    baseline = inspect_file(media['click'], policy)
    if kind == 'directory':
        mkdir = Path.mkdir
        def denied(path, *args, **kwargs):
            if path.name == 'defect_snippets':
                raise PermissionError('Evidence error')
            return mkdir(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'mkdir', denied)
    elif kind == 'ffmpeg':
        monkeypatch.setattr('audio_qc.snippets.stream_process', lambda *a: (_ for _ in ()).throw(ToolError('Evidence error')))
    else:
        error = PermissionError('Evidence error') if kind == 'permission' else RuntimeError('Evidence error')
        monkeypatch.setattr('audio_qc.cli.export_snippets', lambda *a: (_ for _ in ()).throw(error))
    code, report, html = run(media['click'], tmp_path/'out', '--export-defect-snippets')
    audio, = report['files']
    assert code == 2 and report['execution_status'] == 'PARTIAL'
    assert report['status'] == 'WARNING'  # The actual click candidate still needs review.
    assert audio['measurements'] == baseline.measurements
    assert len(audio['defects']) == 1 and audio['defects'][0]['severity'] == 'WARNING'
    assert not any(c['status'] == 'FAIL' for c in audio['checks'])
    assert audio['operational_diagnostics'][0]['code'] == 'snippet_export'
    assert 'Evidence error' in html


@pytest.mark.integration
def test_acoustic_fail_survives_other_metric_error(media, tmp_path, monkeypatch):
    monkeypatch.setattr('audio_qc.loudness.stream_process', fake_stream(['lavfi.r128.I=-14', 'Summary:']))
    code, report, _ = run(media['valid'], tmp_path/'out')
    assert code == 2 and report['status'] == 'INCOMPLETE'
    assert any(c['code'] == 'integrated_loudness' and c['status'] == 'FAIL' for c in report['files'][0]['checks'])


@pytest.mark.integration
@pytest.mark.parametrize('error', [OSError(errno.ENOSPC, 'disk full'), PermissionError(errno.EACCES, 'denied'), RuntimeError('renderer failed')])
def test_report_failure_preserves_recovery_and_never_announces_success(media, tmp_path, monkeypatch, capsys, error):
    monkeypatch.setattr('audio_qc.reports.write_html', lambda *a: (_ for _ in ()).throw(error))
    output = tmp_path/'out'
    assert main([str(media['valid']), '--output', str(output)]) == 2
    assert not (output/'QC_COMPLETE.json').exists()
    assert 'HTML report:' not in capsys.readouterr().out
    recovery = json.loads((output/'QC_RECOVERY.json').read_text())
    assert recovery['audio_compliance'] == 'PASS' and recovery['execution_status'] == 'FAILED'
    assert recovery['files'][0]['measurements']['integrated_lufs'] is not None
    assert recovery['operational_diagnostics'][-1]['code'] == 'report_export'


@pytest.mark.integration
def test_optional_log_failure_is_not_acoustic_failure(media, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(SafeFileHandler, '_open', lambda *a: (_ for _ in ()).throw(PermissionError('log denied')))
    code, report, html = run(media['valid'], tmp_path/'out')
    assert code == 0 and report['status'] == 'PASS'
    assert report['execution_status'] == 'COMPLETED_WITH_WARNINGS'
    assert report['operational_diagnostics'][0]['code'] == 'diagnostic_log'
    assert 'log denied' in html
    error = capsys.readouterr().err
    assert error.count('Cannot write') == 1
    assert 'Traceback' not in error and 'Logging error' not in error


@pytest.mark.integration
def test_late_log_failure_is_console_only_snapshot_policy(media, tmp_path, monkeypatch, capsys):
    real_emit = SafeFileHandler.emit
    def emit(handler, record):
        if record.getMessage().startswith('HTML report:'):
            handler.failure = 'late log failure'
        else:
            real_emit(handler, record)
    monkeypatch.setattr(SafeFileHandler, 'emit', emit)
    code, report, html = run(media['valid'], tmp_path/'out')
    assert code == 0 and report['status'] == 'PASS' and report['execution_status'] == 'COMPLETED'
    assert not report['operational_diagnostics'] and 'late log failure' not in html
    assert 'late log failure' in capsys.readouterr().err


@pytest.mark.parametrize('path', ['/reports/error.log', r'C:\reports\error.log', r'\\server\share\error.log'])
def test_error_log_identity_is_independent_of_path(tmp_path, capsys, path):
    logs = RunLog()
    logs.attach(tmp_path)
    assert not logs.error_saved()
    logs.logger.error('test diagnostic')
    handler = logs.error_handler
    original = handler.baseFilename
    handler.baseFilename = path
    try:
        assert logs.error_saved()
        handler.failure = 'write failed'
        assert not logs.error_saved()
    finally:
        handler.baseFilename = original
        logs.close()
    assert not logs.logger.handlers


def test_log_close_failure_reaches_stderr_without_logging_recursion(tmp_path, monkeypatch, capsys):
    logs = RunLog()
    logs.attach(tmp_path)
    logs.logger.info('start')
    handler = logs.files[0]
    real_close = handler.close
    monkeypatch.setattr(handler, 'close', lambda: (_ for _ in ()).throw(OSError('close failed')))
    logs.close()
    error = capsys.readouterr().err
    assert error.count('Cannot close diagnostic log: close failed') == 1
    assert not logs.logger.handlers
    real_close()
    monkeypatch.undo()


@pytest.mark.integration
def test_policy_assessment_does_not_mutate_outcomes_or_measurements(media):
    config = load_config()
    measured, context = measure_file(media['valid'], measurement_requirements(config))
    before = deepcopy(measured)
    result = assess_file(measured, config, context)
    assert measured == before and measured is not result
    assert measured.measurement_outcomes['integrated_lufs'].state == MS.SUCCESS


def test_negative_infinity_is_legitimately_undefined_not_nan_error():
    parser = LoudnessParser()
    for line in ('lavfi.r128.I=-inf', 'lavfi.r128.M=-inf', 'lavfi.r128.S=-inf',
                 'Summary:', 'True peak:', 'Peak: -inf dBFS'):
        parser.feed(line)
    measured = parser.result(4)
    assert measured['integrated_lufs'] is None and measured['true_peak_dbtp'] is None
    assert all(o.state == MS.UNAVAILABLE for o in measured['measurement_outcomes'].values())


def test_corrupt_metadata_does_not_expose_partial_loudness_maxima():
    parser = LoudnessParser()
    for line in ('pts_time:3.9', 'lavfi.r128.M=-23', 'lavfi.r128.S=-23',
                 'lavfi.r128.I=-23', 'lavfi.r128.I=nan', 'Summary:', 'True peak:', 'Peak: -20 dBFS'):
        parser.feed(line)
    result = parser.result(4)
    assert result['measurement_outcomes']['integrated_lufs'].state == MS.ERROR
    assert all(result[k] is None for k in ('integrated_lufs','lra_lu','max_momentary_lufs','max_short_term_lufs'))
    assert result['true_peak_dbtp'] == -20


@pytest.mark.integration
def test_partial_completion_marker_cannot_certify_report_delivery(media, tmp_path, monkeypatch):
    from audio_qc.reports import write_json
    def write(report, path):
        if path.name == '.QC_COMPLETE.json.tmp':
            path.write_text('{')
            raise OSError(errno.ENOSPC, 'marker disk full')
        write_json(report, path)
    monkeypatch.setattr('audio_qc.reports.write_json', write)
    output = tmp_path/'out'
    assert main([str(media['valid']), '--output', str(output)]) == 2
    assert (output/'QC_REPORT.html').exists()
    assert not (output/'QC_COMPLETE.json').exists()
    recovery = json.loads((output/'QC_RECOVERY.json').read_text())
    assert recovery['execution_status'] == 'FAILED'
