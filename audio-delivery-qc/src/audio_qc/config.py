"""Strict configuration, with presets merged before user overrides."""
from copy import deepcopy
import math
import os
from pathlib import Path
import tempfile

import yaml
from .timecode import validate_settings

PRESETS = ("FILM_48K", "BROADCAST_EBU_R128", "CUSTOM")
BIT_DEPTHS = (8, 16, 20, 24, 32, 64)
BASE = {
    "preset": "FILM_48K",
    "sample_rate": {"required": 48000},
    "bit_depth": {"preferred": 24, "required": None},
    "pcm": {"preferred": True},
    "channels": {"allowed": None},
    "loudness": {"enabled": True, "target_lufs": None, "tolerance": None},
    "true_peak": {"maximum": None},
    "bwf": {"required": False, "warn_if_missing": True},
    "clipping": {"fail": True, "consecutive_samples": 3},
    "duration_tolerance_ms": 20,
    "large_duration_difference_ms": 1000,
    "expected_stems": [],
    "process_timeout_seconds": None,
    "timecode": {"frame_rate": "25", "source": "AUTO", "manual_start": None},
    "defects": {
        "enabled": False,
        "max_candidates": 1000,
        "issues": {"cross_channel_merge_ms": 1.0},
        "snippet_before_seconds": 1.0,
        "snippet_after_seconds": 1.0,
        "clicks": {"enabled": True, "sensitivity": "low",
                   "min_local_deviation_db": 12, "max_duration_ms": 5, "merge_gap_ms": 1.0},
        "dropouts": {"enabled": True, "zero_run_ms": 5,
                     "relative_level_drop_db": 30, "min_duration_ms": 2,
                     "max_duration_ms": 500, "fail_zero_run_ms": None},
    },
}


class ConfigError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


class MarkedMapping(dict):
    """YAML source locations, discarded when resolving into the canonical dict."""
    def __init__(self):
        super().__init__()
        self.locations = {}



class UniqueLoader(yaml.SafeLoader):
    """Reject repeated keys rather than silently discarding a rule."""


def _mapping(loader, node, deep=False):
    result = MarkedMapping()
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ConfigError(f"Duplicate or non-text YAML key at line {key_node.start_mark.line+1}, column {key_node.start_mark.column+1}: {key!r}")
        result.locations[key] = (value_node.start_mark.line+1, value_node.start_mark.column+1)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def merge(base: dict, supplied: dict, prefix="") -> None:
    if not isinstance(supplied, dict):
        raise ConfigError(f"{prefix or 'Configuration'} must be a mapping", prefix.rstrip("."))
    for key, value in supplied.items():
        name = f"{prefix}{key}"
        if key not in base:
            raise ConfigError(f"Unknown setting: {name}", name)
        if isinstance(base[key], dict):
            merge(base[key], value, name + ".")
        else:
            base[key] = value


