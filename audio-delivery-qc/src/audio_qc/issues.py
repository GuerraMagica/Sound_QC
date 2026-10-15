"""File-scoped measurement/evidence construction, before the public issue cap.

First consolidate click candidates per channel using M2.1 interval rules. Group
channel events of the same type whose first sample is within a fixed tolerance
of an issue's earliest first sample, with at most one event per channel/issue.
Assign to the earliest eligible issue; never merge already distinct issues.
This bounded start window prevents cross-channel transitive time chaining.
"""
from dataclasses import fields
from fractions import Fraction

from .consolidation import CLICK, _cluster, _merge
from .models import Defect, DefectIssue, highest_severity


def _issue(events):
    events = sorted(events, key=lambda e: e.channel)
    representative = min(events, key=lambda e: (e.sample_index, e.channel))
    values = {f.name: getattr(representative, f.name) for f in fields(Defect)}
    values.update(severity=highest_severity(e.severity for e in events),
                  merged_candidate_count=sum(e.merged_candidate_count for e in events),
                  cluster_first_sample=min(e.cluster_first_sample for e in events),
                  cluster_last_sample=max(e.cluster_last_sample for e in events))
    return DefectIssue(**values, channels=[e.channel for e in events], channel_events=events)


class IssueConsolidator:
    """Retain <= limit issues, <= source channels events per issue, no raw list.

    A pending reference per click channel allows intra-channel consolidation to
    continue across core windows and after overflow. New channels may still join
    retained issues until their inclusive start window closes. Since assignment
    always prefers the earliest eligible retained issue, ignored later issues
    cannot steal events from it; cap=K equals the first K uncapped issues.
    """
    def __init__(self, rate, channels, click_merge_gap_ms=1.0,
                 cross_channel_merge_ms=1.0, max_issues=None):
        self.rate, self.channels = rate, channels
        self.click_gap = Fraction(str(click_merge_gap_ms)) * rate // 1000
        self.issue_gap = Fraction(str(cross_channel_merge_ms)) * rate // 1000
        self.limit = max_issues
        self.issues = []
        self.pending = {}  # channel -> retained issue index
        self.joinable = []  # indices still inside the fixed cross-channel start window
        self.capped = False
        self.watermark = 0
        self.raw_candidate_count = 0

    @property
    def ready_to_stop(self):
        return self.capped and not self.pending and not self.joinable

    def advance(self, sample):
        if sample < self.watermark:
            raise ValueError("Candidates must arrive in chronological sample order")
        self.watermark = sample
        for channel, index in list(self.pending.items()):
            event = next(e for e in self.issues[index].channel_events if e.channel == channel)
            if sample > event.cluster_last_sample + 1 + self.click_gap:
                del self.pending[channel]
        self.joinable = [i for i in self.joinable
                         if sample <= self.issues[i].cluster_first_sample + self.issue_gap]

    def extend(self, candidates):
        for candidate in candidates:
            self.advance(candidate.sample_index)
            if self.ready_to_stop:
                break
            if not 1 <= candidate.channel <= self.channels:
                raise ValueError("Candidate channel is outside the source channel count")
            self.raw_candidate_count += 1
            event = _cluster(candidate, self.rate)
            index = self.pending.get(event.channel) if event.event_type == CLICK else None
            if index is not None:
                events = self.issues[index].channel_events
                self.issues[index] = _issue([_merge(e, event) if e.channel == event.channel else e for e in events])
                continue
            index = next((i for i in self.joinable
                          if self.issues[i].event_type == event.event_type
                          and event.channel not in self.issues[i].channels), None)
            if index is not None:
                self.issues[index] = _issue([*self.issues[index].channel_events, event])
            elif self.limit is None or len(self.issues) < self.limit:
                index = len(self.issues)
                self.issues.append(_issue([event]))
                self.joinable.append(index)
            else:
                self.capped = True
                continue
            if event.event_type == CLICK:
                self.pending[event.channel] = index

    def finish(self):
        self.pending.clear()
        self.joinable.clear()
        return self.issues


def consolidate_issues(candidates, rate, channels, click_merge_gap_ms=1.0,
                       cross_channel_merge_ms=1.0, max_issues=None):
    """Pure batch equivalent of streaming construction, for ONE source file."""
    state = IssueConsolidator(rate, channels, click_merge_gap_ms, cross_channel_merge_ms, max_issues)
    state.extend(sorted(candidates, key=lambda e: (e.sample_index, e.channel, e.event_type)))
    return state.finish()
