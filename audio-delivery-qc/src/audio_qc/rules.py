"""Pure QC policy evaluation plus a compatibility adapter for existing callers.

Only this layer interprets file specification limits. Measurement execution is
planned here; presets have already resolved into the same validated shape.
"""
from copy import deepcopy
from dataclasses import replace

from .measurement import MeasurementContext, MeasurementRequirements
from .models import AudioFile, Check, Status, Defect, MeasurementState as MS


def measurement_requirements(policy: dict, with_hash=False) -> MeasurementRequirements:
    """Project resolved policy into execution-only inputs for the engine."""
    options = None
    if policy["defects"]["enabled"]:
        d = policy["defects"]
        options = {"max_candidates": d["max_candidates"], "issues": deepcopy(d["issues"]), "clicks": deepcopy(d["clicks"]),
                   "dropouts": {k: deepcopy(v) for k, v in d["dropouts"].items() if k != "fail_zero_run_ms"}}
    return MeasurementRequirements(loudness=policy["loudness"]["enabled"],
                                   true_peak=policy["loudness"]["enabled"] or policy["true_peak"]["maximum"] is not None,
                                   defect_options=options, hash=with_hash,
                                   timeout_seconds=policy["process_timeout_seconds"])


def evaluate_level_policy(m: dict, c: dict, outcomes=None) -> list[Check]:
    """Shared level rules over measured facts, independent of physical files."""
    checks = []
    outcomes = outcomes or {}
    def failed(metric):
        return metric in outcomes and outcomes[metric].state == MS.ERROR
    def add(code, status, message):
        checks.append(Check(code, status, message))
    if c["loudness"]["enabled"]:
        value = m.get("integrated_lufs")
        target = c["loudness"]["target_lufs"]
        if failed("integrated_lufs"):
            add("integrated_loudness", Status.INCOMPLETE, outcomes["integrated_lufs"].reason)
        elif value is None:
            add("integrated_loudness", Status.WARNING,
                  m.get("loudness_unavailable", "Integrated loudness unavailable (short, silent, below gate, or not measured)"))
        elif target is not None:
            ok = abs(value-target) <= c["loudness"]["tolerance"] + 1e-9
            add("integrated_loudness", Status.PASS if ok else Status.FAIL,
                  f"{value:.3f} LUFS; target {target:g} ±{c['loudness']['tolerance']:g} LU")
        else:
            add("integrated_loudness", Status.INFO, f"{value:.3f} LUFS; no loudness target configured")
        add("lra", Status.INFO, "LRA is report-only; unavailable below 3 s / below gate and unstable for short programmes")
    else:
        add("integrated_loudness", Status.INFO, "Loudness checks disabled by configuration")
    if c["loudness"]["enabled"] or c["true_peak"]["maximum"] is not None:
        value, limit = m.get("true_peak_dbtp"), c["true_peak"]["maximum"]
        if failed("true_peak_dbtp"):
            add("true_peak", Status.INCOMPLETE, outcomes["true_peak_dbtp"].reason)
        elif value is None:
            add("true_peak", Status.WARNING, "True Peak unavailable; no numeric value or failure inferred")
        else:
            add("true_peak", Status.INFO if limit is None else Status.FAIL if value > limit + 1e-9 else Status.PASS,
                  f"{value:.1f} dBTP (0.1 dB reporting resolution)" + (f"; maximum {limit:g} dBTP" if limit is not None else ""))
    return checks