def validate(c: dict) -> None:
    try:
        validate_settings(c["timecode"])
    except ValueError as exc:
        raise ConfigError(str(exc), "timecode") from exc

    def number(value, name, low, high, nullable=False, integer=False):
        if value is None and nullable:
            return
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not low <= value <= high or not math.isfinite(value)
                or (integer and not isinstance(value, int))):
            raise ConfigError(f"{name} must be {'an integer' if integer else 'a number'} in [{low}, {high}]"
                              + (" or null" if nullable else ""), name.removesuffix(" item"))

    for section, key in [("loudness", "enabled"), ("bwf", "required"),
                         ("bwf", "warn_if_missing"), ("pcm", "preferred"), ("clipping", "fail")]:
        if type(c[section][key]) is not bool:
            raise ConfigError(f"{section}.{key} must be true or false", f"{section}.{key}")
    number(c["sample_rate"]["required"], "sample_rate.required", 1000, 768000, True, True)
    for key in ("preferred", "required"):
        number(c["bit_depth"][key], f"bit_depth.{key}", 1, 64, True, True)
        if c["bit_depth"][key] is not None and c["bit_depth"][key] not in BIT_DEPTHS:
            raise ConfigError(f"bit_depth.{key} must be one of {BIT_DEPTHS} or null", f"bit_depth.{key}")
    bits = c["bit_depth"]
    if bits["required"] is not None and bits["preferred"] not in (None, bits["required"]):
        raise ConfigError("bit_depth.required and bit_depth.preferred conflict", "bit_depth.required")
    allowed = c["channels"]["allowed"]
    if allowed is not None:
        if not isinstance(allowed, list) or not allowed:
            raise ConfigError("channels.allowed must be a non-empty list of counts or null", "channels.allowed")
        for n in allowed:
            number(n, "channels.allowed item", 1, 256, integer=True)
    number(c["loudness"]["target_lufs"], "loudness.target_lufs", -70, 0, True)
    number(c["loudness"]["tolerance"], "loudness.tolerance", 0, 20, True)
    if c["loudness"]["target_lufs"] is not None:
        if c["loudness"]["tolerance"] is None or not c["loudness"]["enabled"]:
            raise ConfigError("A loudness target requires loudness.enabled and a numeric tolerance", "loudness.target_lufs")
    elif c["loudness"]["tolerance"] is not None:
        raise ConfigError("loudness.tolerance requires a loudness.target_lufs", "loudness.tolerance")
    number(c["true_peak"]["maximum"], "true_peak.maximum", -99, 20, True)
    number(c["clipping"]["consecutive_samples"], "clipping.consecutive_samples", 2, 10000, integer=True)
    number(c["duration_tolerance_ms"], "duration_tolerance_ms", 0, 60000)
    number(c["large_duration_difference_ms"], "large_duration_difference_ms", 0, 3600000)
    number(c["process_timeout_seconds"], "process_timeout_seconds", 1, 604800, True)
    if not isinstance(c["expected_stems"], list) or any(s not in ("DIA", "FX", "MX", "ME", "FULLMIX") for s in c["expected_stems"]):
        raise ConfigError("expected_stems must be a list using DIA, FX, MX, ME, FULLMIX", "expected_stems")
    d = c["defects"]
    for name, section in [("defects", d), ("defects.clicks", d["clicks"]), ("defects.dropouts", d["dropouts"])]:
        if type(section["enabled"]) is not bool:
            raise ConfigError(f"{name}.enabled must be true or false", f"{name}.enabled")
    number(d["max_candidates"], "defects.max_candidates", 1, 100000, integer=True)
    number(d["issues"]["cross_channel_merge_ms"], "defects.issues.cross_channel_merge_ms", 0, 10)
    for key in ("snippet_before_seconds", "snippet_after_seconds"):
        number(d[key], f"defects.{key}", 0, 30)
    if d["clicks"]["sensitivity"] not in ("low", "medium", "high"):
        raise ConfigError("defects.clicks.sensitivity must be low, medium or high", "defects.clicks.sensitivity")
    number(d["clicks"]["min_local_deviation_db"], "defects.clicks.min_local_deviation_db", 3, 80)
    number(d["clicks"]["max_duration_ms"], "defects.clicks.max_duration_ms", 0.05, 20)
    number(d["clicks"]["merge_gap_ms"], "defects.clicks.merge_gap_ms", 0, 10)
    for key in ("zero_run_ms", "min_duration_ms", "max_duration_ms"):
        number(d["dropouts"][key], f"defects.dropouts.{key}", 0.1, 5000)
    if d["dropouts"]["min_duration_ms"] > d["dropouts"]["max_duration_ms"]:
        raise ConfigError("Dropout minimum duration exceeds maximum duration", "defects.dropouts.min_duration_ms")
    number(d["dropouts"]["relative_level_drop_db"], "defects.dropouts.relative_level_drop_db", 6, 100)
    number(d["dropouts"]["fail_zero_run_ms"], "defects.dropouts.fail_zero_run_ms", 0.1, 86400000, True)


