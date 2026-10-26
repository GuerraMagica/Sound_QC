from dataclasses import replace
import os
from pathlib import Path

from .bwf import inspect_bwf
from .hashing import sha256_file
from .loudness import measure_loudness
from .metadata import inspect_metadata
from .measurement import MeasurementContext, MeasurementRequirements
from .models import AudioFile, Check, Status, MeasurementOutcome, MeasurementState as MS
from .process import ToolError, ScanCancelled
from .rules import assess_file, measurement_requirements
from .samples import analyze_samples

EXTENSIONS = {".wav", ".wave", ".bwf", ".rf64", ".bw64", ".w64", ".aif", ".aiff", ".aifc", ".flac"}


class FileScanCancelled(ScanCancelled):
    """Cancellation carrying completed facts, not a successful inspection."""

    def __init__(self, audio, context):
        super().__init__('Scan cancelled during SHA-256')
        self.audio = audio
        self.context = context


def discover(source: Path):
    """Do not follow directory symlinks; report skipped links and unreadable paths."""
    files, notices = [], []
    if source.is_file():
        return [source], notices

    def onerror(error):
        notices.append(Check("directory_read", Status.WARNING, str(error)))

    for root, dirs, names in os.walk(source, followlinks=False, onerror=onerror):
        dirs.sort(key=str.casefold)
        for directory in dirs[:]:
            p = Path(root)/directory
            if p.is_symlink():
                dirs.remove(directory)
                notices.append(Check("symlink_skipped", Status.INFO, f"Skipped directory symlink: {p}"))
        for name in sorted(names, key=str.casefold):
            p = Path(root)/name
            if p.suffix.lower() in EXTENSIONS:
                if p.is_symlink():
                    notices.append(Check("symlink_skipped", Status.WARNING, f"Skipped source symlink: {p}"))
                elif p.is_file():
                    files.append(p)
    return files, notices


def inspect_file(path: Path, config: dict, with_hash=False, progress=None, *, level_scope="FILE", cancel=None) -> AudioFile:
    requirements = measurement_requirements(config, with_hash)
    if level_scope == "PROGRAMME_MEMBER":
        requirements = replace(requirements, levels_required=False)
    interrupted = None
    try:
        audio, context = measure_file(path, requirements, progress, **({"cancel": cancel} if cancel else {}))
    except FileScanCancelled as exc:
        interrupted = exc
        audio, context = exc.audio, exc.context
    result = assess_file(audio, config, context, level_scope=level_scope)
    _check_source_state(path, context)  # Keep the original final check after policy evaluation.
    if context.source_change_error is not None:
        result.operational("source_changed", context.source_change_error, required=True, affects_analysis=True)
    if interrupted is not None:
        interrupted.audio = result
        raise interrupted
    return result


def _check_source_state(path, context):
    if context.source_signature is not None:
        try:
            after = path.stat()
            if context.source_signature != (after.st_size, after.st_mtime_ns, after.st_ino):
                context.source_change_error = "Source changed externally during analysis; rescan a stable copy"
        except OSError as exc:
            context.source_change_error = str(exc)


