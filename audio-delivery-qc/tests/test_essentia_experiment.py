"""Independent detection must retain exact samples and never manufacture acceptance."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def test_seconds_roundtrip_and_inclusive_end_at_large_source_origin():
    from click_experiment.essentia_detector import sample_interval
    origin = 2**54 + 7
    assert sample_interval(np.float32(256 / 48000), np.float32(256 / 48000),
                           48000, origin) == (origin + 256, origin + 257)
    # Last seconds of a bounded 192 kHz clip must still resolve to unique samples.
    assert sample_interval(np.float32(11519999 / 192000), np.float32(60),
                           192000, 0) == (11519999, 11520001)


@pytest.mark.parametrize('start,end,rate', [(float('nan'), 0, 48000), (1, 0, 48000),
                                         (128, 128, 192000), (-1, 0, 48000)])
def test_unrecoverable_timestamps_are_errors(start, end, rate):
    from click_experiment.essentia_detector import sample_interval
    with pytest.raises(ValueError):
        sample_interval(start, end, rate, 0)


class PCM:
    """Small in-memory fixture; production adapter reads only individual frames."""
    def __init__(self, x, origin=0, rate=48000):
        self.x, self.start, self.end = x, origin, origin + len(x)
        self.rate, self.channels = rate, x.shape[1]
        self.largest_read = 0

    def read(self, first, end):
        assert self.start <= first <= end <= self.end
        self.largest_read = max(self.largest_read, end - first)
        return self.x[first-self.start:end-self.start]


def test_frame_ownership_channels_edges_and_post_consolidation_cap():
    from click_experiment.essentia_detector import detect
    # Controlled binding: return every nonzero sample in the owned middle hop.
    class Binding:
        def __init__(self, **kwargs): self.n = 0
        def __call__(self, x):
            positions = np.flatnonzero(x[128:384]) + 128 + self.n * 256
            self.n += 1
            times = (positions / 48000).astype(np.float32)
            return times, times
    x = np.zeros((1100, 2)); x[[0, 255, 256, 1099], 1] = .5
    pcm = PCM(x)
    clip = {'start_sample': 0, 'end_sample': 1100, 'channels': [1, 2]}
    result = detect(pcm, clip, {}, factory=Binding, max_events=3)
    assert not result['capped']
    assert [(e['sample_index'], e['end_sample'], e['channel'], e['merged_candidate_count'])
            for e in result['events']] == [(0, 1, 2, 1), (255, 257, 2, 2), (1099, 1100, 2, 1)]
    assert pcm.largest_read <= 512
    truncated = detect(pcm, clip, {}, factory=Binding, max_events=2)
    assert truncated['capped']
    assert len(truncated['events']) == 2


def test_manifest_rejection_labels_are_explicit_and_legacy_still_loads(tmp_path):
    import yaml
    from click_experiment.manifest import load_manifest
    data = {'schema_version': 2, 'clips': [{
        'id': 'a', 'programme': 'a', 'split': 'development', 'origin': 'synthetic',
        'file': 'source.wav', 'sample_rate': 48000, 'start_sample': 0, 'end_sample': 48000,
        'channels': [1], 'reviewed': True, 'annotations': [
            {'id': 'click', 'channel': 1, 'start_sample': 500, 'end_sample': 501,
             'kind': 'technical_click', 'qc_disposition': 'reject', 'basis': 'operator'}]}]}
    path = tmp_path / 'corpus.yaml'; path.write_text(yaml.safe_dump(data))
    assert load_manifest(path)[0]['annotations'][0]['qc_disposition'] == 'reject'
    data['clips'][0]['annotations'][0]['qc_disposition'] = 'Netflix-certified'
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError): load_manifest(path)


def test_complete_detector_metrics_keep_new_hits_and_lost_baseline_separate():
    from click_experiment.benchmark_metrics import measure, compare, decide
    labels = [dict(id='a', channel=1, start_sample=100, end_sample=101, kind='technical_click',
                   qc_disposition='reject', basis='operator'),
              dict(id='b', channel=1, start_sample=1000, end_sample=1001, kind='technical_click',
                   qc_disposition='reject', basis='operator'),
              dict(id='fx', channel=1, start_sample=2000, end_sample=2001, kind='intentional_transient',
                   qc_disposition='acceptable', basis='operator')]
    def events(*samples): return [dict(id=str(n), channel=1, sample_index=n) for n in samples]
    base = measure(events(100, 2000), labels, 48000, complete=True)
    alternative = measure(events(1000), labels, 48000, complete=True)
    assert base['reject']['precision'] == .5
    assert base['reject']['recall'] == .5
    assert alternative['reject']['recall'] == .5
    paired = compare(base['reject'], alternative['reject'])
    assert paired['lost_baseline_hits'] == ['a']
    assert paired['additional_hits'] == ['b']
    assert paired['retention'] == 0
    assert decide(base['reject'], alternative['reject'], [], 2,
                  minimum_hits=1, minimum_false_alarms=1)['decision'] == 'NOT_VIABLE'
    unknown = measure(events(3000), labels, 48000, complete=True)
    assert unknown['reject']['precision'] is None
    assert unknown['blockers']


def test_reviewed_hours_use_interval_unions_and_exclude_incomplete_analysis():
    from click_experiment.benchmark_metrics import coverage
    clips = [dict(file='/a.wav', start_sample=0, end_sample=48000, sample_rate=48000,
                  channels=[1], reviewed=True),
             dict(file='/a.wav', start_sample=0, end_sample=48000, sample_rate=48000,
                  channels=[2], reviewed=True)]
    assert coverage(clips) == {'source_seconds': 1.0, 'channel_seconds': 2.0}
    clips[1]['reviewed'] = False
    assert coverage(clips) == {'source_seconds': 1.0, 'channel_seconds': 1.0}


def test_temporal_measurement_does_not_execute_prediction(monkeypatch):
    from click_experiment import scoring
    def forbidden(*args): raise AssertionError('Prediction ran inside temporal timing')
    monkeypatch.setattr(scoring, 'prediction_error', forbidden)
    result = scoring.score_context(np.ones(1200)*.01, np.array([.5]), np.ones(1200)*.01,
                                   48000, methods=('temporal',))
    assert set(result) == {'temporal'}
    assert result['temporal']['score'] > 4


def test_v2_does_not_change_legacy_rejection_definition():
    from click_experiment.benchmark_metrics import measure
    label = dict(id='mouth', channel=1, start_sample=100, end_sample=101, kind='technical_click',
                 qc_disposition='acceptable', basis='operator')
    result = measure([dict(id='a', channel=1, sample_index=100)], [label], 48000, complete=True)
    assert result['technical']['true_positives'] == 1
    assert result['reject']['false_alarms'] == 1
    assert label['kind'] == 'technical_click'


def test_selection_failure_is_per_method_not_a_global_veto():
    from click_experiment.benchmark import conclusions
    base = {'hits': [str(i) for i in range(20)], 'missed': [], 'false_alarms': 20}
    better = {'hits': base['hits'], 'missed': [], 'false_alarms': 5}
    measured = {'baseline': {'reject': base, 'blockers': []},
                **{m: {'reject': better, 'blockers': []} for m in ('temporal','prediction','essentia')}}
    results = conclusions(measured, [], ['temporal: diagnostic fallback'], 2)
    assert results['temporal']['decision'] == 'INSUFFICIENT_EVIDENCE'
    assert results['essentia']['decision'] == 'VIABLE'


def test_unknown_new_detector_event_blocks_only_its_metrics(tmp_path):
    from click_experiment.benchmark import aggregate
    import json
    clip = dict(id='one', file='/source.wav', programme='a', origin='real', reviewed=True,
                start_sample=0, end_sample=48000, sample_rate=48000, channels=[1],
                annotations=[dict(id='r',channel=1,start_sample=100,end_sample=101,
                                  kind='technical_click',qc_disposition='reject',basis='operator')])
    record = dict(clip=clip, error=None, variants={
        'baseline': dict(events=[dict(id='b',channel=1,sample_index=100)], capped=False),
        'essentia:30': dict(events=[dict(id='e',channel=1,sample_index=1000)], capped=False)})
    (tmp_path/'x.json').write_text(json.dumps(record))
    m = aggregate(tmp_path, ['x.json'])
    assert m['baseline']['reject']['recall'] == 1
    assert m['essentia:30']['reject']['precision'] is None
    assert m['essentia:30']['blockers']


def test_worker_deadline_kills_and_reaps_child(tmp_path, monkeypatch):
    import subprocess
    from click_experiment import benchmark
    processes = []
    original = subprocess.Popen
    # Replace only the native worker process with a deliberately stalled child.
    def stalled(args, **kwargs):
        proc = original([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        processes.append(proc)
        return proc
    monkeypatch.setattr(benchmark.subprocess, 'Popen', stalled)
    with pytest.raises(subprocess.TimeoutExpired):
        benchmark.run_worker({}, 'baseline', [], tmp_path, 1, timeout=.05)
    assert processes[0].poll() is not None
    assert not (tmp_path/'EXPERIMENT_COMPLETE.json').exists()


def test_forensic_safety_limit_is_visible_even_with_one_consolidated_issue(monkeypatch):
    from click_experiment import essentia_detector as adapter
    monkeypatch.setattr(adapter, 'MAX_RAW', 3)
    class Binding:
        def __init__(self, **kw): pass
        def __call__(self, frame):
            t = np.array([128,129,130,131],dtype=np.float32)/48000
            return t,t
    pcm = PCM(np.zeros((100,1)))
    result = adapter.detect(pcm, dict(start_sample=0,end_sample=100,channels=[1]), {}, factory=Binding)
    assert result['capped'] and result['raw_output_capped']
    assert len(result['issues']) == 1
    assert result['events'][0]['merged_candidate_count'] == 3


def test_capped_records_do_not_produce_complete_recall_or_rates(tmp_path):
    from click_experiment.benchmark import aggregate
    import json
    record = dict(error=None,clip=dict(id='a',file='/a.wav',programme='p',origin='real',reviewed=True,
        channels=[1],sample_rate=48000,start_sample=0,end_sample=48000,annotations=[]),
        variants={'essentia:30':dict(events=[],capped=True)})
    (tmp_path/'r.json').write_text(json.dumps(record))
    result = aggregate(tmp_path,['r.json'])['essentia:30']
    assert result['blockers']
    assert result['reject']['recall'] is None
    assert result['reject']['false_alarms_per_source_hour'] is None
    assert result['reject']['source_seconds'] == 0


def test_rejection_manifest_cannot_accidentally_use_legacy_acceptance(tmp_path):
    import yaml
    from click_experiment.runner import run
    clip=dict(id='a',file='/not-needed.wav',programme='p',origin='synthetic',reviewed=False,
              channels=[1],sample_rate=48000,start_sample=0,end_sample=1000,annotations=[],split='development')
    path=tmp_path/'manifest.yaml'
    path.write_text(yaml.safe_dump(dict(schema_version=2,clips=[clip])))
    with pytest.raises(ValueError, match='schema.*--essentia'):
        run(path,tmp_path/'out')
    assert not (tmp_path/'out').exists()
