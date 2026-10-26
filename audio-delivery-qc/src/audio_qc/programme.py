"""Validated media relationships and cross-file evidence; no acoustic QC rules.

Filename discovery is opt-in and exact (directory + entire case-sensitive stem).
Only complete, mono PCM WAV groups with exact matching lengths/alignment enter
consolidation. All positions are integer samples; no audio is decoded here.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import yaml

from .config import ConfigError, UniqueLoader
from .consolidation import _cluster
from .issues import can_join_issue
from .models import MeasurementState, highest_severity

LAYOUTS = {"stereo": ("L", "R"), "5.1": ("L", "R", "C", "LFE", "Ls", "Rs")}
ROLES = LAYOUTS["5.1"]
DEFAULT_SUFFIXES = {role: ["_" + role, "." + role] for role in ROLES}
MODES = ("auto", "bwf_time_reference", "common_file_start")


@dataclass(frozen=True)
class ProgrammeMember:
    channel: str
    file: str


@dataclass(frozen=True)
class ProgrammeDefinition:
    id: str
    name: str
    layout: str
    alignment: str
    members: tuple[ProgrammeMember, ...]
    identity_source: str = "explicit manifest"


def _fields(value, allowed, required, location):
    if not isinstance(value, dict):
        raise ConfigError(f"{location}: expected a mapping")
    extra, missing = set(value) - set(allowed), set(required) - set(value)
    if extra or missing:
        raise ConfigError(f"{location}: unknown fields {sorted(extra)}; missing fields {sorted(missing)}")


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{location}: expected nonempty text")
    return value


def default_group_settings():
    return {"schema_version": 1, "naming": {"enabled": True, "layout": "auto", "alignment": "auto",
                                          "suffixes": deepcopy(DEFAULT_SUFFIXES)}, "programme_groups": []}


def load_group_settings(path):
    path = Path(path).expanduser().resolve()
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Programme groups: {exc}") from exc
    return validate_group_settings(value, path.parent)


def validate_group_settings(value, directory):
    """Normalize to plain data with absolute paths, safe for GUI snapshots."""
    _fields(value, ("schema_version", "naming", "programme_groups"), ("schema_version",), "groups")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ConfigError("groups.schema_version must be 1")
    naming = value.get("naming", {})
    _fields(naming, ("enabled", "layout", "alignment", "suffixes"), (), "groups.naming")
    resolved = default_group_settings()
    resolved["naming"]["enabled"] = False
    resolved["naming"].update(naming)
    naming = resolved["naming"]
    if type(naming["enabled"]) is not bool:
        raise ConfigError("groups.naming.enabled must be boolean")
    if naming["layout"] not in ("auto", *LAYOUTS):
        raise ConfigError("groups.naming.layout must be auto, stereo or 5.1")
    if naming["alignment"] not in MODES:
        raise ConfigError("groups.naming.alignment must be auto, bwf_time_reference or common_file_start")
    suffixes = naming["suffixes"]
    _fields(suffixes, ROLES, (), "groups.naming.suffixes")
    seen = set()
    for role, endings in suffixes.items():
        if not isinstance(endings, list) or not endings:
            raise ConfigError(f"suffixes.{role} must be a nonempty list")
        for suffix in endings:
            _text(suffix, f"suffixes.{role}")
            if suffix[0] not in "_.-" or any(c in suffix for c in "/\\\0") or suffix in seen:
                raise ConfigError(f"Invalid or duplicate suffix: {suffix!r}")
            seen.add(suffix)
    # Overlapping endings create two possible identities for one filename.
    if any(a != b and a.endswith(b) for a in seen for b in seen):
        raise ConfigError("Channel suffixes must not overlap")
    required_roles = ROLES if naming["layout"] == "auto" else LAYOUTS[naming["layout"]]
    if naming["enabled"] and not set(required_roles) <= set(suffixes):
        raise ConfigError("Naming suffixes must cover all channels of the selected layout")
    groups = value.get("programme_groups", [])
    if not isinstance(groups, list):
        raise ConfigError("programme_groups must be a list")
    ids = set()
    normalized = []
    for group in groups:
        _fields(group, ("id", "name", "layout", "alignment", "members"), ("id", "layout", "alignment", "members"), "programme_groups[]")
        identifier = _text(group["id"], "group.id")
        if identifier.startswith("naming:") or identifier in ids:
            raise ConfigError("Group IDs must be unique; naming: is reserved")
        ids.add(identifier)
        name = _text(group.get("name", identifier), "group.name")
        if not isinstance(group["layout"], str) or group["layout"] not in LAYOUTS:
            raise ConfigError("group.layout must be stereo or 5.1")
        _fields(group["alignment"], ("mode",), ("mode",), "group.alignment")
        if group["alignment"]["mode"] not in MODES:
            raise ConfigError("Unknown group alignment mode")
        if not isinstance(group["members"], list) or not group["members"]:
            raise ConfigError("group.members must be a nonempty list")
        members = []
        for member in group["members"]:
            _fields(member, ("channel", "file"), ("channel", "file"), "group.member")
            if not isinstance(member["channel"], str) or member["channel"] not in ROLES:
                raise ConfigError("Unknown logical programme channel")
            file = Path(_text(member["file"], "member.file")).expanduser()
            members.append({"channel": member["channel"], "file": str((Path(directory) / file).resolve())})
        normalized.append({"id": identifier, "name": name, "layout": group["layout"],
                           "alignment": {"mode": group["alignment"]["mode"]}, "members": members})
    naming["suffixes"] = {role: list(endings) for role, endings in suffixes.items()}
    resolved["programme_groups"] = normalized
    return deepcopy(resolved)


def discover_programmes(paths, settings):
    definitions = [ProgrammeDefinition(g["id"], g["name"], g["layout"], g["alignment"]["mode"],
                   tuple(ProgrammeMember(**m) for m in g["members"])) for g in settings["programme_groups"]]
    explicit = {m.file for g in definitions for m in g.members}
    naming = settings["naming"]
    found = defaultdict(list)
    if naming["enabled"]:
        for path in sorted({Path(p).resolve() for p in paths}, key=str):
            if str(path) in explicit or path.suffix.lower() not in (".wav", ".wave", ".bwf", ".rf64", ".bw64"):
                continue
            for role, endings in naming["suffixes"].items():
                for suffix in endings:
                    if path.stem.endswith(suffix) and len(path.stem) > len(suffix):
                        identity = path.stem[:-len(suffix)]
                        found[(str(path.parent), identity)].append(ProgrammeMember(role, str(path)))
        for (parent, identity), members in sorted(found.items()):
            layout = naming["layout"]
            if layout == "auto":
                layout = "5.1" if any(m.channel not in ("L", "R") for m in members) else "stereo"
            identifier = "naming:" + sha256((parent + "\0" + identity).encode()).hexdigest()[:24]
            definitions.append(ProgrammeDefinition(identifier, identity, layout, naming["alignment"], tuple(members),
                                                    "exact filename stem and parent directory"))
    return tuple(definitions)


def _reference(audio):
    value = audio.bwf.get("time_reference")
    return value if audio.bwf.get("present") is True and type(value) is int and 0 <= value < 2**64 else None


def build_programmes(definitions, files, *, detection_enabled, cross_channel_merge_ms=1.0, max_issues=1000):
    """Reuse bounded file results; never decode, apply thresholds or mutate input."""
    by_path = {str(Path(a.path).resolve()): a for a in files}
    owners = defaultdict(set)
    for definition in definitions:
        for member in definition.members:
            owners[member.file].add(definition.id)
    return [_build_group(d, by_path, owners, detection_enabled, cross_channel_merge_ms, max_issues) for d in definitions]


def _build_group(definition, by_path, owners, enabled, tolerance, limit):
    members, reasons, warnings = [], [], []

    def reject(code, message, category="TECHNICALLY_INCONSISTENT"):
        reasons.append({"code": code, "message": message, "category": category})

    roles = [m.channel for m in definition.members]
    expected = LAYOUTS[definition.layout]
    missing = [r for r in expected if r not in roles]
    if missing:
        reject("missing_channels", "Missing logical channels: " + ", ".join(missing), "INCOMPLETE")
    if len(roles) != len(set(roles)):
        reject("duplicate_channels", "Several files compete for the same channel", "AMBIGUOUS")
    if set(roles) - set(expected):
        reject("unexpected_channels", "Channel assignments do not match the declared layout", "AMBIGUOUS")
    paths = [m.file for m in definition.members]
    if len(set(paths)) != len(paths):
        reject("duplicate_file", "One physical file has multiple channel assignments", "AMBIGUOUS")
    if any(len(owners[p]) > 1 for p in paths):
        reject("shared_file", "A physical file belongs to several programme groups", "AMBIGUOUS")
    audios = []
    for member in sorted(definition.members, key=lambda m: (ROLES.index(m.channel), m.file)):
        audio = by_path.get(member.file)
        if audio is None or not Path(member.file).is_file():
            reject("missing_media", f"No measured source: {member.file}", "INCOMPLETE")
            members.append({"channel": member.channel, "file": member.file, "physical_channel": 1, "available": False})
            continue
        audios.append((member, audio))
        if audio.bwf.get("present") is True and _reference(audio) is None:
            reject("invalid_bwf", f"BWF TimeReference cannot be interpreted reliably: {member.file}")
        count = audio.measurements.get("decoded_sample_frames")
        outcome = audio.measurement_outcomes.get("samples")
        if outcome is None or outcome.state != MeasurementState.SUCCESS or type(count) is not int or count <= 0:
            reject("unreadable_media", f"Complete decoded samples unavailable: {member.file}")
        if audio.channels != 1:
            reject("not_mono", f"Expected one physical channel: {member.file}")
        if (not audio.codec or not audio.codec.startswith("pcm_") or
                Path(member.file).suffix.lower() not in (".wav", ".wave", ".bwf", ".rf64", ".bw64")):
            reject("unsupported_format", f"M5 multiple-mono members must be PCM WAV/BWF: {member.file}")
        if audio.bwf.get("errors") or any(d.code == "source_changed" for d in audio.operational_diagnostics):
            reject("unreliable_source", f"Container errors or changed source: {member.file}")
        members.append({"channel": member.channel, "file": member.file, "physical_channel": 1, "available": True,
                        "sample_rate": audio.sample_rate, "sample_count": count, "bit_depth": audio.bit_depth,
                        "codec": audio.codec, "bwf_time_reference": _reference(audio),
                        "file_status": audio.status.value, "execution_status": audio.execution_status.value})
    available = [m for m in members if m["available"]]
    rates = {m["sample_rate"] for m in available}
    counts = {m["sample_count"] for m in available}
    references = [m["bwf_time_reference"] for m in available]
    rate = next(iter(rates)) if len(rates) == 1 else None
    if type(rate) is not int or rate <= 0:
        reject("sample_rate_mismatch", "A common positive integer sample rate is required")
    if len(counts) > 1:
        reject("sample_count_mismatch", "Exact decoded sample counts differ; no padding or trimming applied")
    if len({m["codec"] for m in available}) > 1 or len({m["bit_depth"] for m in available}) > 1:
        warnings.append({"code": "mixed_pcm_formats", "message": "PCM encodings/bit depths differ; exact sample alignment remains possible"})
    mode = definition.alignment
    if mode == "auto":
        if references and all(r is not None for r in references):
            mode = "bwf_time_reference"
        elif references and all(r is None for r in references):
            mode = "common_file_start"
            warnings.append({"code": "assumed_common_start", "message": "No BWF origins: common-file-start assumption requires exact identity, rate and length validation; verify editorial alignment"})
        else:
            reject("mixed_timing", "BWF alignment cannot be resolved; explicit alignment is required")
            mode = "unresolved"
    origin = 0
    if mode == "bwf_time_reference":
        if not references or any(r is None for r in references):
            reject("missing_bwf", "BWF mode requires a valid TimeReference for every member")
        else:
            origin = min(references)
            if len(set(references)) != 1:
                reject("bwf_start_mismatch", "Different BWF starts: conservative M5 validation rejects this group; no inferred resynchronization")
    elif mode == "common_file_start" and len({r for r in references if r is not None}) > 1:
        warnings.append({"code": "bwf_contradicts_common_start", "message": "BWF origins differ; explicit common_file_start governs alignment"})
    alignment_available = (type(rate) is int and rate > 0 and mode != "unresolved"
                           and (mode != "bwf_time_reference" or references and all(r is not None for r in references)))
    if not alignment_available:
        origin = None
    for m in available:
        start = (m["bwf_time_reference"] - origin if mode == "bwf_time_reference" else 0) if alignment_available else None
        m["start_sample"] = start
        m["end_sample_exclusive"] = start + m["sample_count"] if start is not None and type(m["sample_count"]) is int else None
    extent = [m for m in available if m.get("end_sample_exclusive") is not None]
    coverage = None
    if extent and type(rate) is int and rate > 0 and len(extent) == len(members):
        starts = [m["start_sample"] for m in extent]
        ends = [m["end_sample_exclusive"] for m in extent]
        overlap_start, overlap_end = max(starts), min(ends)
        coverage = {"union_start": min(starts), "union_end_exclusive": max(ends),
                    "overlap_start": overlap_start, "overlap_end_exclusive": max(overlap_start, overlap_end),
                    "start_spread_samples": max(starts) - min(starts), "end_spread_samples": max(ends) - min(ends),
                    "sample_count_spread": max(counts) - min(counts)}
    categories = {r["category"] for r in reasons}
    status = next((s for s in ("AMBIGUOUS", "INCOMPLETE", "TECHNICALLY_INCONSISTENT") if s in categories), "VALID")
    coverage_reasons = []
    if not enabled:
        coverage_reasons.append("Defect detection was disabled")
    if reasons:
        coverage_reasons.append("Group validation prevents cross-file consolidation")
    for member, audio in audios:
        for check in audio.checks:
            if check.code in ("defects_capped", "defects_unavailable", "signal_loss_records", "signal_loss_coverage"):
                coverage_reasons.append(f"{member.channel}: {check.code}: {check.message}")
        if any(d.affects_analysis and d.code in ("readability", "inspection", "unexpected_inspection_error", "source_changed") for d in audio.operational_diagnostics):
            coverage_reasons.append(f"{member.channel}: incomplete source analysis")
    issues, capped = ([], False)
    if status == "VALID" and enabled:
        issues, capped = _group_issues(definition, audios, rate, tolerance, limit)
    if capped:
        coverage_reasons.append("Consolidated group issue limit exceeded")
    return {"id": definition.id, "name": definition.name, "layout": definition.layout,
            "channel_order": list(expected), "identity_source": definition.identity_source,
            "requested_alignment": definition.alignment, "alignment_mode": mode, "group_origin": origin,
            "sample_rate": rate, "members": members, "missing_channels": missing,
            "validation_status": status, "valid_for_consolidation": status == "VALID", "reasons": reasons,
            "warnings": warnings, "coverage": coverage, "issues": issues,
            "defect_coverage": "COMPLETE" if not coverage_reasons else "INCOMPLETE" if enabled else "NOT_MEASURED",
            "coverage_limitations": coverage_reasons, "issues_capped": capped,
            "issue_configuration": {"cross_channel_merge_ms": tolerance, "max_issues": limit},
            "combined_programme_loudness": "Not measured in M5.",
            "combined_true_peak": "Not measured in M5."}


def _group_issues(definition, audios, rate, tolerance, limit):
    # Up to six already bounded per-file issue lists; no raw detection stream.
    events = []
    for member, audio in audios:
        for file_issue_index, issue in enumerate(audio.defects, 1):
            for original in getattr(issue, "channel_events", None) or [issue]:
                event = _cluster(original, rate)
                events.append({"logical_channel": member.channel, "source_path": member.file,
                               "physical_channel": event.channel, "file_issue_index": file_issue_index,
                               "file_issue_severity": issue.severity,
                               "group_sample_index": event.sample_index,
                               "group_first_sample": event.cluster_first_sample,
                               "group_last_sample": event.cluster_last_sample,
                               "source_event": asdict(event), "snippet": issue.snippet or event.snippet})
    events.sort(key=lambda e: (e["group_first_sample"], ROLES.index(e["logical_channel"]),
                               e["source_event"]["event_type"], e["group_sample_index"]))
    gap = Fraction(str(tolerance)) * rate // 1000
    issues, joinable, capped = [], [], False
    for event in events:
        start, role, kind = event["group_first_sample"], event["logical_channel"], event["source_event"]["event_type"]
        joinable = [i for i in joinable if start <= i["cluster_first_sample"] + gap]
        issue = next((i for i in joinable if can_join_issue(i["cluster_first_sample"], start, gap,
                     i["event_type"], kind, i["channels"], role)), None)
        if issue is None:
            if len(issues) >= limit:
                capped = True
                continue
            issue = {"id": f"{definition.id}:issue:{len(issues)+1:04d}", "group_id": definition.id,
                     "event_type": kind, "sample_index": start, "cluster_first_sample": start,
                     "cluster_last_sample": event["group_last_sample"], "channels": [], "channel_events": []}
            issues.append(issue)
            joinable.append(issue)
        issue["channels"].append(role)
        issue["channels"].sort(key=ROLES.index)
        issue["channel_events"].append(event)
        issue["cluster_last_sample"] = max(issue["cluster_last_sample"], event["group_last_sample"])
        # Policy classifies the file issue; its forensic channel events can
        # remain unclassified. Carry that existing assessment without changing
        # source events or inventing a classification during measurement.
        issue["severity"] = highest_severity(s for e in issue["channel_events"]
                                             for s in (e["source_event"]["severity"], e["file_issue_severity"]))
        issue["merged_candidate_count"] = sum(e["source_event"]["merged_candidate_count"] for e in issue["channel_events"])
    return issues, capped
