"""Pinned, optional ClickDetector adapter. No production imports of Essentia.

Frames own their central hop; all origins are integer source samples. The short
local clock is converted before adding the potentially very large file origin.
"""
from dataclasses import asdict
from importlib.metadata import version
from functools import lru_cache
from pathlib import Path
import hashlib
import math

import numpy as np
from audio_qc.issues import IssueConsolidator
from audio_qc.models import Defect

VERSION = '2.1b6.dev1438'
FRAME, HOP, ORDER = 512, 256, 12
MAX_RAW = 100_000  # independent forensic-output safety bound, never an issue cap


@lru_cache(maxsize=1)
def runtime():
    if version('essentia') != VERSION:
        raise ValueError(f'This experimental adapter requires essentia=={VERSION}')
    import essentia
    binary = Path(essentia._essentia.__file__)
    binaries = [binary, *sorted((binary.parent/'.dylibs').glob('libessentia*'))]
    hashes = {}
    for path in binaries:
        with path.open('rb') as handle:
            hashes[path.name] = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'distribution': version('essentia'), 'module_version': essentia.__version__, 'binary_sha256': hashes,
            'path': essentia.__file__, 'binding': '_essentia.Algorithm(ClickDetector)',
            'analysis_dtype': 'float32'}


class ClickDetector:
    def __init__(self, **parameters):
        runtime()
        import essentia
        # standard imports/constructs EVERY algorithm. Use only this pinned C++
        # binding; characterization tests verify configuration, outputs and state.
        self.algorithm = essentia._essentia.Algorithm('ClickDetector')
        self.algorithm.__configure__(**parameters)

    def __call__(self, frame):
        return self.algorithm.__compute__(frame)


def sample_interval(start, last, rate, origin):
    def recover(seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid Essentia timestamp')
        # float32 clock rounding must be strictly below half a source sample.
        # Also require round-trip to the exact returned float32, not an arbitrary
        # fractional timestamp merely rounded into a plausible sample.
        value = np.float32(seconds)
        if float(np.spacing(value)) * rate >= 1:
            raise ValueError('Essentia local clock cannot resolve individual samples')
        sample = round(seconds * rate)
        if np.float32(sample / rate) != value:
            raise ValueError('Essentia timestamp is not a sample-grid position')
        return sample
    first, end = recover(start), recover(last)
    if end < first: raise ValueError('Reversed Essentia interval')
    return origin + first, origin + end + 1


def detect(pcm, clip, parameters, *, factory=ClickDetector, max_events=1000, raw_sink=None):
    rate = pcm.rate
    if clip['end_sample'] - clip['start_sample'] > 60 * rate:
        raise ValueError('Essentia local streams are limited to 60 seconds')
    first_core = clip['start_sample'] // HOP * HOP
    origin = first_core - (FRAME - HOP) // 2
    settings = dict(frameSize=FRAME, hopSize=HOP, order=ORDER, sampleRate=float(rate),
                    detectionThreshold=float(parameters.get('detectionThreshold', 30)),
                    powerEstimationThreshold=10, silenceThreshold=-50)
    detectors = {ch: factory(**settings) for ch in sorted(clip['channels'])}
    state = IssueConsolidator(rate, pcm.channels, 1.0, 1.0, max_events)
    raw_count, raw_capped = 0, False
    for core in range(first_core, clip['end_sample'], HOP):
        start = core - 128
        if max(0, start) < pcm.start:
            raise ValueError('Missing real source context for Essentia frame')
        frame = np.zeros((FRAME, pcm.channels), dtype=np.float32)
        lo, hi = max(0, start), min(pcm.end, start + FRAME)
        if hi > lo: frame[lo-start:hi-start] = pcm.read(lo, hi)
        if not np.isfinite(frame).all(): raise ValueError('Nonfinite float32 analysis samples')
        candidates = []
        for channel, detector in detectors.items():
            starts, ends = detector(np.ascontiguousarray(frame[:, channel-1]))
            if len(starts) != len(ends): raise ValueError('Invalid Essentia output lengths')
            for a, b in zip(starts, ends):
                first, end = sample_interval(a, b, rate, origin)
                if not core <= first < end <= core + HOP:
                    raise ValueError('Essentia output escaped its owned central hop')
                if end <= clip['start_sample'] or first >= clip['end_sample']: continue
                first, end = max(first, clip['start_sample']), min(end, clip['end_sample'])
                if raw_count >= MAX_RAW:
                    raw_capped = True
                    break
                raw_count += 1
                values = {'duration_samples': end-first, 'raw_start_seconds': float(a),
                          'raw_last_seconds': float(b), 'clock_origin_sample': origin,
                          'frame_start_sample': start, 'raw_id': raw_count}
                if raw_sink: raw_sink(dict(channel=channel, start_sample=first, end_sample=end, **values))
                candidates.append(Defect(event_type='POSSIBLE CLICK / TICK', severity=None,
                                         timestamp_seconds=first/rate, sample_index=first,
                                         duration_seconds=(end-first)/rate, channel=channel,
                                         detection_method='Essentia ClickDetector', measurements=values))
            if raw_capped: break
        state.extend(sorted(candidates, key=lambda c: (c.sample_index, c.channel)))
        state.advance(min(core + HOP, clip['end_sample']))
        if raw_capped or state.ready_to_stop: break
    issues = state.finish()
    events = []
    for i, issue in enumerate(issues):
        for event in issue.channel_events:
            events.append({'id': f'essentia:{i+1}:{event.channel}', 'issue_index': i,
                           'sample_index': event.sample_index, 'channel': event.channel,
                           'end_sample': event.cluster_last_sample+1,
                           'merged_candidate_count': event.merged_candidate_count,
                           'original': asdict(event)})
    return {'events': events, 'issues': [asdict(i) for i in issues], 'channels': pcm.channels,
            'capped': state.capped or raw_capped, 'raw_output_capped': raw_capped,
            'raw_count': raw_count, 'parameters': settings}
