import ast
import builtins
from copy import deepcopy
from dataclasses import asdict
import io
import os
from pathlib import Path
import subprocess

import pytest

from audio_qc.config import load_config
from audio_qc.measurement import MeasurementContext
from audio_qc.models import AudioFile, Defect
from audio_qc.process import ToolError
from audio_qc.rules import assess_file, evaluate_file_policy, measurement_requirements
from audio_qc.scanner import measure_file, inspect_file


def test_pure_policy_never_opens_audio_or_executes_processes(monkeypatch, config):
    audio = AudioFile('/missing/source.wav','source.wav', sample_rate=48000, bit_depth=24,
                      measurements={'integrated_lufs':-23.0,'true_peak_dbtp':-1.5})
    context = MeasurementContext()
    before = deepcopy((asdict(audio), config, asdict(context)))
    def forbidden(*args, **kwargs):
        pytest.fail('Policy attempted filesystem or process I/O')
    with monkeypatch.context() as patch:
        for owner, name in [(builtins,'open'),(io,'open'),(os,'open'),(Path,'open'),(Path,'read_bytes'),
                            (subprocess,'Popen'),(subprocess,'run')]:
            patch.setattr(owner,name,forbidden)
        for name in ('audio_qc.process.stream_process','audio_qc.scanner.measure_loudness',
                     'audio_qc.scanner.analyze_samples','audio_qc.scanner.inspect_metadata',
                     'audio_qc.scanner.inspect_bwf','audio_qc.scanner.sha256_file'):
            patch.setattr(name,forbidden)
        first = evaluate_file_policy(audio,config,context)
        for _ in range(3):
            assert evaluate_file_policy(audio,config,context) == first
            assert assess_file(audio,config,context).checks == first
    assert (asdict(audio), config, asdict(context)) == before


@pytest.mark.parametrize('enabled,maximum,ebur128', [(True,None,True),(True,-1,True),
                                                   (False,None,False),(False,-6,True)])
def test_requirements_schedule_combined_level_pass(config, enabled, maximum, ebur128):
    config['loudness']['enabled'] = enabled
    config['true_peak']['maximum'] = maximum
    plan = measurement_requirements(config, with_hash=True)
    assert plan.ebur128 == ebur128
    assert plan.hash
    assert plan.loudness == enabled


def test_plan_contains_only_execution_inputs_and_independent_options(config):
    config['defects']['enabled'] = True
    config['defects']['dropouts']['fail_zero_run_ms'] = 800
    config['process_timeout_seconds'] = 123
    plan = measurement_requirements(config)
    assert set(plan.defect_options) == {'max_candidates','issues','clicks','dropouts'}
    assert 'fail_zero_run_ms' not in plan.defect_options['dropouts']
    assert set(asdict(plan)) == {'loudness','true_peak','defect_options','hash','timeout_seconds','levels_required'}
    assert plan.timeout_seconds == 123
    before = deepcopy(config)
    plan.defect_options['clicks']['merge_gap_ms'] = 0
    assert config == before
    config['defects']['enabled'] = False
    assert measurement_requirements(config).defect_options is None


def test_different_policy_targets_keep_identical_measurement_plan(config):
    config['loudness'].update(target_lufs=-23,tolerance=.5)
    config['true_peak']['maximum'] = -1
    first = measurement_requirements(config)
    config['loudness'].update(target_lufs=-14,tolerance=1)
    config['true_peak']['maximum'] = -6
    config['sample_rate']['required'] = 44100
    config['bit_depth'].update(required=16,preferred=16)
    config['channels']['allowed'] = [2]
    config['bwf']['required'] = True
    config['clipping']['fail'] = False
    assert measurement_requirements(config) == first


@pytest.mark.integration
def test_measure_once_assess_twice_without_remeasurement(wav, monkeypatch):
    policy = load_config(preset='BROADCAST_EBU_R128')
    measured, context = measure_file(wav,measurement_requirements(policy,True))
    before = deepcopy(asdict(measured))
    assert not any(c.code in {'sample_rate','integrated_loudness','true_peak','bwf'} for c in measured.checks)
    def forbidden(*args, **kwargs):
        pytest.fail('Re-evaluation attempted to measure again')
    monkeypatch.setattr('audio_qc.scanner.measure_file',forbidden)
    monkeypatch.setattr('audio_qc.process.stream_process',forbidden)
    first = assess_file(measured,policy,context)
    policy['loudness'].update(target_lufs=-14,tolerance=1)
    second = assess_file(measured,policy,context)
    assert next(c.status for c in first.checks if c.code=='integrated_loudness') == 'PASS'
    assert next(c.status for c in second.checks if c.code=='integrated_loudness') == 'FAIL'
    assert first.measurements == second.measurements == measured.measurements
    assert asdict(measured) == before


