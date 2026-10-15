from collections import defaultdict
from pathlib import Path
import re
import statistics

from .models import Check, Status


def group_checks(files, config):
    checks = []
    valid = [a for a in files if a.sample_rate and a.decoded_duration_seconds is not None]

    def add(code, message, members, status=Status.WARNING):
        checks.append(Check(code, status, message, [a.path for a in members]))

    for field, title in (("sample_rate", "sample rates"), ("bit_depth", "bit depths"), ("codec", "codecs")):
        values = {getattr(a, field) for a in valid if getattr(a, field) is not None}
        if len(values) > 1:
            add(f"mixed_{field}", f"Group contains different {title}: {sorted(values)}. Confirm delivery requirements.", valid)
    counts = sorted({a.channels for a in valid})
    if len(counts) > 1:
        add("mixed_channels", f"Channel counts present: {counts}; mixed mono/stereo/surround deliveries can be intentional.", valid, Status.INFO)
    durations = [a.decoded_duration_seconds for a in valid]
    if len(durations) > 1:
        spread = max(durations)-min(durations)
        median = statistics.median(durations)
        tolerance = config["duration_tolerance_ms"]/1000
        if spread > tolerance + 1e-9:
            add("duration_spread", f"Duration spread {spread*1000:.3f} ms exceeds {tolerance*1000:g} ms; group median {median:.6f} s.", valid)
        large = config["large_duration_difference_ms"]/1000
        for a in valid:
            delta = a.decoded_duration_seconds-median
            if abs(delta) > max(large, tolerance) + 1e-9:
                add("duration_outlier", f"{a.filename} is {abs(delta):.3f} s {'longer' if delta > 0 else 'shorter'} than the group median; relationship is unverified.", [a])
    for field, code, label in (("filename", "duplicate_filename", "Duplicate filenames (case-insensitive)"),
                               ("sha256", "duplicate_file", "Byte-identical file SHA-256"),
                               ("audio_sha256", "duplicate_audio", "Identical decoded audio SHA-256 (same rate and channel order)")):
        groups = defaultdict(list)
        for a in files:
            value = getattr(a, field)
            if value:
                groups[value.casefold() if field == "filename" else value].append(a)
        for group in groups.values():
            if len(group) > 1:
                add(code, label, group)
    # Exact, delimited tokens + identical parent/name skeleton are strong evidence.
    stem_groups = defaultdict(dict)
    token = re.compile(r"(?<![A-Za-z0-9])(DIA|FX|MX|ME|M&E|FULLMIX)(?![A-Za-z0-9])", re.I)
    for a in files:
        path = Path(a.path)
        matches = list(token.finditer(path.stem))
        if len(matches) == 1:
            match = matches[0]
            name = match[1].upper().replace("&", "")
            skeleton = path.stem[:match.start()] + "{STEM}" + path.stem[match.end():]
            stem_groups[(str(path.parent), skeleton.casefold())][name] = a
    explicit = set(config["expected_stems"])
    for (_, skeleton), stems in stem_groups.items():
        if explicit:
            expected = explicit
        elif len(set(stems) & {"DIA", "FX", "MX"}) >= 2:
            expected = {"DIA", "FX", "MX"}
        else:
            continue
        missing = expected-set(stems)
        if missing:
            add("potential_missing_stems", f"Naming group {skeleton}: potentially missing {', '.join(sorted(missing))}. Confirm the intended delivery list.", list(stems.values()))
    return checks
