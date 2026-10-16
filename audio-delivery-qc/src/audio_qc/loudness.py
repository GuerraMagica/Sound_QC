"""FFmpeg EBU R128 pass-through measurement; no audio gain processing."""
import math
import re

from .process import ffmpeg_input, stream_process
from .models import MeasurementOutcome, MeasurementState as MS

# Explicit channel assignments only. Immersive/object layouts need a specified render.
SUPPORTED_LAYOUTS = {"mono", "stereo", "2.1", "3.0", "3.0(back)", "4.0", "quad",
                     "quad(side)", "3.1", "5.0", "5.0(side)", "4.1", "5.1", "5.1(side)",
                     "6.0", "6.0(front)", "hexagonal", "6.1", "6.1(back)", "6.1(front)",
                     "7.0", "7.0(front)", "7.1", "7.1(wide)", "7.1(wide-side)", "octagonal"}
NUM = r"[-+]?(?:\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|inf|nan)"


class LoudnessParser:
    def __init__(self):
        self.values = {}
        self.max_m = None
        self.max_s = None
        self.frame_time = -1.0
        self.in_true_peak = False
        self.true_peak = None
        self.saw_summary = False
        self.invalid = set()
        self.saw_peak = False

    def feed(self, line: str) -> None:
        frame = re.search(r"pts_time:([\d.eE+-]+)", line)
        if frame:
            self.frame_time = float(frame[1])
        match = re.search(r"lavfi\.r128\.(I|M|S|LRA)=(\S*)", line, re.I)
        if match:
            key = match[1].upper()
            if not re.fullmatch(NUM, match[2], re.I):
                self.invalid.add(key)
                self.values.pop(key, None)
                return
            value = float(match[2])
            if value == -math.inf and key in {"I", "M", "S"}:
                self.values[key] = value  # Legitimate logarithmic silence, never a numeric report value.
            elif not math.isfinite(value):
                self.values.pop(key, None)
                self.invalid.add(key)
            else:
                self.values[key] = value
                if key == "M" and self.frame_time >= 0.299999 and value > -119:
                    self.max_m = max(self.max_m if self.max_m is not None else value, value)
                if key == "S" and self.frame_time >= 2.899999 and value > -119:
                    self.max_s = max(self.max_s if self.max_s is not None else value, value)
        if "Summary:" in line:
            self.saw_summary = True
            self.saw_peak = False
            self.true_peak = None
            self.in_true_peak = False
        if "True peak:" in line:
            self.in_true_peak = True
        elif self.in_true_peak:
            peak = re.search(r"Peak:\s*(\S+)\s*dB(?:FS|TP)", line, re.I)
            if peak:
                self.saw_peak = True
                if not re.fullmatch(NUM, peak[1], re.I):
                    self.invalid.add("TP")
                    value = math.nan
                else:
                    value = float(peak[1])
                if math.isnan(value) or value == math.inf:
                    self.invalid.add("TP")
                self.true_peak = value if math.isfinite(value) else None
                self.in_true_peak = False

    def result(self, duration: float | None) -> dict:
        if not self.saw_summary:
            reason = "FFmpeg did not produce a complete EBU R128 summary"
            return {"loudness_unavailable": reason, "measurement_outcomes": {
                k: MeasurementOutcome(MS.ERROR, reason) for k in ("integrated_lufs", "true_peak_dbtp")}}
        duration = duration or 0
        integrated = self.values.get("I")
        if duration < 0.4 or integrated is None or integrated <= -69.999:
            integrated = None  # -70 is FFmpeg's no-gated-programme sentinel
        outcomes = {}
        if self.invalid & {"I", "M", "S", "LRA"} or (duration >= 0.4 and "I" not in self.values):
            integrated = None
            outcomes["integrated_lufs"] = MeasurementOutcome(MS.ERROR, "Invalid or missing EBU R128 loudness metadata")
        else:
            outcomes["integrated_lufs"] = MeasurementOutcome(
                MS.SUCCESS if integrated is not None else MS.UNAVAILABLE,
                None if integrated is not None else "Short programme or no signal above the loudness gate")
        if "TP" in self.invalid or not self.saw_peak:
            self.true_peak = None
            outcomes["true_peak_dbtp"] = MeasurementOutcome(MS.ERROR, "Invalid or missing EBU R128 True Peak summary")
        else:
            outcomes["true_peak_dbtp"] = MeasurementOutcome(
                MS.SUCCESS if self.true_peak is not None else MS.UNAVAILABLE,
                None if self.true_peak is not None else "True Peak is negative infinity (digital silence)")
        return {
            "measurement_outcomes": outcomes,
            "integrated_lufs": integrated,
            "lra_lu": self.values.get("LRA") if integrated is not None and duration >= 3 else None,
            "max_momentary_lufs": self.max_m if duration >= 0.4 and outcomes["integrated_lufs"].state != MS.ERROR else None,
            "max_short_term_lufs": self.max_s if duration >= 3 and outcomes["integrated_lufs"].state != MS.ERROR else None,
            "true_peak_dbtp": self.true_peak,
            "true_peak_resolution_db": 0.1,
            "loudness_method": "FFmpeg ebur128; native channel layout; dualmono=false; 100 ms updates",
        }


def measure_loudness(path, audio, timeout=None, progress=None) -> dict:
    layout = audio.channel_layout
    if not layout and audio.channels in (1, 2):
        layout = "mono" if audio.channels == 1 else "stereo"
    if layout not in SUPPORTED_LAYOUTS:
        reason = "No supported explicit channel layout; channel weighting cannot be verified"
        return {"loudness_unavailable": reason, "measurement_outcomes": {
            k: MeasurementOutcome(MS.UNAVAILABLE, reason) for k in ("integrated_lufs", "true_peak_dbtp")}}
    parser = LoudnessParser()

    def feed(line):
        parser.feed(line)
        if progress and parser.frame_time >= 0:
            progress(parser.frame_time / audio.duration_seconds if audio.duration_seconds else 0)

    args = ffmpeg_input(path, "info")
    if not audio.channel_layout:
        # Only the already-probed mono/stereo counts reach here. Assign their
        # conventional layout at input: FFmpeg 6 cannot relabel an unknown
        # layout via aformat during filtering. Never guess multichannel roles.
        args[args.index("-guess_layout_max") + 1] = str(audio.channels)
    filters = "ebur128=metadata=1:peak=true:dualmono=false,ametadata=mode=print"
    args += ["-af", filters, "-f", "null", "-"]
    with stream_process(args, timeout, feed) as output:
        while output.read(8192):
            pass
    return parser.result(audio.decoded_duration_seconds or audio.duration_seconds)