@pytest.mark.integration
@pytest.mark.parametrize('run_levels', [False,True])
def test_scanner_executes_plan_without_reading_policy_targets(wav, config, monkeypatch, run_levels):
    config['loudness']['enabled'] = run_levels
    calls = []
    def levels(*args):
        calls.append('ebur128')
        return {'integrated_lufs':-23, 'true_peak_dbtp':-8}
    monkeypatch.setattr('audio_qc.scanner.measure_loudness',levels)
    measured, context = measure_file(wav,measurement_requirements(config))
    assert calls == (['ebur128'] if run_levels else [])
    assert context.zero_runs
    assert not measured.defects


@pytest.mark.integration
def test_sample_unavailability_remains_operational(wav, config, monkeypatch):
    config['defects']['enabled'] = True
    def unavailable(*args):
        raise ValueError('Defect analysis unavailable for test format')
    monkeypatch.setattr('audio_qc.samples.StreamingDefects',unavailable)
    audio = inspect_file(wav,config)
    assert [(c.code,c.status) for c in audio.checks[:2]] == [('defects_unavailable','WARNING'),('readability','PASS')]


@pytest.mark.integration
@pytest.mark.parametrize('error,code', [(ToolError,'readability'),(ValueError,'inspection')])
def test_decode_failure_retains_earlier_measurement_diagnostic(wav, config, monkeypatch, error, code):
    config['defects']['enabled'] = True
    def unavailable(*args):
        raise ValueError('Defects unavailable')
    def failed(*args):
        raise error('Decoder failed')
    monkeypatch.setattr('audio_qc.samples.StreamingDefects',unavailable)
    monkeypatch.setattr('audio_qc.samples.stream_process',failed)
    audio = inspect_file(wav,config)
    assert audio.checks[0].code == 'defects_unavailable'
    assert any(d.code == code and d.affects_analysis for d in audio.operational_diagnostics)
    assert audio.status == 'INCOMPLETE'
    assert audio.measurements.get('decoded_sample_frames') is None


def test_measurement_modules_do_not_import_policy_or_emit_checks():
    source = Path(__file__).parents[1]/'src/audio_qc'
    forbidden = {'target_lufs','tolerance','maximum','required','preferred','fail_zero_run_ms'}
    for name in ('metadata','bwf','samples','loudness','hashing','defects','consolidation','issues','measurement'):
        tree = ast.parse((source/f'{name}.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {'rules','config'}
                assert not any(n.name in {'Check','Status'} for n in node.names)
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                assert node.slice.value not in forbidden
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (isinstance(node.func.value, ast.Name) and node.func.value.id=='audio' and node.func.attr=='add')
    scanner = (source/'scanner.py').read_text()
    for key in ('target_lufs','maximum','tolerance','BROADCAST_EBU_R128','CUSTOM','FILM_48K'):
        assert key not in scanner


@pytest.mark.integration
def test_final_source_guard_still_runs_after_policy(wav, config, monkeypatch):
    from types import SimpleNamespace
    original_stat = Path.stat
    original_assess = assess_file
    changed = False
    def stat(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path == wav and changed:
            return SimpleNamespace(st_size=value.st_size, st_mtime_ns=value.st_mtime_ns+1, st_ino=value.st_ino)
        return value
    def assess(*args, **kwargs):
        nonlocal changed
        result = original_assess(*args, **kwargs)
        changed = True  # Simulate external change; do not alter the source fixture.
        return result
    monkeypatch.setattr('audio_qc.scanner.assess_file',assess)
    monkeypatch.setattr(Path,'stat',stat)
    audio = inspect_file(wav,config)
    assert audio.operational_diagnostics[-1].code == 'source_changed'
    assert audio.status == 'INCOMPLETE'
