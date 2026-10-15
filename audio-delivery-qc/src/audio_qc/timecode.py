"""Reporting only: exact sample positions -> containing SMPTE video-frame labels.

23.976 means 24000/1001 and 29.97 means 30000/1001. No detector imports
this module, and reporting never changes samples, timestamps or BWF metadata.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FrameRate:
    label: str
    numerator: int
    denominator: int
    nominal: int
    drop_frame: bool = False

    @property
    def frames_per_day(self):
        return 2589408 if self.drop_frame else self.nominal * 86400

    def as_dict(self):
        return {"label": self.label, "numerator": self.numerator,
                "denominator": self.denominator, "nominal": self.nominal,
                "drop_frame": self.drop_frame}


RATES = {
    "23.976": FrameRate("23.976", 24000, 1001, 24),
    "24": FrameRate("24", 24, 1, 24),
    "25": FrameRate("25", 25, 1, 25),
    "29.97 NDF": FrameRate("29.97 NDF", 30000, 1001, 30),
    "29.97 DF": FrameRate("29.97 DF", 30000, 1001, 30, True),
    "30": FrameRate("30", 30, 1, 30),
}
SOURCES = ("AUTO", "FILE_RELATIVE", "MANUAL")
BASIS_LABELS = {"BWF_TIMEREFERENCE": "BWF TimeReference", "FILE_RELATIVE": "File-relative", "MANUAL": "Manual start TC"}


def parse_frame_rate(value) -> FrameRate:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Frame rate must be one of: " + ", ".join(RATES))
    key = str(value).strip().upper().replace(" ", "").replace("_", "").replace("29.97-", "29.97")
    aliases = {k.replace(" ", ""): k for k in RATES}
    aliases.update({"29.97": "29.97 NDF", "24000/1001": "23.976", "30000/1001": "29.97 NDF",
                    "24.0": "24", "25.0": "25", "30.0": "30"})
    if key not in aliases:
        raise ValueError("Unsupported reporting frame rate; choose " + ", ".join(RATES))
    return RATES[aliases[key]]


def parse_start_timecode(value, rate: FrameRate) -> int:
    """Return an exact frame count. Reject nonexistent DF labels and wrong separators."""
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})", value) if isinstance(value, str) else None
    if not match:
        raise ValueError("Manual start TC must be HH:MM:SS:FF (HH:MM:SS;FF for 29.97 DF)")
    h, m, s, separator, f = match.groups()
    h, m, s, f = map(int, (h, m, s, f))
    if h > 23 or m > 59 or s > 59 or f >= rate.nominal:
        raise ValueError(f"Manual start TC is outside the valid range for {rate.label}")
    if separator != (";" if rate.drop_frame else ":"):
        raise ValueError("Use ';' for 29.97 DF and ':' for non-drop-frame timecode")
    if rate.drop_frame and m % 10 != 0 and s == 0 and f < 2:
        raise ValueError("29.97 DF skips frame labels ;00 and ;01 at every minute except multiples of ten")
    nominal_frames = ((h * 60 + m) * 60 + s) * rate.nominal + f
    return nominal_frames - (2 * (h * 60 + m - (h * 60 + m) // 10) if rate.drop_frame else 0)


def format_frame(frame: int, rate: FrameRate) -> str:
    if type(frame) is not int or frame < 0:
        raise ValueError("Frame count must be a non-negative integer")
    # Wrap conventional TC at 24 hours; reporting also retains the day offset.
    frame %= rate.frames_per_day
    if rate.drop_frame:
        ten_minutes, remainder = divmod(frame, 17982)
        skipped_minutes = max(0, (remainder - 2) // 1798)
        frame += 18 * ten_minutes + 2 * skipped_minutes
    seconds, ff = divmod(frame, rate.nominal)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{';' if rate.drop_frame else ':'}{ff:02d}"


def _validate_sample_position(sample: int, sample_rate: int) -> None:
    if type(sample) is not int or sample < 0 or type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("A non-negative sample index and positive integer sample rate are required")


def sample_frame(sample: int, sample_rate: int, rate: FrameRate) -> int:
    _validate_sample_position(sample, sample_rate)
    return (sample * rate.numerator) // (sample_rate * rate.denominator)


def format_offset(sample: int, sample_rate: int) -> str:
    # Display the containing millisecond, without rounding into the next one.
    _validate_sample_position(sample, sample_rate)
    seconds, milliseconds = divmod(sample * 1000 // sample_rate, 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def validate_settings(settings):
    rate = parse_frame_rate(settings["frame_rate"])
    settings["frame_rate"] = rate.label
    source = settings["source"]
    if source not in SOURCES:
        raise ValueError("timecode.source must be AUTO, FILE_RELATIVE or MANUAL")
    if source == "MANUAL":
        parse_start_timecode(settings["manual_start"], rate)
    elif settings["manual_start"] is not None:
        raise ValueError("timecode.manual_start requires timecode.source: MANUAL")


def file_timecode(audio, settings):
    """Return an enriched report copy. Leave AudioFile and all Defect objects unchanged."""
    result = audio.to_dict()
    rate = parse_frame_rate(settings["frame_rate"])
    requested = settings["source"]
    reference = audio.bwf.get("time_reference")
    valid_reference = (audio.bwf.get("present") is True and type(reference) is int
                       and 0 <= reference <= 2**64 - 1)
    valid_rate = type(audio.sample_rate) is int and audio.sample_rate > 0
    basis, reason = "FILE_RELATIVE", None
    start_sample = 0
    start_frame = 0
    manual_frame = None
    if requested == "MANUAL":
        basis = "MANUAL"
        manual_frame = parse_start_timecode(settings["manual_start"], rate)
        start_frame = manual_frame
    elif requested == "AUTO" and valid_reference and valid_rate:
        basis = "BWF_TIMEREFERENCE"
        start_sample = reference
        start_frame = sample_frame(start_sample, audio.sample_rate, rate)
    elif requested == "AUTO":
        reason = "No valid BEXT TimeReference" if not valid_reference else "Sample rate unavailable for BEXT conversion"
    start_tc = format_frame(start_frame, rate)
    context = {"requested_source": requested, "basis": basis, "source_label": BASIS_LABELS[basis],
               "frame_rate": rate.as_dict(), "file_start_timecode": start_tc,
               "file_start_day_offset": start_frame // rate.frames_per_day,
               "fallback_reason": reason, "bwf_time_reference_used": reference if basis == "BWF_TIMEREFERENCE" else None}
    result["timecode_reporting"] = context
    def enrich(event):
        sample = event["sample_index"]
        valid_position = valid_rate and type(sample) is int and sample >= 0
        if valid_position:
            # Sum the BWF position BEFORE converting: it may start between frames.
            frame = (manual_frame + sample_frame(sample, audio.sample_rate, rate) if manual_frame is not None
                     else sample_frame(start_sample + sample, audio.sample_rate, rate))
            tc, day = format_frame(frame, rate), frame // rate.frames_per_day
            offset = format_offset(sample, audio.sample_rate)
        else:
            tc, day, offset = None, None, None
        event.update(timecode=tc, timecode_frame_rate=rate.label, timecode_basis=basis,
                     file_start_timecode=start_tc, timecode_day_offset=day, offset=offset)
        for channel_event in event.get("channel_events", []):
            enrich(channel_event)

    for event in result["defects"]:
        enrich(event)
    return result
