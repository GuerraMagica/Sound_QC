from copy import deepcopy
from dataclasses import asdict
from itertools import permutations

import pytest

from audio_qc.issues import IssueConsolidator, consolidate_issues
from audio_qc.models import AudioFile, Check, Defect, Status, highest_severity, overall_status
from audio_qc.rules import assess_file, evaluate_file_policy


def event(sample, channel, severity, strength=12):
    return Defect(sample/48000, sample, channel, 'POSSIBLE CLICK / TICK', 3/48000,
                  severity, {'duration_samples': 3, 'impulse_deviation_db': strength},
                  f'measured_at_{sample}')


@pytest.mark.parametrize('first,second,expected', [
    (Status.INFO, Status.WARNING, Status.WARNING),
    (Status.WARNING, Status.FAIL, Status.FAIL),
    (Status.INFO, Status.FAIL, Status.FAIL),
    (Status.PASS, Status.INFO, Status.PASS),
    (Status.PASS, Status.WARNING, Status.WARNING),
    (None, Status.INFO, Status.INFO),
    (None, Status.WARNING, Status.WARNING),
    (None, Status.FAIL, Status.FAIL),
    (None, Status.PASS, Status.PASS),
    (None, None, None),
])
def test_issue_severity_independent_of_constituent_order_and_representative(first, second, expected, config):
    for severities in permutations((first, second)):
        candidates = [event(100, 1, severities[0]), event(104, 2, severities[1])]
        before = deepcopy(candidates)
        forward, = consolidate_issues(candidates, 48000, 2)
        reverse, = consolidate_issues(reversed(candidates), 48000, 2)
        assert forward == reverse
        assert forward.severity == expected
        assert forward.sample_index == 100 and forward.channel == 1
        assert [e.severity for e in forward.channel_events] == list(severities)
        assert candidates == before
        audio = AudioFile('/not/opened.wav', 'not/opened.wav', sample_rate=48000, defects=[forward])
        measured = deepcopy(audio)
        assessed = assess_file(audio, config)
        assert assessed.defects[0].severity == (Status.WARNING if expected is None else expected)
        assert assessed.defects[0].channel_events == forward.channel_events
        assert audio == measured


@pytest.mark.parametrize('severity', [Status.WARNING, Status.FAIL])
def test_stronger_later_same_channel_representative_cannot_downgrade_issue(severity, config):
    candidates = [event(100, 1, severity, 12), event(102, 2, Status.INFO, 13),
                  event(104, 1, Status.INFO, 16), event(108, 1, None, 20)]
    before = deepcopy(candidates)
    state = IssueConsolidator(48000, 2)
    for candidate in candidates:
        state.extend([candidate])
        assert state.issues[0].severity == severity
    issue, = state.finish()
    # Stronger channel-1 representative moves later, so channel 2 becomes the
    # issue's earliest representative. Neither selection may change severity.
    assert issue.sample_index == 102 and issue.channel == 2
    channel_one = issue.channel_events[0]
    assert channel_one.sample_index == 108 and channel_one.severity == severity
    expected = {**asdict(candidates[-1]), 'severity': severity, 'merged_candidate_count': 3,
                'cluster_first_sample': 100, 'cluster_last_sample': 110}
    assert asdict(channel_one) == expected
    assert issue.channel_events[1].severity == Status.INFO
    audio = AudioFile('/not/opened.wav', 'not/opened.wav', sample_rate=48000, defects=[issue])
    measured = deepcopy(audio)
    assert assess_file(audio, config).defects[0].severity == severity
    assert audio == measured and candidates == before


def test_measurement_stays_unclassified_and_default_policy_is_unchanged(config):
    candidates = [event(100, 1, None), event(102, 2, None), event(104, 1, None, 20)]
    before = deepcopy(candidates)
    issue, = consolidate_issues(candidates, 48000, 2)
    assert issue.severity is None
    assert all(e.severity is None for e in issue.channel_events)
    assert candidates == before
    audio = AudioFile('/not/opened.wav', 'not/opened.wav', sample_rate=48000, defects=[issue])
    measured, policy = deepcopy(audio), deepcopy(config)
    for _ in range(2):
        assessed = assess_file(audio, config)
        assert assessed.defects[0].severity == Status.WARNING
        assert all(e.severity is None for e in assessed.defects[0].channel_events)
        check, = [c for c in assessed.checks if c.code == 'defect_candidates']
        assert check.status == Status.WARNING and check.message == '1 possible defects require human review'
        assert assessed.checks == evaluate_file_policy(audio, config)
        assert audio == measured and config == policy
    # Report-copy mutation must not alter any original forensic evidence.
    assessed.defects[0].channel_events[0].measurements['duration_samples'] = 999
    assert audio == measured


@pytest.mark.parametrize('first', list(Status))
@pytest.mark.parametrize('second', list(Status))
def test_classified_severity_matches_existing_application_status_order(first, second):
    checks = [Check('first', first, ''), Check('second', second, '')]
    assert highest_severity([first, second]) == overall_status(checks)


def test_absent_classification_is_not_an_info_or_pass_decision():
    assert highest_severity([]) is None
    assert highest_severity([None, None]) is None
