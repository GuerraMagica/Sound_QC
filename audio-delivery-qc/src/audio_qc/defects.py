"""Deterministic candidates with bounded, overlapping local context.

This is deliberately conservative: thresholds identify evidence for a listening
review, not a claim that a transient or an edit is artistically wrong.
"""
import math
import numpy as np

from .models import Defect
from .issues import IssueConsolidator


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))


def rms(x):
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def db(value):
    return 20 * math.log10(max(float(value), 1e-12))


def detect_window(data, rate, config, offset=0, core_start=0, core_end=None):
    """Indices are relative to source audio; channels are numbered from one."""
    if data.ndim == 1:
        data = data[:, None]
    length = len(data)
    core_end = offset + length if core_end is None else core_end
    context = max(8, round(rate * 0.025))
    candidates = []

    def event(ch, start, end, kind, values, method):
        absolute = offset + int(start)
        if core_start <= absolute < core_end:
            candidates.append(Defect(absolute / rate, absolute, ch + 1, kind,
                                     int(end - start) / rate, None, values, method))

    for ch in range(data.shape[1]):
        x = data[:, ch]
        drop_intervals = []
        if config["dropouts"]["enabled"]:
            cfg = config["dropouts"]
            min_n = max(2, math.ceil(rate * cfg["min_duration_ms"] / 1000))
            max_n = math.floor(rate * cfg["max_duration_ms"] / 1000)
            zero_n = max(min_n, math.ceil(rate * cfg["zero_run_ms"] / 1000))

            def dropout(start, end, method, exact=False):
                if start < context or end + context > length:
                    return
                pre, post = x[start-context:start], x[end:end+context]
                before, after = rms(pre), rms(post)
                baseline = min(before, after)
                if baseline < 10 ** (-65 / 20):
                    return  # sustained/edge silence is not evidence of a short dropout
                inside = rms(x[start:end])
                reduction = db(baseline) - db(inside)
                if not exact and reduction < cfg["relative_level_drop_db"]:
                    return
                values = {"local_rms_dbfs": db(baseline), "event_rms_dbfs": db(inside) if inside > 0 else None,
                          "relative_level_drop_db": reduction if inside > 0 else None,
                          "digital_zero": inside == 0,
                          "entry_step": float(abs(x[start] - x[start-1])),
                          "exit_step": float(abs(x[end] - x[end-1])),
                          "channel_specific": False}
                for other in range(data.shape[1]):
                    if other == ch:
                        continue
                    other_pre = data[start-context:start, other]
                    if np.std(pre) > 1e-8 and np.std(other_pre) > 1e-8:
                        correlation = float(np.corrcoef(pre, other_pre)[0, 1])
                        if abs(correlation) >= 0.7 and rms(data[start:end, other]) > rms(other_pre) * 0.5:
                            values.update(channel_specific=True, continuing_channel=other+1,
                                          context_correlation=correlation)
                            break
                drop_intervals.append((start, end))
                event(ch, start, end, "POSSIBLE DROPOUT", values, method)

            for start, end in runs(x == 0):
                if zero_n <= end - start <= max_n:
                    dropout(start, end, "digital_zero_run+active_surrounding_context", True)
            # Runs in diff correspond to one additional sample of a held value.
            for start, end in runs(np.diff(x) == 0):
                end += 1
                if x[start] != 0 and min_n <= end-start <= max_n:
                    dropout(start, end, "constant_sample_run+active_surrounding_context", True)
            hop = max(1, round(rate / 1000))
            count = length // hop
            if count > 4:
                energy = np.mean(x[:count*hop].reshape(count, hop) ** 2, axis=1)
                # The reference spans the longest configured dropout so the
                # middle of a long attenuation does not become its own baseline.
                # Exact two-sided context below makes the final level decision.
                radius = min(math.ceil(cfg["max_duration_ms"] * rate / (1000*hop)) + 25, (count-1)//2)
                local = np.convolve(energy, np.ones(2*radius+1)/(2*radius+1), mode="same")
                low = (energy < local * 10 ** (-(cfg["relative_level_drop_db"]-6) / 10)) & (local > 1e-8)
                for a, b in runs(low):
                    start, end = int(a*hop), int(b*hop)
                    if not min_n <= end-start <= max_n:
                        continue
                    if any(start < e+hop and end > s-hop for s, e in drop_intervals):
                        continue
                    # Both edges must be abrupt at the 1 ms energy scale.
                    if a == 0 or b >= count or min(energy[a-1], energy[b]) < local[a] * 0.05:
                        continue
                    dropout(start, end, "1ms_energy_collapse+two_sided_local_RMS")

        if config["clicks"]["enabled"] and length > context * 2:
            cfg = config["clicks"]
            diff = np.diff(x)
            max_n = max(1, math.floor(rate * cfg["max_duration_ms"] / 1000))
            tile = max(16, round(rate * 0.05))
            factor = {"low": 16, "medium": 10, "high": 6}[cfg["sensitivity"]]
            edges = []
            # Local robust scale rather than an absolute signal peak threshold.
            for start in range(0, len(diff), tile):
                local_diff = diff[max(0, start-tile):min(len(diff), start+2*tile)]
                median = np.median(local_diff)
                mad = float(np.median(np.abs(local_diff-median)))
                threshold = max(1e-7, factor * 1.4826 * mad)
                part = diff[start:start+tile]
                edges.extend((np.flatnonzero(np.abs(part-median) > threshold) + start).tolist())
            consumed = -1
            for pos, edge in enumerate(edges):
                if edge <= consumed or edge < context:
                    continue
                for second in edges[pos+1:pos+65]:
                    gap = second-edge
                    if gap > max_n:
                        break
                    if diff[edge] * diff[second] >= 0 or not 0.3 <= abs(diff[edge]/diff[second]) <= 3.3:
                        continue
                    start, end = edge+1, second+1
                    if end+context > length or any(start < e+context//4 and end > s-context//4 for s, e in drop_intervals):
                        continue
                    surrounding = np.r_[x[start-context:start], x[end:end+context]]
                    local_rms = rms(surrounding)
                    baseline = float(np.median(surrounding))
                    impulse = float(np.max(np.abs(x[start:end]-baseline)))
                    deviation = db(impulse) - db(max(local_rms, 1e-7))
                    if deviation < cfg["min_local_deviation_db"]:
                        continue
                    event(ch, start, end, "POSSIBLE CLICK / TICK",
                          {"local_rms_dbfs": db(local_rms) if local_rms > 0 else None,
                           "impulse_deviation_db": deviation, "comparison_rms_floor_dbfs": -140.0,
                           "entry_derivative": float(diff[edge]), "exit_derivative": float(diff[second]),
                           "duration_samples": end-start},
                          "local_derivative_MAD+opposite_edges+isolated_impulse_vs_RMS")
                    consumed = second
                    break
    return sorted(candidates, key=lambda e: (e.sample_index, e.channel, e.event_type))


class StreamingDefects:
    def __init__(self, rate, channels, config):
        self.rate, self.channels, self.config = rate, channels, config
        self.core = max(8192, rate)
        hop = max(1, round(rate / 1000))
        self.pad = math.ceil((config["dropouts"]["max_duration_ms"] / 1000 + 0.06) * rate / hop) * hop
        if (self.core + 2*self.pad + 8192) * channels * 8 > 128 * 1024 * 1024:
            raise ValueError("Defect analysis would exceed the 128 MiB window limit for this format")
        self.buffer = np.empty((0, channels), dtype=np.float64)
        self.base = 0
        self.next_core = 0
        self.consolidator = IssueConsolidator(rate, channels, config["clicks"]["merge_gap_ms"],
                                             config["issues"]["cross_channel_merge_ms"], config["max_candidates"])
        self.events = self.consolidator.issues
        self.capped = False

    def feed(self, samples, final=False):
        if self.capped:
            return
        self.buffer = np.concatenate((self.buffer, samples))
        total = self.base + len(self.buffer)
        while self.next_core < total and (final or total >= self.next_core+self.core+self.pad):
            start = max(self.base, self.next_core-self.pad)
            end = min(total, self.next_core+self.core+self.pad)
            detected = detect_window(self.buffer[start-self.base:end-self.base], self.rate, self.config,
                                     start, self.next_core, min(total, self.next_core+self.core))
            self.consolidator.extend(detected)
            self.next_core += self.core
            self.consolidator.advance(min(total, self.next_core))
            if self.consolidator.ready_to_stop:
                self.capped = True
                self.buffer = np.empty((0, self.channels))
                break
            keep = max(self.base, self.next_core-self.pad)
            self.buffer = self.buffer[keep-self.base:].copy()
            self.base = keep

    def finish(self):
        self.feed(np.empty((0, self.channels)), final=True)
        self.capped = self.consolidator.capped
        return self.consolidator.finish()
