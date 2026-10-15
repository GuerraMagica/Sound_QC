from copy import deepcopy
from dataclasses import asdict
import random

import numpy as np
import pytest

from audio_qc.config import ConfigError, load_config
from audio_qc.consolidation import consolidate_candidates
from audio_qc.defects import StreamingDefects, detect_window
from audio_qc.issues import IssueConsolidator, consolidate_issues
from audio_qc.measurement import MeasurementContext
from audio_qc.models import AudioFile, Defect, Status
from audio_qc.reports import build_report
from audio_qc.rules import assess_file, evaluate_file_policy
from audio_qc.synthetic import sine


CLICK = 'POSSIBLE CLICK / TICK'
DROP = 'POSSIBLE DROPOUT'


def raw(sample, channel=1, length=3, strength=12.5, kind=CLICK, rate=48000):
    return Defect(sample/rate, sample, channel, kind, length/rate, None,
                  {'duration_samples': length, 'impulse_deviation_db': strength}, f'measured_{sample}')


@pytest.mark.parametrize('rate,delta,count', [(48000,48,1),(48000,49,2),
                                            (44100,44,1),(44100,45,2),
                                            (96000,96,1),(96000,97,2)])
def test_cross_channel_start_tolerance_inclusive_exact_samples(rate, delta, count):
    issues = consolidate_issues([raw(100,rate=rate), raw(100+delta,2,rate=rate)],rate,2)
    assert len(issues) == count
    assert [e.channels for e in issues] == ([[1,2]] if count == 1 else [[1],[2]])


def test_overlap_alone_is_insufficient_and_types_never_merge():
    issues = consolidate_issues([raw(100,1,10000,kind=DROP),raw(200,2,10000,kind=DROP),
                                 raw(100,3,kind=CLICK)],48000,3)
    assert len(issues) == 3
    assert all(len(e.channels) == 1 for e in issues)


def test_start_window_is_anchored_to_earliest_not_transitive():
    issues = consolidate_issues([raw(100,1),raw(140,2),raw(180,3)],48000,3)
    assert [e.channels for e in issues] == [[1,2],[3]]
    assert [e.cluster_first_sample for e in issues] == [100,180]


def test_channel_first_start_not_later_strongest_representative_controls_grouping():
    detections = [raw(100,1,strength=11),raw(140,2),raw(151,1,strength=13),raw(180,3)]
    before = deepcopy(detections)
    first, second = consolidate_issues(detections,48000,3)
    assert first.channels == [1,2] and second.channels == [3]
    assert (first.cluster_first_sample, first.cluster_last_sample) == (100,153)
    assert first.sample_index == 140 and first.timestamp_seconds.hex() == detections[1].timestamp_seconds.hex()
    one, two = first.channel_events
    assert one.sample_index == 151 and one.merged_candidate_count == 2
    assert one.measurements == detections[2].measurements
    assert one.detection_method == detections[2].detection_method
    assert one.duration_seconds == detections[2].duration_seconds
    assert one.timestamp_seconds.hex() == detections[2].timestamp_seconds.hex()
    assert two.sample_index == 140 and two.merged_candidate_count == 1
    assert detections == before


def test_distinct_same_channel_events_are_not_merged_by_issue_tolerance():
    issues = consolidate_issues([raw(100),raw(110),raw(120,2)],48000,2,click_merge_gap_ms=0)
    assert [e.channels for e in issues] == [[1,2],[1]]
    assert [e.merged_candidate_count for e in issues] == [2,1]
    assert issues[0].sample_index == 100


def test_no_tc_rounding_or_cross_source_grouping(config):
    one = consolidate_issues([raw(2529767)],48000,2)
    two = consolidate_issues([raw(2529770,2)],48000,2)
    a = AudioFile('/delivery/a.wav','a.wav',sample_rate=48000,defects=one)
    b = AudioFile('/delivery/b.wav','b.wav',sample_rate=48000,defects=two)
    report = build_report('/delivery',[a,b],[],config,{},0)
    assert report['summary']['defect_issues'] == 2
    assert report['files'][0]['defects'][0]['channels'] == [1]
    assert report['files'][1]['defects'][0]['channels'] == [2]
    same_frame = [raw(100),raw(340,2)]
    for e in same_frame:
        e.timecode = '01:00:00:00'
    assert len(consolidate_issues(same_frame,48000,2)) == 2


def test_zero_cross_tolerance_accepts_only_equal_starts():
    issues = consolidate_issues([raw(100),raw(100,2),raw(101,3)],48000,3,cross_channel_merge_ms=0)
    assert [e.channels for e in issues] == [[1,2],[3]]


def test_cap_after_both_stages_retains_new_channels_and_updates_after_overflow():
    state = IssueConsolidator(48000,6,max_issues=1)
    # The unrelated type overflows, but must not prevent channel 5 joining later.
    state.extend([raw(100),raw(102,2),raw(104,kind=DROP),raw(105,1,strength=14),raw(148,5)])
    issue, = state.finish()
    assert state.capped
    assert issue.channels == [1,2,5]
    assert issue.merged_candidate_count == 4
    assert [e.merged_candidate_count for e in issue.channel_events] == [2,1,1]
    assert issue.channel_events[0].sample_index == 105


def test_cap_does_not_warn_for_many_raw_detections_in_one_issue():
    state = IssueConsolidator(48000,6,max_issues=1)
    for sample in range(5000):
        state.extend(raw(sample,ch) for ch in range(1,7))
        assert len(state.issues) == 1
        assert len(state.issues[0].channel_events) == 6
        assert len(state.pending) <= 6 and len(state.joinable) <= 1
    issue, = state.finish()
    assert not state.capped
    assert issue.merged_candidate_count == state.raw_candidate_count == 30000
    assert [e.merged_candidate_count for e in issue.channel_events] == [5000]*6


