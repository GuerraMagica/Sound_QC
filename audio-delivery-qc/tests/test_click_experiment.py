"""Experimental metrics must not manufacture evidence of detector improvement."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from click_experiment.manifest import load_manifest
from click_experiment.metrics import classify, summarize, acceptance, choose


def manifest_data():
    return {'schema_version': 1, 'clips': [
        {'id': 'a', 'programme': 'dev', 'split': 'development', 'origin': 'synthetic',
         'file': 'sources/mezcla 日本語.wav', 'sample_rate': 48000,
         'start_sample': 0, 'end_sample': 48000, 'channels': [1, 2],
         'reviewed': True, 'annotations': []},
        {'id': 'b', 'programme': 'heldout', 'split': 'validation', 'origin': 'synthetic',
         'file': 'sources/other.wav', 'sample_rate': 48000,
         'start_sample': 0, 'end_sample': 48000, 'channels': [1, 2],
         'reviewed': True, 'annotations': []}]}


def save_manifest(tmp_path, data):
    p = tmp_path / 'groups.yaml'
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')
    return p


def test_manifest_resolves_unicode_relative_paths(tmp_path):
    clips = load_manifest(save_manifest(tmp_path, manifest_data()))
    assert clips[0]['file'] == str(tmp_path / 'sources/mezcla 日本語.wav')


@pytest.mark.parametrize('mutation', ['programme_leak', 'source_alias', 'unknown', 'bool_sample',
                                      'overlap', 'channel', 'long', 'missing_review'])
def test_manifest_rejects_ambiguous_or_leaking_corpus(tmp_path, mutation):
    data = manifest_data(); a, b = data['clips']
    if mutation == 'programme_leak': b['programme'] = a['programme']
    elif mutation == 'source_alias': b['file'] = 'sources/../sources/mezcla 日本語.wav'
    elif mutation == 'unknown': a['sampl_rate'] = 48000
    elif mutation == 'bool_sample': a['start_sample'] = True
    elif mutation == 'channel': a['channels'] = [1, 1]
    elif mutation == 'long': a['end_sample'] = 48000 * 61
    elif mutation == 'missing_review': del a['reviewed']
    else:
        b.update(file=a['file'], programme=a['programme'], split=a['split'])
    with pytest.raises(ValueError): load_manifest(save_manifest(tmp_path, data))


def test_duplicate_yaml_keys_rejected(tmp_path):
    p = tmp_path / 'bad.yaml'; p.write_text('schema_version: 1\nschema_version: 1\nclips: []\n')
    with pytest.raises(ValueError): load_manifest(p)


def event(i, sample, channel=1):
    return {'id': i, 'sample_index': sample, 'channel': channel}


def label(i, start, end, kind='technical_click', channel=1):
    return {'id': i, 'start_sample': start, 'end_sample': end, 'kind': kind, 'channel': channel}


def test_matching_inclusive_tolerance_duplicates_unknown_and_uncertain():
    annotations = [label('real', 100, 101), label('foley', 400, 410, 'intentional_transient'),
                   label('maybe', 700, 710, 'uncertain')]
    rows = classify([event('a', 148), event('b', 100), event('c', 405),
                     event('d', 705), event('e', 900), event('f', 100, 2)], annotations, 48000)
    counts = summarize(rows, annotations)
    assert counts['true_positives'] == 1
    assert counts['false_alarms'] == 2  # duplicate technical detection plus intentional transient
    assert counts['duplicates'] == 1
    assert counts['unclassified'] == 2
    assert counts['uncertain'] == 1
    assert counts['missed'] == []


def test_matching_does_not_lose_second_true_click_to_greedy_assignment():
    rows = classify([event('ambiguous', 148), event('only_first', 100)],
                    [label('one', 100, 101), label('two', 190, 191)], 48000)
    assert {r['annotation'] for r in rows if r['classification'] == 'true_positive'} == {'one', 'two'}


def test_one_sample_beyond_tolerance_is_unclassified():
    assert classify([event('a', 149)], [label('one', 100, 101)], 48000)[0]['classification'] == 'unclassified'


def test_selection_does_not_compensate_lost_baseline_hits_with_other_hits():
    base = {'hits': list(map(str, range(10))), 'false_alarms': 10}
    trials = [{'method': 'temporal', 'window_ms': 25, 'threshold': 8,
               'metrics': {'hits': list(map(str, range(2, 12))), 'false_alarms': 0}},
              {'method': 'prediction', 'window_ms': 25, 'threshold': 4,
               'metrics': {'hits': list(map(str, range(1, 10))), 'false_alarms': 5}}]
    assert choose(base, trials)['method'] == 'prediction'


def test_acceptance_requires_real_reserved_coverage_and_sample_size():
    base = {'hits': list(map(str, range(20))), 'false_alarms': 20}
    alt = {'hits': list(map(str, range(2, 20))), 'false_alarms': 10}
    assert acceptance(base, alt, real_programmes=2, blockers=[])['decision'] == 'VIABLE'
    assert acceptance(base, alt, real_programmes=1, blockers=[])['decision'] == 'INSUFFICIENT_EVIDENCE'
    assert acceptance(base, alt, real_programmes=2, blockers=['truncated'])['decision'] == 'INSUFFICIENT_EVIDENCE'
    alt['hits'] = list(map(str, range(3, 20)))
    assert acceptance(base, alt, real_programmes=2, blockers=[])['decision'] == 'NOT_VIABLE'


def test_scores_use_both_sides_and_preserve_unreliable_candidates():
    import numpy as np
    from click_experiment.scoring import score_context, retain
    t = np.arange(2400) / 48000
    pre = .03 * np.sin(2 * np.pi * 220 * t)
    post = .03 * np.sin(2 * np.pi * 220 * (t + 2408 / 48000))
    pulse = np.full(8, .7)
    result = score_context(pre, pulse, post, 48000)
    assert result['temporal']['score'] > 20
    assert result['prediction']['score'] > 8
    assert retain(result['prediction'], 8)
    loud_post = score_context(pre, pulse, post * 20, 48000)
    assert loud_post['temporal']['score'] < result['temporal']['score']
    silent = score_context(np.zeros(2400), pulse, np.zeros(2400), 48000)
    assert silent['prediction']['score'] is None
    assert retain(silent['prediction'], 100)
    assert retain(score_context(pre[:3], pulse, post, 48000)['prediction'], 100)


@pytest.mark.integration
def test_baseline_pcm_positions_and_chunk_boundaries(tmp_path):
    import numpy as np
    from dataclasses import asdict
    from audio_qc.config import load_config
    from audio_qc.defects import StreamingDefects
    from audio_qc.synthetic import sine, write_wav
    from click_experiment.audio import PCMClip, detect_clip
    source = tmp_path / 'source'; source.mkdir()
    samples = np.repeat(sine(4, frequency=220, amplitude=.03), 2, axis=1)
    samples[96000 - 4:96000 + 4, 1] += .7
    path = write_wav(source / 'print master.wav', samples, bits=24, bext=True, time_reference=172800000)
    clip = {**manifest_data()['clips'][0], 'file': str(path), 'start_sample': 50003, 'end_sample': 145001}
    with PCMClip(clip) as pcm:
        issues, capped = detect_clip(pcm, clip)
        assert not capped
        assert len(issues) == 1
        assert issues[0].sample_index == 95996
        assert issues[0].channels == [2]
        values = pcm.read(95996, 96004)
        np.testing.assert_allclose(values[:, 1], samples[95996:96004, 1], atol=2**-23)
        assert len(values) == 8
        detector = StreamingDefects(48000, 2, load_config()['defects'])
        full = pcm.read(pcm.start, pcm.end)
        for i in range(0, len(full), 127): detector.feed(full[i:i+127])
        reference = detector.finish()
        assert issues[0].measurements == reference[0].measurements


@pytest.mark.integration
def test_invalid_media_range_and_nonfinite_are_not_silent_success(tmp_path):
    import numpy as np
    from audio_qc.synthetic import write_wav
    from click_experiment.audio import PCMClip
    folder = tmp_path / 'source'; folder.mkdir()
    p = write_wav(folder / 'bad.wav', np.array([0., float('nan'), 0.]), bits=32, float_pcm=True)
    clip = {**manifest_data()['clips'][0], 'file': str(p), 'channels': [1], 'end_sample': 3}
    with pytest.raises(ValueError, match='finite'):
        with PCMClip(clip): pass
    p = write_wav(folder / 'short.wav', np.zeros(100))
    clip.update(file=str(p), end_sample=101)
    with pytest.raises(ValueError, match='range'):
        with PCMClip(clip): pass


def make_corpus(tmp_path):
    import numpy as np
    from audio_qc.synthetic import sine, write_wav
    sources = tmp_path / 'sources'; sources.mkdir()
    clips = []
    for i, split in enumerate(('development', 'validation', 'validation')):
        x = np.repeat(sine(3, amplitude=.03, frequency=220 + 31*i), 2, axis=1)
        x[48000, 0] += .7
        x[80000, 1] += .3
        p = write_wav(sources / f'mix {i} 日本語.wav', x, bits=24, bext=True, time_reference=172800000)
        clips.append({**manifest_data()['clips'][0], 'id': f'clip-{i}', 'programme': f'programme-{i}',
                      'split': split, 'file': str(p), 'end_sample': 144000,
                      'annotations': [label('click', 48000, 48001),
                                      label('effect', 80000, 80001, 'intentional_transient', channel=2)]})
    return save_manifest(tmp_path, {'schema_version': 1, 'clips': clips}), clips


@pytest.mark.integration
def test_runner_freezes_before_holdout_and_exports_only_insufficient_synthetic_evidence(tmp_path, monkeypatch):
    import json
    from click_experiment import runner
    from click_experiment.audio import fingerprint
    path, clips = make_corpus(tmp_path)
    before = {c['file']: fingerprint(c['file']) for c in clips}
    output = tmp_path / 'results'
    original = runner.analyze_clip
    def inspected(clip, *args, **kwargs):
        if clip['split'] == 'validation':
            frozen = json.loads((output / 'frozen_selection.json').read_text())
            assert frozen['selected'] is not None
            assert frozen['development_clips'] == ['clip-0']
        return original(clip, *args, **kwargs)
    monkeypatch.setattr(runner, 'analyze_clip', inspected)
    report = runner.run(path, output)
    assert report['decision']['decision'] == 'INSUFFICIENT_EVIDENCE'
    assert report['source_integrity'] is True
    assert report['metrics']['validation']['all']['baseline']['true_positives'] == 2
    assert before == {c['file']: fingerprint(c['file']) for c in clips}
    assert (output / 'report.html').is_file()
    assert (output / 'candidates.csv').is_file()
    assert (output / 'results.json').is_file()
    with pytest.raises(FileExistsError): runner.run(path, output)


@pytest.mark.integration
def test_runner_rejects_identical_sources_disguised_as_different_programmes(tmp_path):
    import shutil
    from click_experiment.runner import run
    path, clips = make_corpus(tmp_path)
    shutil.copyfile(clips[0]['file'], clips[1]['file'])
    with pytest.raises(ValueError, match='Identical'):
        run(path, tmp_path / 'results')
    assert not (tmp_path / 'results').exists()


@pytest.mark.integration
def test_unclassified_candidate_blocks_acceptance(tmp_path):
    from click_experiment.runner import run
    path, clips = make_corpus(tmp_path)
    clips[1]['annotations'] = []
    path = save_manifest(tmp_path, {'schema_version': 1, 'clips': clips})
    result = run(path, tmp_path / 'results')
    assert any('unclassified' in r for r in result['decision']['reasons'])


@pytest.mark.integration
def test_original_source_change_invalidates_experiment(tmp_path, monkeypatch):
    from click_experiment import runner
    path, clips = make_corpus(tmp_path)
    original = runner.analyze_clip
    def changed(clip, *args, **kwargs):
        result = original(clip, *args, **kwargs)
        Path(clip['file']).touch()
        return result
    monkeypatch.setattr(runner, 'analyze_clip', changed)
    result = runner.run(path, tmp_path / 'results')
    assert result['source_integrity'] is False
    assert result['decision']['decision'] == 'INSUFFICIENT_EVIDENCE'

@pytest.mark.integration
def test_low_rate_spool_covers_global_detector_pad(tmp_path):
    import numpy as np
    from audio_qc.synthetic import write_wav
    from click_experiment.audio import PCMClip
    path = write_wav(tmp_path / 'low.wav', np.zeros(8000 * 50), rate=8000)
    clip = {**manifest_data()['clips'][0], 'file': str(path), 'sample_rate': 8000,
            'channels': [1], 'start_sample': 16000, 'end_sample': 24000}
    with PCMClip(clip) as pcm:
        assert pcm.start <= (clip['start_sample'] // 8192) * 8192 - 4480

@pytest.mark.integration
def test_report_failure_never_marks_complete(tmp_path, monkeypatch):
    from click_experiment import runner, report
    path, _ = make_corpus(tmp_path)
    def full(*args):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(report, 'render', full)
    output = tmp_path / 'results'
    with pytest.raises(OSError): runner.run(path, output)
    assert not (output / 'EXPERIMENT_COMPLETE.json').exists()
    assert (output / 'EXPERIMENT_ERROR.json').exists()

@pytest.mark.integration
def test_discarded_evidence_preserves_six_channel_source(tmp_path):
    import json
    import numpy as np
    from audio_qc.synthetic import sine, write_wav
    from click_experiment import runner
    from click_experiment.audio import PCMClip, fingerprint
    folder = tmp_path / 'source'; folder.mkdir()
    x = np.repeat(sine(3, amplitude=.03), 6, axis=1)
    x *= np.arange(1, 7) / 6
    x[48000, 4] += .7
    p = write_wav(folder / 'mix & 日本語.wav', x, bits=24, bext=True)
    before = fingerprint(p)
    clip = {**manifest_data()['clips'][0], 'file': str(p), 'channels': list(range(1, 7)),
            'end_sample': 144000}
    out = tmp_path / 'results'; out.mkdir()
    record = json.loads((out / runner.analyze_clip(clip, out, 1)).read_text())
    assert record['events']
    links, errors = runner.evidence_for_discarded(record,
        {'method': 'temporal', 'window_ms': 25, 'threshold': 1000000}, out, 1)
    assert links and not errors
    snippet = out / next(iter(links.values()))
    with PCMClip({**clip, 'file': str(snippet), 'end_sample': 48000}) as pcm:
        assert pcm.channels == 6
        np.testing.assert_allclose(pcm.read(0, 1000), x[:1000], atol=2**-22)
    assert fingerprint(p) == before


def test_mixed_kind_tolerance_is_unclassified_not_reassigned_as_true_click():
    labels = [label('T', 100, 101), label('F', 190, 191, 'intentional_transient')]
    baseline = classify([event('one', 100), event('two', 144)], labels, 48000)
    alternative = classify([event('two', 144)], labels, 48000)
    assert baseline[1]['classification'] == 'unclassified'
    assert alternative[0]['classification'] == 'unclassified'
    assert summarize(alternative, labels)['hits'] == []

@pytest.mark.integration
def test_same_programme_identical_copy_cannot_multiply_observations(tmp_path):
    import shutil
    from click_experiment.runner import run
    path, clips = make_corpus(tmp_path)
    duplicate = deepcopy(clips[0])
    duplicate.update(id='copy', file=str(tmp_path / 'sources' / 'copy.wav'))
    shutil.copyfile(clips[0]['file'], duplicate['file'])
    clips.append(duplicate)
    path = save_manifest(tmp_path, {'schema_version': 1, 'clips': clips})
    with pytest.raises(ValueError, match='Identical'):
        run(path, tmp_path / 'results')
