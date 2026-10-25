"""Preserve real measured facts when orchestration or hashing is interrupted."""
import hashlib
import json
from copy import deepcopy

import pytest

from audio_qc import cli, scanner
from audio_qc.config import load_config
from audio_qc.process import CancellationToken
from audio_qc.synthetic import sine, write_wav


def fingerprint(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


@pytest.mark.integration
@pytest.mark.parametrize('stage', ['group_checks', 'build_programmes', 'build_report'])
@pytest.mark.parametrize('error_type', [RuntimeError, OSError])
def test_pre_report_failure_preserves_facts_without_retry(tmp_path, monkeypatch, stage, error_type):
    source = write_wav(tmp_path/'source.wav', sine(), bext=True)
    before = fingerprint(source)
    measured = scanner.inspect_file(source, load_config())
    original = deepcopy(measured)
    # Reuse completed real measurements; only inject the orchestration failure.
    monkeypatch.setattr(cli, 'inspect_file', lambda *a, **k: measured)
    calls = []
    def fail(*args, **kwargs):
        calls.append(stage)
        raise error_type('controlled pre-report failure')
    monkeypatch.setattr(cli, stage, fail)
    output = tmp_path/'report'
    assert cli.main([str(source), '--output', str(output)]) == 2
    saved = json.loads((output/'QC_RECOVERY.json').read_text())
    assert saved['files'][0]['measurements'] == measured.measurements
    assert saved['files'][0]['checks'] == measured.to_dict()['checks']
    assert saved['audio_compliance'] == 'INCOMPLETE'
    assert saved['execution_status'] == 'FAILED'
    assert any('controlled pre-report failure' in d['message'] for d in saved['operational_diagnostics'])
    assert not (output/'QC_COMPLETE.json').exists()
    assert calls == [stage]  # Recovery must not retry the failed stage.
    assert measured == original and fingerprint(source) == before


@pytest.mark.integration
def test_failure_between_programmes_preserves_completed_and_marks_pending(tmp_path, monkeypatch):
    from m6_fixtures import make_programme_fixture
    for name in ('one', 'two'):
        make_programme_fixture(tmp_path/'sources'/name, layout='stereo', seconds=1)
    original = cli.measure_programme
    completed = []
    def fail_second(*args, **kwargs):
        if completed:
            raise RuntimeError('second programme failed unexpectedly')
        value = original(*args, **kwargs)
        completed.append(deepcopy(value))
        return value
    monkeypatch.setattr(cli, 'measure_programme', fail_second)
    output = tmp_path/'report'
    assert cli.main([str(tmp_path/'sources'), '--detect-groups', '--no-defects', '--output', str(output)]) == 2
    saved = json.loads((output/'QC_RECOVERY.json').read_text())
    groups = saved['programme_groups']
    assert [g['programme_measurement']['state'] for g in groups] == ['SUCCESS', 'NOT_EVALUATED']
    assert groups[0]['programme_measurement']['measurements'] == completed[0].measurements
    assert saved['programme_compliance'] == 'NOT_EVALUATED'
    assert saved['programme_group_configuration'] is not None
    assert not (output/'QC_COMPLETE.json').exists()


@pytest.mark.integration
@pytest.mark.parametrize('interruption', ['keyboard', 'token'])
@pytest.mark.parametrize('file_number', [1, 2])
def test_hash_cancellation_keeps_current_file_and_previous_results(tmp_path, monkeypatch, interruption, file_number):
    sources = tmp_path/'sources'
    paths = [write_wav(sources/f'{i}.wav', sine(amplitude=.8), bext=True) for i in (1, 2)]
    fingerprints = [fingerprint(p) for p in paths]
    baseline = scanner.inspect_file(paths[0], load_config(preset='BROADCAST_EBU_R128'), with_hash=True)
    original_hash = scanner.sha256_file
    calls = []
    def interrupt_hash(path, progress=None, **kwargs):
        calls.append(path)
        if len(calls) == file_number:
            if interruption == 'keyboard':
                raise KeyboardInterrupt()
            token = CancellationToken()
            token.cancel()
            return original_hash(path, progress, cancel=token)
        return original_hash(path, progress, **kwargs)
    monkeypatch.setattr(scanner, 'sha256_file', interrupt_hash)
    output = tmp_path/'report'
    assert cli.main([str(sources), '--hash', '--preset', 'BROADCAST_EBU_R128', '--output', str(output)]) == 130
    saved = json.loads((output/'QC_RECOVERY.json').read_text())
    assert len(saved['files']) == file_number
    current = saved['files'][-1]
    assert current['measurements'] == baseline.measurements
    assert current['audio_sha256'] == baseline.audio_sha256
    assert current['measurement_outcomes']['samples']['state'] == 'SUCCESS'
    assert current['measurement_outcomes']['integrated_lufs']['state'] == 'SUCCESS'
    assert current['sha256'] is None
    assert current['checks'] == baseline.to_dict()['checks']  # Genuine QC failures survive.
    assert any(c['status'] == 'FAIL' for c in current['checks'])
    assert any(d['code'] == 'hash_cancelled' and d['required'] for d in current['operational_diagnostics'])
    if file_number == 2:
        assert saved['files'][0]['sha256'] == fingerprints[0][0]
    assert saved['audio_compliance'] == 'INCOMPLETE'
    assert not (output/'QC_COMPLETE.json').exists()
    assert [fingerprint(p) for p in paths] == fingerprints


@pytest.mark.integration
def test_recovery_write_failure_stays_operational(tmp_path, monkeypatch, capsys):
    source = write_wav(tmp_path/'source.wav', sine(), bext=True)
    before = fingerprint(source)
    def fail(*args, **kwargs):
        raise RuntimeError('group construction failure')
    def disk_full(*args, **kwargs):
        raise OSError('controlled disk full during recovery')
    monkeypatch.setattr(cli, 'build_programmes', fail)
    monkeypatch.setattr(cli, 'write_recovery', disk_full)
    output = tmp_path/'report'
    assert cli.main([str(source), '--output', str(output)]) == 2
    console = capsys.readouterr()
    assert 'Recovery data could not be saved' in console.err
    assert 'Traceback' not in console.err and 'HTML report:' not in console.out
    assert not (output/'QC_COMPLETE.json').exists()
    assert fingerprint(source) == before


@pytest.mark.integration
def test_programme_assessment_failure_retains_measured_programme(tmp_path, monkeypatch):
    from m6_fixtures import make_programme_fixture
    fixture = make_programme_fixture(tmp_path/'fixture', layout='stereo', seconds=4)
    sources = list(fixture['members'].values())
    before = [fingerprint(p) for p in sources]
    def fail(*args, **kwargs):
        raise RuntimeError('controlled programme assessment failure')
    monkeypatch.setattr(cli, 'assess_programme', fail)
    output = tmp_path/'report'
    assert cli.main([str(tmp_path/'fixture'/'sources'), '--groups', str(fixture['manifest']),
                     '--no-defects', '--output', str(output)]) == 2
    saved = json.loads((output/'QC_RECOVERY.json').read_text())
    group, = saved['programme_groups']
    assert group['programme_measurement']['state'] == 'SUCCESS'
    assert group['programme_measurement']['measurements']['decoded_sample_frames'] == 192000
    assert group['combined_programme_loudness'] == 'SUCCESS'
    assert group['combined_true_peak'] == 'SUCCESS'
    assert group['programme_compliance'] == 'NOT_EVALUATED'
    assert saved['audio_compliance'] == 'INCOMPLETE'
    assert [fingerprint(p) for p in sources] == before


@pytest.mark.integration
def test_hash_cancellation_keeps_source_guard_and_raw_measurement_boundary(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from audio_qc.measurement import MeasurementRequirements
    source = write_wav(tmp_path/'source.wav', sine(), bext=True)
    before = fingerprint(source)
    original_stat = type(source).stat
    changed = False
    def stat(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path == source and changed:
            return SimpleNamespace(st_size=value.st_size, st_mtime_ns=value.st_mtime_ns+1, st_ino=value.st_ino)
        return value
    def cancel_hash(*args, **kwargs):
        nonlocal changed
        changed = True  # Simulate an external change without touching the WAV.
        raise KeyboardInterrupt()
    monkeypatch.setattr(type(source), 'stat', stat)
    monkeypatch.setattr(scanner, 'sha256_file', cancel_hash)
    with pytest.raises(scanner.FileScanCancelled) as caught:
        scanner.measure_file(source, MeasurementRequirements(True, True, None, hash=True))
    facts = caught.value.audio
    assert facts.measurement_outcomes['samples'].state == 'SUCCESS'
    assert facts.sha256 is None
    assert caught.value.context.source_change_error is not None
    assert not any(c.code == 'integrated_loudness' for c in facts.checks)  # No QC policy during measurement.
    changed = False
    with pytest.raises(scanner.FileScanCancelled) as caught:
        scanner.inspect_file(source, load_config(), with_hash=True)
    assessed = caught.value.audio
    assert any(d.code == 'source_changed' for d in assessed.operational_diagnostics)
    assert assessed.status == 'INCOMPLETE'
    changed = False
    assert fingerprint(source) == before
