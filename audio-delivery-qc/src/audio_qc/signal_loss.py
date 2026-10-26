"""Bounded, exact digital-zero intervals; no delivery severity or signal inference."""
from fractions import Fraction
from math import ceil

import numpy as np

from .defects import runs
from .models import Defect, DefectIssue

METHOD = 'exact_zero_samples+signal_loss'


class StreamingSignalLoss:
    def __init__(self, rate, channels, options):
        self.rate, self.channels = rate, channels
        self.minimum = max(1, ceil(Fraction(str(options['min_duration_ms'])) * rate / 1000))
        self.cap = options['max_events']
        self.frames = 0
        self.open = [None] * channels
        self.critical, self.edges = {}, {}
        self.counts = dict.fromkeys(('INTERNAL', 'TOTAL', 'LEADING', 'TRAILING'), 0)
        self.omitted = 0

    def _record(self, ch, start, end, kind):
        if end-start < self.minimum and kind != 'TOTAL':
            return
        self.counts[kind] += 1
        table = self.critical if kind in ('INTERNAL', 'TOTAL') else self.edges
        key = (start, end, kind)
        # Leading/trailing storage is intrinsically bounded by 2 * channels.
        if key not in table and table is self.critical and len(table) >= self.cap:
            self.omitted += 1
            return
        table.setdefault(key, []).append(ch+1)

    def feed(self, samples):
        if not len(samples):
            return
        for ch in range(self.channels):
            mask = samples[:, ch] == 0  # NaN/Inf are not digital silence.
            if self.open[ch] is not None and not mask[0]:
                start = self.open[ch]
                self._record(ch, start, self.frames, 'LEADING' if start == 0 else 'INTERNAL')
                self.open[ch] = None
            for left, right in runs(mask):
                start = self.open[ch] if left == 0 and self.open[ch] is not None else self.frames + int(left)
                if right == len(samples):
                    self.open[ch] = start
                else:
                    self._record(ch, start, self.frames+int(right), 'LEADING' if start == 0 else 'INTERNAL')
                    self.open[ch] = None
        self.frames += len(samples)

    def finish(self, *, complete):
        open_runs = [{'channel': ch+1, 'start_sample': start,
                      'observed_end_sample_exclusive': self.frames}
                     for ch, start in enumerate(self.open) if start is not None]
        if complete:
            for ch, start in enumerate(self.open):
                if start is not None:
                    self._record(ch, start, self.frames, 'TOTAL' if start == 0 else 'TRAILING')
            self.open = [None] * self.channels
        issues = []
        for (start, end, kind), channels in sorted({**self.critical, **self.edges}.items()):
            channels = sorted(channels)
            whole_file = len(channels) == self.channels
            name = ('MOS (SILENT FILE)' if whole_file else 'MOS (SILENT CHANNEL)') if kind == 'TOTAL' else (
                'DIGITAL SIGNAL LOSS' if kind == 'INTERNAL' else f'DIGITAL SILENCE ({kind})')
            facts = {'kind': kind, 'zero_samples': end-start, 'end_sample_exclusive': end,
                     'scope': 'ALL_CHANNELS' if whole_file else 'CHANNEL'}
            def fields(ch):
                return dict(timestamp_seconds=start/self.rate, sample_index=start, channel=ch,
                            event_type=name, duration_seconds=(end-start)/self.rate, severity=None,
                            measurements=dict(facts), detection_method=METHOD,
                            cluster_first_sample=start, cluster_last_sample=end-1)
            issues.append(DefectIssue(**fields(channels[0]), channels=channels,
                                     channel_events=[Defect(**fields(ch)) for ch in channels]))
        return ({'complete': bool(complete), 'checked_sample_frames': self.frames,
                 'min_samples': self.minimum, 'max_events': self.cap,
                 'channel_event_counts': dict(self.counts), 'retained_issues': len(issues),
                 'omitted_channel_events': self.omitted, 'truncated': bool(self.omitted),
                 'open_runs': [] if complete else open_runs}, issues)
