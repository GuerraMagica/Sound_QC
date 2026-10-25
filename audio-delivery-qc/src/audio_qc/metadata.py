import json
import math
from fractions import Fraction
from pathlib import Path

from .models import AudioFile
from .process import ToolError, stream_process


def finite_number(value) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def positive_int(value) -> int | None:
    n = finite_number(value)
    return int(n) if n is not None and n > 0 and n.is_integer() else None


def _resolve_bit_depth(stream: dict, audio: AudioFile) -> None:
    raw = positive_int(stream.get("bits_per_raw_sample"))
    stored = positive_int(stream.get("bits_per_sample"))
    depth = raw or stored
    source = "FFPROBE" if depth is not None else None
    reason = None
    header = audio.bwf.get("wave_format")
    # Compressed WAVE formats have format-specific bit fields: retain the existing
    # ffprobe behavior, never reinterpret their storage as PCM precision.
    if header is not None and header.get('format_tag') in (None, 1, 3, 65534):
        header_depth = header["bit_depth"]
        reason = header.get("reason")
        if header_depth is not None:
            codec = audio.codec or ""
            expected_encoding = ("float" if codec.startswith("pcm_f") else
                                 "integer" if codec.startswith(("pcm_s", "pcm_u")) else None)
            if (header['channels'] != audio.channels or header['sample_rate'] != audio.sample_rate
                    or expected_encoding != header['encoding']):
                reason = "WAVE format and ffprobe disagree on channels, sample rate or encoding"
            elif raw is not None and raw != header_depth:
                reason = "WAVE valid-bit depth and ffprobe raw bit depth disagree"
            elif stored is not None and stored not in (header_depth, header['container_bits']):
                reason = "WAVE format and ffprobe sample bit depth disagree"
            elif depth is None or (raw is None and stored != header_depth):
                depth, source = header_depth, "WAVE_FMT"
        if reason:
            depth, source = None, None
    audio.bit_depth = depth
    audio.metadata['bit_depth_provenance'] = {
        'source': source, 'ffprobe_raw_bits': raw, 'ffprobe_sample_bits': stored,
        'wave_bit_depth': header.get('bit_depth') if header else None,
        'reason': reason or ("Bit depth unavailable from metadata" if depth is None else None),
    }


def parse_probe(data: dict, audio: AudioFile) -> None:
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    audio.stream_count = len(streams)
    if not streams:
        raise ToolError("ffprobe found no audio stream")
    s = streams[0]
    audio.sample_rate = positive_int(s.get("sample_rate"))
    audio.channels = positive_int(s.get("channels"))
    audio.codec = s.get("codec_name")
    audio.pcm_format = s.get("sample_fmt")
    audio.channel_layout = s.get("channel_layout") or None
    audio.duration_seconds = finite_number(s.get("duration"))
    if audio.duration_seconds is None and s.get("duration_ts") is not None and s.get("time_base"):
        try:
            audio.duration_seconds = float(int(s["duration_ts"]) * Fraction(s["time_base"]))
        except (ValueError, ZeroDivisionError):
            pass
    if audio.duration_seconds is None:
        audio.duration_seconds = finite_number(data.get("format", {}).get("duration"))
    if audio.duration_seconds is not None and audio.duration_seconds < 0:
        audio.duration_seconds = None
    audio.metadata = {"container": data.get("format", {}).get("format_name"),
                      "format_tags": data.get("format", {}).get("tags", {}),
                      "stream_tags": s.get("tags", {})}
    _resolve_bit_depth(s, audio)
    if not audio.sample_rate or not audio.channels:
        raise ToolError("Missing/invalid sample rate or channel count")
    if audio.channels > 256 or audio.sample_rate > 768000:
        raise ToolError("Format exceeds supported limits (256 channels / 768 kHz)")


def inspect_metadata(path: Path, audio: AudioFile, *, cancel=None) -> None:
    args = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "stream=codec_type,codec_name,sample_fmt,sample_rate,channels,channel_layout,bits_per_sample,bits_per_raw_sample,duration,duration_ts,time_base:stream_tags:format=format_name,duration:format_tags",
            "-of", "json", str(path)]
    with stream_process(args, timeout=60, **({"cancel": cancel} if cancel else {})) as output:
        raw = output.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ToolError("ffprobe metadata exceeds 2 MiB safety limit")
    try:
        parse_probe(json.loads(raw), audio)
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        raise ToolError(f"Invalid ffprobe JSON: {exc}") from exc
