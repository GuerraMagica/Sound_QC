import errno
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager

import pytest

from audio_qc.cli import main
from audio_qc.config import ConfigError, load_config
from audio_qc.diagnostics import SafeFileHandler
from audio_qc.models import AudioFile
from audio_qc.process import ToolError, ffmpeg_input, stream_process
from audio_qc.scanner import inspect_file
from audio_qc.synthetic import sine, write_wav


@pytest.fixture
def scan(tmp_path, monkeypatch):
    source = tmp_path / 'input'
    source.mkdir()
    monkeypatch.setattr('audio_qc.cli.check_tools', lambda: {})
    return source, tmp_path / 'report'


def test_unexpected_report_error_has_traceback_only_in_log(scan, monkeypatch, capsys):
    source, output = scan
    def fail(*args):
        raise RuntimeError('report renderer failed')
    monkeypatch.setattr('audio_qc.cli.write_reports', fail)
    assert main([str(source), '--output', str(output)]) == 2
    console = capsys.readouterr()
    assert 'An unexpected error occurred' in console.err and 'Check error.log' in console.err
    assert 'Traceback' not in console.err and 'HTML report:' not in console.out
    diagnostic = (output / 'error.log').read_text()
    assert 'Traceback' in diagnostic and 'RuntimeError: report renderer failed' in diagnostic


@pytest.mark.parametrize('error', [OSError(errno.ENOSPC, 'No space left'), PermissionError(errno.EACCES, 'Permission denied')])
def test_report_io_failure_is_not_success(scan, monkeypatch, capsys, error):
    source, output = scan
    def fail(*args):
        raise error
    monkeypatch.setattr('audio_qc.cli.write_reports', fail)
    assert main([str(source), '--output', str(output)]) == 2
    console = capsys.readouterr()
    assert str(error) in console.err
    assert 'HTML report:' not in console.out and 'Traceback' not in console.err
    assert str(error) in (output / 'error.log').read_text()


def test_disk_full_also_prevents_logs_without_secondary_traceback(scan, monkeypatch, capsys):
    source, output = scan
    def no_space(*args):
        raise OSError(errno.ENOSPC, 'disk full')
    monkeypatch.setattr(SafeFileHandler, '_open', no_space)
    monkeypatch.setattr('audio_qc.cli.write_reports', no_space)
    assert main([str(source), '--output', str(output), '--verbose']) == 2
    console = capsys.readouterr()
    assert 'disk full' in console.err and 'Cannot write' in console.err
    assert 'Traceback' not in console.err and 'Logging error' not in console.err
    assert 'HTML report:' not in console.out


def test_unexpected_error_before_output_has_honest_message(scan, monkeypatch, capsys):
    source, output = scan
    def fail(*args):
        raise RuntimeError('dependency lookup failed')
    monkeypatch.setattr('audio_qc.cli.check_tools', fail)
    assert main([str(source), '--output', str(output)]) == 2
    message = capsys.readouterr().err
    assert 'could not be saved' in message and 'Check error.log' not in message
    assert 'Traceback' not in message and not output.exists()


def test_existing_output_is_not_used_for_logs(scan, capsys):
    source, output = scan
    output.mkdir()
    sentinel = output / 'error.log'
    sentinel.write_text('existing evidence')
    assert main([str(source), '--output', str(output)]) == 2
    assert sentinel.read_text() == 'existing evidence'
    assert not (output / 'scan.log').exists()


def test_directory_creation_denied_does_not_write_into_source(scan, monkeypatch, capsys):
    source, output = scan
    def denied(*args):
        raise PermissionError('report directory denied')
    monkeypatch.setattr('audio_qc.cli.create_output', denied)
    assert main([str(source), '--output', str(output)]) == 2
    assert 'report directory denied' in capsys.readouterr().err
    assert list(source.iterdir()) == []


def test_log_failure_remains_visible_in_report(scan, monkeypatch, capsys):
    source, output = scan
    def denied(*args):
        raise PermissionError('log denied')
    monkeypatch.setattr(SafeFileHandler, '_open', denied)
    assert main([str(source), '--output', str(output)]) == 0
    report = json.loads((output / 'QC_REPORT.json').read_text())
    assert any(c['code'] == 'diagnostic_log' for c in report['operational_diagnostics'])
    assert 'log denied' in capsys.readouterr().err


