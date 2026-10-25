"""Evidence must refer to the source that was measured, including on cancellation."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest

from audio_qc import snippets
from audio_qc.cli import main
from audio_qc.process import ScanCancelled, ToolError
from audio_qc.scanner import inspect_file
from audio_qc.synthetic import sine, write_wav


@pytest.fixture
def measured(tmp_path, config):
    config['defects']['enabled'] = True
    samples = sine(4, amplitude=.02)
    samples[48000, 0] += .8
    samples[144000, 0] += .8
    source = write_wav(tmp_path/'source.wav', samples, bits=24, bext=True)
    audio = inspect_file(source, config)
    assert len(audio.defects) == 2
    output = tmp_path/'output'
    output.mkdir()
    return source, audio, output, config


def touch_source(source):
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))


def assert_blocked(audio, before):
    assert all(event.snippet is None for event in audio.defects)
    assert audio.measurements == before.measurements
    assert audio.checks == before.checks
    assert audio.measurement_outcomes == before.measurement_outcomes
    assert audio.status == before.status
    diagnostic = next(d for d in audio.operational_diagnostics if d.code == 'snippet_source_changed')
    assert diagnostic.required and not diagnostic.affects_analysis


@pytest.mark.integration
@pytest.mark.parametrize('change', ['mtime', 'size', 'replacement', 'missing', 'unknown', 'malformed'])
def test_changed_or_unverifiable_source_blocks_evidence_before_export(measured, change):
    source, audio, output, config = measured
    if change == 'mtime':
        touch_source(source)
    elif change == 'size':
        with source.open('ab') as handle:
            handle.write(b'changed synthetic fixture')
    elif change == 'replacement':
        stat = source.stat()
        replacement = source.with_suffix('.replacement')
        replacement.write_bytes(source.read_bytes())
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replacement.replace(source)
    elif change == 'missing':
        source.unlink()
    elif change == 'unknown':
        audio.metadata.pop('source_signature', None)
    else:
        audio.metadata['source_signature'] = [True, 1, 2]
    before = deepcopy(audio)
    snippets.export_snippets(audio, output, config, 1)
    assert_blocked(audio, before)
    assert not list(output.rglob('*.wav'))


@pytest.mark.integration
@pytest.mark.parametrize('termination', ['success', 'failure', 'cancel'])
def test_change_during_second_export_revokes_all_links_and_preserves_facts(measured, monkeypatch, termination):
    source, audio, output, config = measured
    before = deepcopy(audio)
    original = snippets.stream_process
    calls = []

    @contextmanager
    def changing(args, *a, **kw):
        calls.append(args)
        with original(args, *a, **kw) as pipe:
            yield pipe
        if len(calls) == 2:
            assert audio.defects[0].snippet  # First export really completed.
            touch_source(source)
            if termination == 'failure':
                raise ToolError('Injected export failure')
            if termination == 'cancel':
                raise ScanCancelled()

    monkeypatch.setattr(snippets, 'stream_process', changing)
    if termination == 'cancel':
        with pytest.raises(ScanCancelled):
            snippets.export_snippets(audio, output, config, 1)
    else:
        snippets.export_snippets(audio, output, config, 1)
    assert_blocked(audio, before)


@pytest.mark.integration
def test_cli_changed_source_is_operational_not_acoustic_failure(measured, monkeypatch):
    source, baseline, _, config = measured
    export = snippets.export_snippets
    def changed(audio, *a, **kw):
        touch_source(source)
        export(audio, *a, **kw)
    monkeypatch.setattr('audio_qc.cli.export_snippets', changed)
    output = source.parent/'cli-report'
    code = main(['inspect', str(source), '--output', str(output), '--export-defect-snippets'])
    assert code == 2
    report = json.loads((output/'QC_REPORT.json').read_text())
    assert report['execution_status'] == 'PARTIAL'
    audio, = report['files']
    assert audio['measurements'] == baseline.measurements
    assert all(e['snippet'] is None for e in audio['defects'])
    assert any(d['code'] == 'snippet_source_changed' for d in audio['operational_diagnostics'])
    assert '>Evidence WAV</a>' not in (output/'QC_REPORT.html').read_text()


@pytest.mark.integration
@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('change', [False, True])
def test_experiment_evidence_requires_same_source_as_analysis(measured, version, change):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
    from click_experiment import runner, benchmark, benchmark_worker
    source, _, output, _ = measured
    clip = dict(id='test', file=str(source), sample_rate=48000, start_sample=0,
                end_sample=192000, channels=[1])
    if version == 1:
        record = json.loads((output/runner.analyze_clip(clip, output, 1)).read_text())
        assert record['error'] is None and record['issues']
        if change:
            touch_source(source)
        links, errors = runner.evidence_for_discarded(record,
            dict(method='temporal', window_ms=25, threshold=1000000), output, 1)
    else:
        path = output/'clip_0001_baseline.json'
        benchmark_worker.execute(dict(clip=clip, family='baseline', output_file=str(path)))
        record = json.loads(path.read_text())
        assert record['error'] is None and record['variants']['baseline']['issues']
        # No native Essentia is needed to exercise the shared evidence exporter.
        (output/'clip_0001_essentia.json').write_text(json.dumps({
            **record, 'variants': {'essentia:30': record['variants']['baseline']}}))
        if change:
            touch_source(source)
        links, errors = benchmark.export_evidence(output, [clip],
            {'essentia': dict(method='essentia', detectionThreshold=30)})
        links = links['test']
    if change:
        assert errors and links and not any(links.values())
        assert not list(output.rglob('*.wav'))
    else:
        assert not errors and links and all(links.values())
        assert all((output/path).is_file() for path in links.values())


@pytest.mark.integration
def test_unreadable_identity_revokes_existing_links(measured, monkeypatch):
    source, audio, output, config = measured
    snippets.export_snippets(audio, output, config, 1)
    assert all(e.snippet for e in audio.defects)
    before = deepcopy(audio)
    stat = Path.stat
    def denied(path, *a, **kw):
        if path == source:
            raise PermissionError('Injected stat denial')
        return stat(path, *a, **kw)
    monkeypatch.setattr(Path, 'stat', denied)
    snippets.export_snippets(audio, output, config, 2)
    assert_blocked(audio, before)
    assert len(list(output.rglob('*.wav'))) == 2  # No additional exports.


@pytest.mark.integration
def test_analysis_change_cannot_be_hidden_by_restored_stat_before_export(measured):
    _, audio, output, config = measured
    # The scanner has already observed a change. Even if stat now matches, that
    # diagnostic is permanent for this scan and must prohibit evidence links.
    audio.operational('source_changed', 'Previously observed change', required=True, affects_analysis=True)
    before = deepcopy(audio)
    snippets.export_snippets(audio, output, config, 1)
    assert_blocked(audio, before)
    assert not list(output.rglob('*.wav'))
