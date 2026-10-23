"""Bounded PCM spool and unchanged, globally aligned baseline detector windows."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import math
import tempfile

import numpy as np
from audio_qc.config import load_config
from audio_qc.defects import detect_window
from audio_qc.issues import IssueConsolidator
from audio_qc.metadata import inspect_metadata
from audio_qc.models import AudioFile
from audio_qc.process import ffmpeg_input, stream_process
from .scoring import WINDOWS_MS, score_context

BASELINE_SHA = '2e74a097455dbb30cd2f2df312e078aeae35a426'
BASELINE_HASHES = {
    'config.py': '5e8b16886e82eaee066d2692169a0876121bc5d7efc39130bad370f289e9f7ee',
    'defects.py': '959834f0119bff4fda4005c5215209a6fdac803e9e3ec53f76137acacbffbae0',
    'issues.py': '445845ce23aa66909cbc854a40335a517bad94837f626c9132366a3261964018',
    'consolidation.py': '751e3b5b06c13ce5dbae95026f1d5a6369a1eb4a601842916a9f5115b660dae2',
    'models.py': '4c1326777d74000d3762644e920b317004046e1f38b4cb53b42d14c21b66102e',
}
MAX_PCM_BYTES = 128 * 1024 * 1024


def check_baseline():
    import audio_qc
    root = Path(audio_qc.__file__).parent
    actual = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in BASELINE_HASHES}
    if actual != BASELINE_HASHES:
        raise ValueError('Imported detector differs from the accepted experiment baseline; refusing a misleading comparison')
    return {'commit': BASELINE_SHA, 'files': actual, 'import_path': str(root)}


def fingerprint(path):
    before = Path(path).stat()
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        while block := handle.read(1024 * 1024): h.update(block)
    after = Path(path).stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Source changed while hashing: {path}')
    return {'sha256': h.hexdigest(), 'size': after.st_size, 'mtime_ns': after.st_mtime_ns}


class PCMClip:
    """One temporary spool <=128 MiB; analysis reads small windows, never a master array."""
    def __init__(self, clip):
        self.clip, self.handle = clip, None

    def __enter__(self):
        audio = AudioFile(self.clip['file'], Path(self.clip['file']).name)
        inspect_metadata(Path(audio.path), audio)
        if audio.sample_rate != self.clip['sample_rate'] or audio.channels not in (1, 2, 6):
            raise ValueError('Expected manifest sample rate and mono/stereo/six-channel PCM')
        if not audio.codec.startswith('pcm_') or audio.stream_count != 1:
            raise ValueError('Only one physical PCM audio stream per source is supported')
        if max(self.clip['channels']) > audio.channels:
            raise ValueError('Annotation channel outside decoded physical channels')
        self.rate, self.channels = audio.sample_rate, audio.channels
        # A full extra second covers the unchanged 560 ms detector pad and 50 ms scoring context.
        core = max(8192, self.rate)
        self.start = max(0, (self.clip['start_sample'] // core - 1) * core)
        requested_end = ((self.clip['end_sample'] + core - 1) // core + 1) * core
        if (requested_end - self.start) * self.channels * 8 > MAX_PCM_BYTES:
            raise ValueError('Clip plus context exceeds 128 MiB temporary PCM limit; shorten the interval')
        self.handle = tempfile.TemporaryFile()
        try:
            args = ffmpeg_input(audio.path) + ['-af', f'atrim=start_sample={self.start}:end_sample={requested_end}',
                                             '-c:a', 'pcm_f64le', '-f', 'f64le', 'pipe:1']
            written = 0
            with stream_process(args, timeout=300) as pipe:
                while raw := pipe.read(8192 * self.channels * 8):
                    written += len(raw)
                    if written > MAX_PCM_BYTES or len(raw) % (8 * self.channels):
                        raise ValueError('Invalid or oversized decoded PCM stream')
                    if not np.all(np.isfinite(np.frombuffer(raw, '<f8'))):
                        raise ValueError('Nonfinite decoded samples prevent reliable evaluation')
                    self.handle.write(raw)
            self.end = self.start + written // (8 * self.channels)
            if self.end < self.clip['end_sample']:
                raise ValueError('Evaluation range exceeds exact decoded source samples')
            self.handle.flush()
            return self
        except BaseException:
            self.handle.close()
            raise

    def __exit__(self, *args):
        if self.handle: self.handle.close()

    def read(self, start, end):
        start, end = max(start, self.start), min(end, self.end)
        if end <= start: return np.empty((0, self.channels))
        self.handle.seek((start - self.start) * self.channels * 8)
        raw = self.handle.read((end - start) * self.channels * 8)
        if len(raw) != (end - start) * self.channels * 8: raise ValueError('Short PCM spool read')
        return np.frombuffer(raw, '<f8').reshape(-1, self.channels)


def detect_clip(pcm, clip):
    options = load_config()['defects']
    rate = pcm.rate
    hop = max(1, round(rate / 1000))
    pad = math.ceil((options['dropouts']['max_duration_ms'] / 1000 + .06) * rate / hop) * hop
    state = IssueConsolidator(rate, pcm.channels, options['clicks']['merge_gap_ms'],
                             options['issues']['cross_channel_merge_ms'], options['max_candidates'])
    core = max(8192, rate)
    for first in range((clip['start_sample'] // core) * core, clip['end_sample'], core):
        start, end = max(0, first - pad), min(pcm.end, first + core + pad)
        samples = pcm.read(start, end)
        candidates = detect_window(samples, rate, options, start,
                                   max(first, clip['start_sample']), min(first + core, clip['end_sample']))
        state.extend([c for c in candidates if c.channel in clip['channels']])
        state.advance(min(first + core, clip['end_sample']))
        if state.ready_to_stop: break
    return state.finish(), state.capped


def score_events(pcm, issues, *, methods=('temporal', 'prediction'), windows=WINDOWS_MS):
    rows = []
    for issue_index, issue in enumerate(issues):
        if issue.event_type != 'POSSIBLE CLICK / TICK': continue
        for event in issue.channel_events:
            first, end = event.cluster_first_sample, event.cluster_last_sample + 1
            scores = {}
            for window in windows if methods else ():
                radius = round(pcm.rate * window / 1000)
                if first - radius < pcm.start or end + radius > pcm.end or end - first > pcm.rate * .02:
                    result = {m: {'score': None, 'reason': 'insufficient_context_or_long_cluster'}
                              for m in methods}
                else:
                    x = pcm.read(first - radius, end + radius)[:, event.channel - 1]
                    result = score_context(x[:radius], x[radius:radius + end-first], x[radius + end-first:], pcm.rate,
                                           methods=methods)
                scores[str(window)] = result
            rows.append({'id': f'{issue_index + 1}:{event.channel}', 'issue_index': issue_index,
                         'sample_index': event.sample_index, 'channel': event.channel,
                         'original': asdict(event), 'scores': scores})
    return rows