def test_per_file_error_continues_and_preserves_previous_measurements(scan, monkeypatch, capsys):
    source, output = scan
    paths = [source / 'one.wav', source / 'two.wav']
    for path in paths:
        path.write_bytes(b'fixture')
    calls = []
    def inspect(path, *args):
        calls.append(path)
        return AudioFile(str(path), path.name, measurements={'integrated_lufs': -23.125})
    def export(audio, *args):
        if audio.filename == 'one.wav':
            raise RuntimeError('export bug')
    monkeypatch.setattr('audio_qc.cli.inspect_file', inspect)
    monkeypatch.setattr('audio_qc.cli.export_snippets', export)
    assert main([str(source), '--output', str(output), '--export-defect-snippets']) == 2
    report = json.loads((output / 'QC_REPORT.json').read_text())
    assert len(calls) == 2 and report['files'][0]['status'] == 'INFO'
    assert all(a['measurements']['integrated_lufs'] == -23.125 for a in report['files'])
    assert 'export bug' in (output / 'error.log').read_text()
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('options,visible', [([], False), (['--quiet'], False), (['--verbose'], True)])
def test_verbosity_and_repeated_invocations_have_no_duplicate_handlers(scan, capsys, options, visible):
    source, output = scan
    for i in range(2):
        target = output.with_name(f'report-{i}')
        assert main([str(source), '--output', str(target), *options]) == 0
        text = capsys.readouterr().out
        assert text.count('HTML report:') == 1
        assert ('AUDIO DELIVERY QC INSPECTOR' in text) == visible
        assert 'DEBUG AUDIO DELIVERY QC INSPECTOR' in (target / 'scan.log').read_text()
        assert not (target / 'error.log').exists()


@pytest.mark.parametrize('yaml,field,line', [
    ('true_peak_limit: -1\n', 'true_peak_limit', 1),
    ('sample_rate:\n  required: wrong\n', 'sample_rate.required', 2),
    ('loudness:\n  enabled: no_thanks\n', 'loudness.enabled', 2),
    ('true_peak:\n  maximum: .nan\n', 'true_peak.maximum', 2),
    ('channels:\n  allowed: [0, 2]\n', 'channels.allowed', 2),
    ('defects:\n  clicks:\n    surprise: true\n', 'defects.clicks.surprise', 3),
    ('preset: nope\n', 'preset', 1),
])
def test_yaml_errors_identify_path_field_and_line(tmp_path, yaml, field, line):
    path = tmp_path / 'Especificación.yaml'
    path.write_text(yaml)
    with pytest.raises(ConfigError) as result:
        load_config(path)
    assert field in str(result.value) and f'line {line}, column' in str(result.value)
    assert path.name in str(result.value)


def test_duplicate_yaml_key_has_location(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text('preset: CUSTOM\npreset: FILM_48K\n')
    with pytest.raises(ConfigError, match='line 2, column 1'):
        load_config(path)


def test_cancel_reaps_process(monkeypatch):
    real = subprocess.Popen
    processes = []
    def launch(*args, **kwargs):
        proc = real(*args, **kwargs)
        processes.append(proc)
        return proc
    monkeypatch.setattr('audio_qc.process.subprocess.Popen', launch)
    with pytest.raises(KeyboardInterrupt):
        with stream_process([sys.executable, '-c', 'import time; time.sleep(60)']):
            raise KeyboardInterrupt()
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


def test_cli_cancellation_is_not_an_unexpected_error(scan, monkeypatch, capsys):
    source, output = scan
    def cancel(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr('audio_qc.cli.group_checks', cancel)
    assert main([str(source), '--output', str(output)]) == 130
    assert 'cancelled' in capsys.readouterr().err
    assert not (output / 'error.log').exists()


def test_literal_filename_arguments_and_output_symlink_guard(tmp_path):
    name = tmp_path / 'audio ; $(touch injected) 日本語.wav'
    args = ffmpeg_input(name)
    assert args[args.index('-i') + 1] == str(name)
    assert args[args.index('-protocol_whitelist') + 1] == 'file,pipe'
    source = tmp_path / 'input'
    source.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(source, target_is_directory=True)
    from audio_qc.cli import create_output
    with pytest.raises(ValueError, match='outside'):
        create_output(source, alias / 'report')


@pytest.mark.integration
def test_failed_ffmpeg_summary_never_becomes_valid_measurement(wav, config, monkeypatch):
    @contextmanager
    def failed(args, timeout, feed):
        for line in ('lavfi.r128.I=-23.0', 'Summary:', 'True peak:', 'Peak: -1.0 dBFS'):
            feed(line)
        raise ToolError('decoder failed after partial summary')
        yield  # pragma: no cover
    monkeypatch.setattr('audio_qc.loudness.stream_process', failed)
    audio = inspect_file(wav, config)
    assert audio.measurements.get('integrated_lufs') is None
    assert audio.measurements.get('true_peak_dbtp') is None
    assert 'decoder failed' in audio.measurements['loudness_unavailable']
    assert next(c for c in audio.checks if c.code == 'integrated_loudness').status == 'INCOMPLETE'
    assert audio.execution_status == 'PARTIAL'


@pytest.mark.integration
def test_out_of_spec_bwf_without_ixml_is_measured_read_only(tmp_path):
    path = write_wav(tmp_path / 'BWF without iXML.wav', sine(amplitude=.5), bext=True)
    def fingerprint():
        return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, path.stat().st_mtime_ns
    before = fingerprint()
    assert b'iXML' not in path.read_bytes()
    audio = inspect_file(path, load_config(preset='BROADCAST_EBU_R128'))
    assert audio.bwf['present'] is True
    assert next(c for c in audio.checks if c.code == 'bwf').status == 'PASS'
    assert next(c for c in audio.checks if c.code == 'integrated_loudness').status == 'FAIL'
    assert fingerprint() == before
