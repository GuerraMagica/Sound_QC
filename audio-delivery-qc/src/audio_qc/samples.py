"""One streaming decode for sample peak, clipping, duration, optional defects/hash."""
import hashlib
import math
import struct

import numpy as np

from .defects import StreamingDefects, runs
from .measurement import MeasurementContext, MeasurementRequirements, ZeroRun
from .process import ffmpeg_input, stream_process, ToolError


class RunCounter:
    """Retain just the longest run and unfinished tail across blocks."""
    def __init__(self):
        self.tail = 0
        self.longest = 0
        self.start = 0

    def feed(self, mask, offset):
        carry = self.tail
        self.tail = 0
        for start, end in runs(mask):
            length = int(end-start) + (carry if start == 0 else 0)
            absolute = offset + int(start) - (carry if start == 0 else 0)
            if length > self.longest:
                self.longest, self.start = length, absolute
            if end == len(mask):
                self.tail = length


def analyze_samples(path, audio, requirements: MeasurementRequirements,
                    context: MeasurementContext | None = None, progress=None):
    context = context if context is not None else MeasurementContext()
    options = requirements.defect_options
    channels, rate = audio.channels, audio.sample_rate
    peak = np.zeros(channels)
    rail_count = np.zeros(channels, dtype=np.int64)
    overloads = 0
    frames = 0
    bad_samples = 0
    plus, minus, zeros = ([RunCounter() for _ in range(channels)] for _ in range(3))
    detector = None
    if options is not None:
        try:
            detector = StreamingDefects(rate, channels, options)
        except ValueError as exc:
            context.defects_unavailable = str(exc)
    bits = audio.bit_depth
    integer_pcm = bool(audio.codec and audio.codec.startswith(("pcm_s", "pcm_u")))
    upper = 1 - 2 ** (1-bits) if integer_pcm and bits and bits <= 32 else 1.0
    digest = hashlib.sha256(struct.pack("<II", rate, channels)) if requirements.hash else None
    args = ffmpeg_input(path) + ["-c:a", "pcm_f64le", "-f", "f64le", "pipe:1"]
    with stream_process(args, requirements.timeout_seconds) as output:
        while raw := output.read(8192 * channels * 8):
            if len(raw) % (8*channels):
                raise ToolError("Decoder produced an incomplete sample frame")
            samples = np.frombuffer(raw, dtype="<f8").reshape(-1, channels)
            if digest:
                digest.update(raw)
            finite = np.isfinite(samples)
            bad_samples += int(samples.size - np.count_nonzero(finite))
            if not np.all(finite):
                samples = np.where(finite, samples, 0.0)
            peak = np.maximum(peak, np.max(np.abs(samples), axis=0))
            overloads += int(np.count_nonzero(np.abs(samples) > 1.0))
            rail_count += np.count_nonzero((samples >= upper) | (samples <= -1.0), axis=0)
            for ch in range(channels):
                plus[ch].feed(samples[:, ch] >= upper, frames)
                minus[ch].feed(samples[:, ch] <= -1.0, frames)
                if options is not None and options["dropouts"]["enabled"]:
                    zeros[ch].feed(samples[:, ch] == 0, frames)
            if detector:
                detector.feed(samples)
            frames += len(samples)
            if progress:
                progress(frames / rate / audio.duration_seconds if audio.duration_seconds else 0)
    if frames == 0:
        raise ToolError("Audio stream decoded to zero sample frames")
    audio.decoded_duration_seconds = frames / rate
    audio.audio_sha256 = digest.hexdigest() if digest else None
    longest = [max(p.longest, m.longest) for p, m in zip(plus, minus)]
    audio.measurements.update(
        decoded_sample_frames=frames,
        sample_peak_dbfs=20*math.log10(float(peak.max())) if peak.max() > 0 else None,
        digital_silence=bool(peak.max() == 0),
        channel_sample_peak_dbfs=[20*math.log10(float(p)) if p > 0 else None for p in peak],
        rail_samples_per_channel=rail_count.tolist(), longest_rail_run_per_channel=longest,
        overload_samples=overloads, nonfinite_samples=bad_samples,
        longest_zero_run_per_channel=[z.longest for z in zeros] if options is not None else None,
    )
    if detector:
        audio.defects = detector.finish()
        context.defects_capped = detector.capped
    context.zero_runs = tuple(ZeroRun(z.longest, z.start) for z in zeros)
    return context