def _evaluate_file(a: AudioFile, c: dict, context: MeasurementContext, level_scope="FILE"):
    if level_scope not in ("FILE", "PROGRAMME_MEMBER"):
        raise ValueError("Unknown level scope: " + level_scope)
    checks = []
    # Policy-created zero-run evidence is regenerated from technical run facts,
    # never counted as an extra raw detector candidate on re-evaluation.
    defects = [replace(e, severity=Status.WARNING if e.severity is None else e.severity)
               for e in a.defects if e.detection_method != "exact_zero_samples+explicit_failure_rule"]
    def add(code, status, message):
        checks.append(Check(code, status, message))
    if a.sample_rate:
        required = c["sample_rate"]["required"]
        add("sample_rate", Status.FAIL if required and a.sample_rate != required else Status.PASS,
              f"Sample rate {a.sample_rate} Hz" + (f"; required {required} Hz" if required else ""))
    for rule, severity in (("required", Status.FAIL), ("preferred", Status.WARNING)):
        value = c["bit_depth"][rule]
        if value is not None:
            if a.bit_depth is None:
                reason = a.metadata.get('bit_depth_provenance', {}).get('reason')
                add(f"bit_depth_{rule}", Status.INCOMPLETE if rule == "required" else Status.INFO,
                    f"Bit depth unavailable; {rule} {value}" + (f"; {reason}" if reason else ""))
            else:
                add(f"bit_depth_{rule}", severity if a.bit_depth != value else Status.PASS,
                    f"Bit depth {a.bit_depth}; {rule} {value}")
    if c["pcm"]["preferred"] and a.codec:
        add("pcm", Status.PASS if a.codec.startswith("pcm_") else Status.WARNING, f"Codec: {a.codec}; PCM preferred")
    if a.channels and c["channels"]["allowed"]:
        add("channel_count", Status.PASS if a.channels in c["channels"]["allowed"] else Status.WARNING,
              f"{a.channels} channels; configured expected counts {c['channels']['allowed']}")
    if not a.channel_layout and a.channels:
        add("channel_layout", Status.INFO if a.channels <= 2 else Status.WARNING,
              "Channel assignment is absent in metadata" + ("; conventional mono/stereo used for loudness" if a.channels <= 2 else "; loudness weighting not assumed"))
    if a.stream_count > 1:
        add("multiple_streams", Status.WARNING, f"{a.stream_count} audio streams; only the first is analyzed")
    present = a.bwf.get("present")
    if present:
        add("bwf", Status.PASS, "BEXT chunk present; this does not certify all BWF metadata fields")
    elif present is False:
        severity = Status.FAIL if c["bwf"]["required"] else Status.WARNING if c["bwf"]["warn_if_missing"] else Status.INFO
        add("bwf", severity, "No BEXT chunk present")
    else:
        add("bwf", Status.WARNING if c["bwf"]["required"] else Status.INFO, "BEXT inspection unavailable for this container")
    m = a.measurements
    if "decoded_sample_frames" in m:
        clipped = m["overload_samples"] > 0 or max(m["longest_rail_run_per_channel"], default=0) >= c["clipping"]["consecutive_samples"]
        if clipped:
            add("clipping", Status.FAIL if c["clipping"]["fail"] else Status.WARNING,
                  f"Digital overload / full-scale plateau detected (criterion: {c['clipping']['consecutive_samples']} consecutive same-polarity rail samples); longest runs {m['longest_rail_run_per_channel']}, >0 dBFS samples {m['overload_samples']}")
        elif sum(m["rail_samples_per_channel"]):
            add("clipping", Status.WARNING, "Isolated full-scale samples; insufficient evidence of a clipped plateau")
        else:
            add("clipping", Status.PASS, "No digital overload or full-scale plateau detected")
        if m["nonfinite_samples"]:
            add("nonfinite_samples", Status.FAIL, f"{m['nonfinite_samples']} non-finite floating-point samples")
        if m["digital_silence"]:
            add("silence", Status.INFO, "All decoded samples are digital zero; logarithmic levels unavailable")
    if level_scope == "FILE":
        checks.extend(evaluate_level_policy(m, c, a.measurement_outcomes))
    else:
        add("level_scope", Status.INFO, "Mono levels are diagnostic; programme levels assessed separately")
    if defects:
        add("defect_candidates", Status.WARNING, f"{len(defects)} possible defects require human review")
    elif c["defects"]["enabled"] and "decoded_sample_frames" in m:
        add("defect_candidates", Status.INFO, "No candidates retained by the configured detector; this is not an audible-quality guarantee")
    threshold = c["defects"]["dropouts"]["fail_zero_run_ms"]
    if c["defects"]["enabled"] and c["defects"]["dropouts"]["enabled"] and threshold is not None:
        for ch, run in enumerate(context.zero_runs, 1):
            if run.longest * 1000 / a.sample_rate >= threshold:
                add("explicit_zero_run_rule", Status.FAIL,
                      f"Channel {ch}: confirmed {run.longest} zero samples exceed configured {threshold:g} ms failure rule")
                defects.append(Defect(run.start/a.sample_rate, run.start, ch, "DIGITAL ZERO RUN (EXPLICIT RULE)",
                                       run.longest/a.sample_rate, Status.FAIL,
                                       {"zero_samples": run.longest, "configured_failure_ms": threshold},
                                       "exact_zero_samples+explicit_failure_rule"))

    return checks, defects


def evaluate_file_policy(audio: AudioFile, policy: dict,
                         context: MeasurementContext | None = None, *, level_scope="FILE") -> list[Check]:
    """Return deterministic policy checks without I/O or mutation of input facts."""
    checks, _ = _evaluate_file(audio, policy, context if context is not None else MeasurementContext(), level_scope)
    return checks


def assess_file(audio: AudioFile, policy: dict,
                context: MeasurementContext | None = None, *, level_scope="FILE") -> AudioFile:
    """Create a report copy with policy checks and classified evidence.

    Pass the measured AudioFile (its checks contain operational diagnostics),
    retaining that original for reuse against another policy.
    """
    result = deepcopy(audio)
    checks, defects = _evaluate_file(result, policy, context if context is not None else MeasurementContext(), level_scope)
    result.checks.extend(checks)
    result.defects = defects
    return result


def apply_rules(audio: AudioFile, policy: dict, zero_runs=()) -> None:
    """Legacy mutating adapter; new callers should use evaluate_file_policy/assess_file."""
    checks, defects = _evaluate_file(audio, policy, MeasurementContext(zero_runs=tuple(zero_runs)))
    audio.checks.extend(checks)
    audio.defects = defects


def assess_programme(measurement, policy) -> list[Check]:
    """Programme thresholds use the same canonical comparisons as physical files."""
    if measurement.state == 'DISABLED':
        return [Check('programme_levels', Status.INFO, 'Programme level measurement disabled by configuration')]
    if measurement.state == 'NOT_EVALUATED':
        return [Check('programme_levels', Status.INCOMPLETE, 'Requested programme levels could not be certified')]
    checks = evaluate_level_policy(measurement.measurements, policy, measurement.measurement_outcomes)
    if measurement.state == 'ERROR':
        checks.insert(0, Check('programme_levels', Status.INCOMPLETE, 'Requested programme levels could not be certified'))
    return checks