def measure_file(path: Path, requirements: MeasurementRequirements, progress=None, *, cancel=None):
    """Collect reusable facts and operational diagnostics; no QC specification."""
    path = path.absolute()
    audio = AudioFile(str(path), path.name)
    before = None
    context = MeasurementContext()

    def phase(name):
        return (lambda fraction: progress(name, fraction)) if progress else None

    def sample_diagnostics():
        if context.defects_unavailable is not None:
            audio.add("defects_unavailable", Status.WARNING, context.defects_unavailable)
        if context.defects_capped:
            audio.add("defects_capped", Status.WARNING,
                      f"Consolidated defect candidate limit ({requirements.defect_options['max_candidates']}) exceeded; additional issues were not retained and further candidate analysis stopped")

    try:
        before = path.stat()
        context.source_signature = (before.st_size, before.st_mtime_ns, before.st_ino)
        audio.size_bytes = before.st_size
        if progress:
            progress("Metadata", 0)
        try:
            audio.bwf = inspect_bwf(path)
            for error in audio.bwf.get("errors", []):
                audio.add("container_integrity", Status.FAIL, error)
            for warning in audio.bwf.get("warnings", []):
                audio.add("bwf_metadata", Status.WARNING, warning)
        except OSError as exc:
            audio.operational("bwf_unavailable", str(exc), required=True, affects_analysis=True)
        inspect_metadata(path, audio, **({"cancel": cancel} if cancel else {}))
        try:
            try:
                analyze_samples(path, audio, requirements, context, phase("Audio samples"), **({"cancel": cancel} if cancel else {}))
            finally:
                sample_diagnostics()
                if requirements.signal_loss_options is not None:
                    complete = audio.measurements.get('signal_loss', {}).get('complete', False)
                    audio.measurement_outcomes['signal_loss'] = MeasurementOutcome(
                        MS.SUCCESS if complete else MS.ERROR,
                        None if complete else 'Digital signal-loss scan did not finish')
            audio.measurement_outcomes["samples"] = MeasurementOutcome(MS.SUCCESS)
            audio.add("readability", Status.PASS, "Complete audio stream decoded successfully")
            expected = audio.bwf.get("declared_sample_frames")
            decoded = audio.measurements["decoded_sample_frames"]
            if expected is not None and audio.codec and audio.codec.startswith("pcm_") and expected != decoded:
                audio.add("sample_count", Status.FAIL, f"Header declares {expected} sample frames, decoded {decoded}")
            if audio.duration_seconds is not None and abs(audio.duration_seconds-audio.decoded_duration_seconds) > max(2/audio.sample_rate, 0.001):
                audio.add("duration_metadata", Status.WARNING, "Container duration differs from fully decoded duration")
        except (ToolError, OSError) as exc:
            audio.measurement_outcomes["samples"] = MeasurementOutcome(MS.ERROR, str(exc))
            audio.operational("readability", f"Audio decode failed: {exc}", required=True, affects_analysis=True)
        if requirements.ebur128:
            try:
                measured = measure_loudness(path, audio, requirements.timeout_seconds, phase("EBU R128"), **({"cancel": cancel} if cancel else {}))
                audio.measurement_outcomes.update(measured.pop("measurement_outcomes", {}))
                audio.measurements.update(measured)
            except Exception as exc:
                audio.measurements["loudness_unavailable"] = f"FFmpeg EBU R128 analysis unavailable: {exc}"
                for metric in ("integrated_lufs", "true_peak_dbtp"):
                    audio.measurement_outcomes[metric] = MeasurementOutcome(MS.ERROR, str(exc))
            for metric, requested in (("integrated_lufs", requirements.loudness), ("true_peak_dbtp", requirements.true_peak)):
                if requested:
                    outcome = audio.measurement_outcomes.get(metric)
                    if outcome is None:
                        outcome = MeasurementOutcome(MS.ERROR, "Requested measurement outcome missing")
                        audio.measurement_outcomes[metric] = outcome
                    if outcome.state == MS.ERROR:
                        audio.operational(metric, outcome.reason, required=requirements.levels_required, affects_analysis=requirements.levels_required)
            for metric in ("lra_lu", "max_momentary_lufs", "max_short_term_lufs"):
                outcome = audio.measurement_outcomes.get(metric)
                if outcome is not None and outcome.state == MS.ERROR:
                    audio.operational(metric, outcome.reason)
    except Exception as exc:
        audio.operational("inspection", str(exc), required=True, affects_analysis=True)
    finally:
        # Metadata parsing replaces the metadata dict. Keep the pre-analysis
        # checkpoint, including on cancellation, rather than sampling it anew.
        audio.metadata["source_signature"] = context.source_signature
    if requirements.hash:
        try:
            audio.sha256 = sha256_file(path, phase("SHA-256"), **({"cancel": cancel} if cancel else {}))
        except KeyboardInterrupt as exc:
            audio.operational("hash_cancelled", "SHA-256 not completed: scan cancelled", required=True)
            _check_source_state(path, context)
            raise FileScanCancelled(audio, context) from exc
        except OSError as exc:
            audio.operational("hash_unavailable", str(exc), required=True)
    _check_source_state(path, context)
    return audio, context
