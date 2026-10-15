"""File-scoped click consolidation in exact sample space, after detection.

Intervals are [start, end); the gap is the number of samples between them.
Cluster bounds are inclusive sample indices. No timing labels are consulted.
"""
from dataclasses import replace
from fractions import Fraction
import math

from .models import highest_severity


CLICK = "POSSIBLE CLICK / TICK"


def _cluster(event, rate):
    count = event.measurements.get("duration_samples")
    if type(count) is not int or count < 1:
        # Legacy candidates expose seconds only. Recover their nearest sample
        # count without comparing floating-point interval endpoints.
        count = max(1, round(Fraction(str(event.duration_seconds)) * rate))
    first = event.cluster_first_sample
    last = event.cluster_last_sample
    return replace(event, cluster_first_sample=event.sample_index if first is None else first,
                   cluster_last_sample=event.sample_index + count - 1 if last is None else last)


def _strength(event):
    value = event.measurements.get("impulse_deviation_db")
    finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return (finite, value if finite else 0, -event.sample_index)


def _merge(left, right):
    representative = right if _strength(right) > _strength(left) else left
    return replace(representative,
                   severity=highest_severity((left.severity, right.severity)),
                   merged_candidate_count=left.merged_candidate_count + right.merged_candidate_count,
                   cluster_first_sample=min(left.cluster_first_sample, right.cluster_first_sample),
                   cluster_last_sample=max(left.cluster_last_sample, right.cluster_last_sample))


class CandidateConsolidator:
    """Consume chronological detections from ONE source file, across windows.

    Retain at most max_candidates representatives plus one pending index per
    retained click channel. Raw candidates are not retained. On overflow, keep
    resolving retained clusters until the sample watermark proves them closed.
    """
    def __init__(self, rate, merge_gap_ms=1.0, max_candidates=None):
        self.rate = rate
        # Integer gaps <= the exact configured duration: floor is intentional.
        self.gap_samples = (Fraction(str(merge_gap_ms)) * rate) // 1000
        self.limit = max_candidates
        self.events = []
        self.pending = {}
        self.capped = False
        self.raw_candidate_count = 0
        self.watermark = 0

    @property
    def ready_to_stop(self):
        return self.capped and not self.pending

    def advance(self, sample):
        """No future candidate starts before sample (inclusive gap boundary)."""
        if sample < self.watermark:
            raise ValueError("Candidates must arrive in chronological sample order")
        self.watermark = sample
        for key, index in list(self.pending.items()):
            if sample > self.events[index].cluster_last_sample + 1 + self.gap_samples:
                del self.pending[key]

    def extend(self, candidates):
        for event in candidates:
            self.advance(event.sample_index)
            if self.ready_to_stop:
                break
            self.raw_candidate_count += 1
            key = (event.channel, event.event_type)
            index = self.pending.get(key) if event.event_type == CLICK else None
            if index is not None:
                self.events[index] = _merge(self.events[index], _cluster(event, self.rate))
            elif self.limit is not None and len(self.events) >= self.limit:
                self.capped = True
            else:
                self.events.append(_cluster(event, self.rate))
                if event.event_type == CLICK:
                    self.pending[key] = len(self.events) - 1

    def finish(self):
        self.pending.clear()
        # A stronger later representative can change ordering across channels.
        self.events.sort(key=lambda e: (e.sample_index, e.channel, e.event_type))
        return self.events


def consolidate_candidates(candidates, rate, merge_gap_ms=1.0):
    """Pure batch helper for one file; preserve each chosen candidate's evidence."""
    consolidator = CandidateConsolidator(rate, merge_gap_ms)
    consolidator.extend(sorted(candidates, key=lambda e: (e.sample_index, e.channel, e.event_type)))
    return consolidator.finish()