def _timecode_aliases(settings):
    """Accept M1's 'mode' spelling while preserving the existing canonical 'source'."""
    if not isinstance(settings, dict) or "mode" not in settings:
        return settings
    result = dict(settings)
    mode = result.pop("mode")
    if "source" in result and result["source"] != mode:
        raise ConfigError("timecode.mode and timecode.source conflict; use one spelling")
    result["source"] = mode
    return result


def load_config(path: Path | None = None, preset: str | None = None, timecode_overrides: dict | None = None) -> dict:
    supplied = {}
    try:
        if path is not None:
            if path.stat().st_size > 65536:
                raise ConfigError("Configuration exceeds 64 KiB")
            supplied = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
            if not isinstance(supplied, dict):
                raise ConfigError("Configuration must be a YAML mapping")
        return resolve_config(supplied, preset, timecode_overrides)
    except ConfigError as exc:
        if path is None:
            raise
        location, current = None, supplied
        for key in (exc.field or "").split("."):
            if not isinstance(current, MarkedMapping) or key not in current:
                break
            location = current.locations[key]
            current = current[key]
        where = f"{path}"
        if location:
            where += f":line {location[0]}, column {location[1]}"
        raise ConfigError(f"{where}: {exc}", exc.field) from exc
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise ConfigError(f"Cannot read configuration {path}: {exc}") from exc


def resolve_config(supplied=None, preset=None, timecode_overrides=None):
    """Canonical resolution for YAML, GUI edits and complete scan snapshots."""
    supplied = deepcopy({} if supplied is None else supplied)
    if not isinstance(supplied, dict):
        raise ConfigError("Configuration must be a mapping")
    if "timecode" in supplied:
        supplied["timecode"] = _timecode_aliases(supplied["timecode"])
    selected = preset or supplied.get("preset", "FILM_48K")
    if selected not in PRESETS:
        raise ConfigError(f"Unknown preset: {selected!r}; choose {', '.join(PRESETS)}", "preset")
    result = deepcopy(BASE)
    if selected == "BROADCAST_EBU_R128":
        result["loudness"].update(target_lufs=-23.0, tolerance=0.5)
        result["true_peak"]["maximum"] = -1.0
    elif selected == "CUSTOM":
        result["sample_rate"]["required"] = None
        result["bit_depth"]["preferred"] = None
        result["pcm"]["preferred"] = False
        result["bwf"]["warn_if_missing"] = False
    try:
        merge(result, supplied)
    except RecursionError as exc:
        raise ConfigError("Recursive YAML is unsupported") from exc
    result["preset"] = selected
    # Explicitly removing an inherited target also removes its inherited
    # tolerance. An explicitly supplied orphan tolerance remains an error.
    loudness = supplied.get("loudness", {})
    if "target_lufs" in loudness and loudness["target_lufs"] is None and "tolerance" not in loudness:
        result["loudness"]["tolerance"] = None
    if timecode_overrides:
        merge(result["timecode"], _timecode_aliases(timecode_overrides), "timecode.")
    validate(result)
    return result


def save_config(path, config):
    """Validate and atomically save canonical YAML; never alter bundled presets."""
    path = Path(path).expanduser().absolute()
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ConfigError("La especificación debe guardarse como .yaml o .yml")
    bundled = Path(__file__).resolve().parents[2] / "config"
    if path.resolve().is_relative_to(bundled):
        raise ConfigError("No se pueden sobrescribir los presets incluidos; elija otra carpeta")
    resolved = resolve_config(config)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".audio-qc-", suffix=".yaml", delete=False) as handle:
            temporary = Path(handle.name)
            yaml.safe_dump(resolved, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise ConfigError(f"No se pudo guardar la especificación: {exc}") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