@pytest.mark.parametrize('seed',range(8))
def test_cap_is_uncapped_prefix_and_forensics_match_existing_intra_channel_stage(seed):
    rng = random.Random(seed)
    detections = [raw(rng.randrange(100,3000),rng.randrange(1,7),rng.randrange(1,16),
                      rng.randrange(10,20),kind=rng.choice([CLICK,CLICK,DROP])) for _ in range(250)]
    detections.sort(key=lambda e:(e.sample_index,e.channel,e.event_type))
    all_issues = consolidate_issues(detections,48000,6)
    channel_events = sorted([asdict(e) for issue in all_issues for e in issue.channel_events],
                            key=lambda e:(e['sample_index'],e['channel'],e['event_type']))
    expected = [asdict(e) for e in consolidate_candidates(detections,48000)]
    assert channel_events == expected
    for cap in (1,2,7,20):
        state = IssueConsolidator(48000,6,max_issues=cap)
        for i in range(0,len(detections),11):
            state.extend(detections[i:i+11])
            assert len(state.issues) <= cap
            assert sum(len(e.channel_events) for e in state.issues) <= cap*6
        assert state.finish() == all_issues[:cap]
        assert state.capped == (len(all_issues)>cap)


@pytest.mark.parametrize('block',[127,8192,48000,65537])
def test_real_multichannel_candidates_cross_core_and_cap_after_grouping(config,block):
    signal = sine(3,channels=6,amplitude=.03,frequency=220)
    signal[47996:47999,0] += .7
    signal[48000:48008,0] += .8
    signal[47999:48005,1] += .7
    signal[48002:48007,4] += .7
    detections = detect_window(signal,48000,config['defects'])
    assert len(detections) == 4
    config['defects']['max_candidates'] = 1
    stream = StreamingDefects(48000,6,config['defects'])
    for i in range(0,len(signal),block):
        stream.feed(signal[i:i+block])
    issue, = stream.finish()
    assert issue.channels == [1,2,5]
    assert issue.merged_candidate_count == 4
    assert [e.merged_candidate_count for e in issue.channel_events] == [2,1,1]
    assert (issue.cluster_first_sample,issue.cluster_last_sample) == (47996,48007)
    assert not stream.capped


def test_issue_policy_assessment_does_no_grouping_and_leaves_measurements_unchanged(config,monkeypatch):
    config['defects']['enabled'] = True
    audio = AudioFile('/missing/source.wav','source.wav',sample_rate=48000,
                      defects=consolidate_issues([raw(100),raw(103,2)],48000,2))
    before = deepcopy(audio)
    def forbidden(*args,**kwargs):
        pytest.fail('Policy invoked signal analysis or issue construction')
    for name in ('audio_qc.issues.consolidate_issues','audio_qc.issues.IssueConsolidator.extend',
                 'audio_qc.consolidation.consolidate_candidates','audio_qc.defects.detect_window'):
        monkeypatch.setattr(name,forbidden)
    checks = evaluate_file_policy(audio,config,MeasurementContext())
    assessed = assess_file(audio,config,MeasurementContext())
    assert assessed.checks == checks
    assert assessed.defects[0].severity == Status.WARNING
    assert assessed.defects[0].channel_events == audio.defects[0].channel_events
    assert audio == before
    assert evaluate_file_policy(audio,config,MeasurementContext()) == checks


@pytest.mark.parametrize('value',[0,0.25,1.0,10])
def test_cross_channel_config_valid(tmp_path,value):
    path = tmp_path/'issues.yaml'
    path.write_text(f'defects:\n  issues:\n    cross_channel_merge_ms: {value}\n')
    assert load_config(path)['defects']['issues']['cross_channel_merge_ms'] == value


@pytest.mark.parametrize('value',['-0.01','10.001','true','null','"1.0"','.nan','.inf'])
def test_cross_channel_config_invalid(tmp_path,value):
    path = tmp_path/'issues.yaml'
    path.write_text(f'defects:\n  issues:\n    cross_channel_merge_ms: {value}\n')
    with pytest.raises(ConfigError,match='cross_channel_merge_ms'):
        load_config(path)


def test_default_is_one_millisecond():
    assert load_config()['defects']['issues']['cross_channel_merge_ms'] == 1.0


def test_real_reference_cluster_geometry_stays_two_issues():
    # The supplied mono report's consolidated intervals, without embedding
    # source audio or inventing the individual raw detector measurements.
    a = raw(1933168, length=8)
    a.cluster_first_sample, a.cluster_last_sample, a.merged_candidate_count = 1933158,1933175,2
    b = raw(1933792, length=238)
    b.cluster_first_sample, b.cluster_last_sample, b.merged_candidate_count = 1933553,1934029,2
    before = deepcopy([a,b])
    assert b.cluster_first_sample - a.cluster_last_sample - 1 == 377
    issues = consolidate_issues([a,b],48000,1,click_merge_gap_ms=1.0,cross_channel_merge_ms=1.0)
    assert len(issues) == 2
    assert [(e.cluster_first_sample,e.cluster_last_sample,e.sample_index,e.merged_candidate_count)
            for e in issues] == [(1933158,1933175,1933168,2),(1933553,1934029,1933792,2)]
    assert [a,b] == before
