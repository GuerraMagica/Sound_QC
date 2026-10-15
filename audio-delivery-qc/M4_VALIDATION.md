# M4 — Configurable CUSTOM QC specification

Validated on this Mac on 2026-10-08 (Europe/Madrid; report timestamps are UTC). M4 is complete; M5 was not started.

## Architecture and behavior

The existing flow remains measurement engine → measured facts → QC policy → checks/status → reports. No policy comparisons were added to GUI callbacks or measurement code. No detector thresholds, consolidation tolerances, clipping criteria, timecode calculations, audio processing or preset values changed.

`config.resolve_config()` is the shared canonical resolver. YAML loading uses the existing strict safe loader and passes through this resolver. The GUI projects controls into the same full configuration and resolves it before save or Run. The CLI still uses `load_config()`. The measurement-requirements mechanism and existing policy evaluator are unchanged.

Run creates a private temporary directory containing a full validated YAML snapshot, makes the file read-only, and passes it to the existing QProcess CLI worker. The worker, policy and report use that resolved configuration. The original loaded YAML is not reread during the scan. Controls and repeated Run are guarded during startup and processing; the snapshot is removed on completion/error/close. A real-worker regression changes both GUI fields and the original YAML after Run and confirms the report retains the captured settings.

The editor is a compact Spanish form in the existing PySide6 window:

| Control | Canonical meaning |
|---|---|
| Sample Rate | Unrestricted or required integer Hz |
| Bit Depth requerido / preferido | Nullable required/preferred depths; conflicting non-null values rejected |
| Loudness integrado | Disabled, report-only, or target LUFS with tolerance LU |
| True Peak | Report-only or upper maximum dBTP |
| BWF / BEXT | Ignored, warning if missing, or required |
| Canales físicos | Blank for unrestricted, otherwise comma-separated allowed counts |
| Clipping | FAIL or WARNING under the existing criterion |

Numeric entries accept Spanish decimal commas or decimal periods without thousands separators. Invalid entries remain visible and block scanning. Built-in presets are read-only with an explicit **Copiar a CUSTOM** action. Initial CUSTOM settings come from canonical CUSTOM defaults. Timecode and detector controls remain separate.

YAML is validated completely before changing editor state. Saving uses a temporary file in the destination directory followed by atomic replacement. Save rejects bundled preset destinations and non-YAML suffixes. Tests cover Unicode/spaces, missing directories, permission failures, cancellation, failed-save preservation and full-policy round trips. Existing technical settings, including clipping criterion, detector settings, timecode, timeout and expected stems, are preserved. Hashing/snippet export are existing execution options rather than new YAML policy fields.

HTML shows the resolved specification near the header. JSON remains schema version 3 with the existing full `configuration`. Defect tables, exact samples/timestamps, per-channel forensics, TC, relative evidence links and the existing self-contained HTML CSP remain intact.

## Compatibility

All three resolved preset defaults match the pre-M4 snapshot exactly. All shipped YAML files, existing tests and the M3 golden fixture remain byte-identical. Existing CLI options are unchanged.

Validation is intentionally stricter for unsupported bit depths, different required/preferred bit depths, and explicit orphan loudness tolerances. Previously accepted YAML with those contradictory/unsupported values is now rejected with a clear error. Supported depths are 8, 16, 20, 24, 32 and 64; pre-existing sample-rate and numeric domain bounds are retained. No delivery-standard-specific loudness restriction was added.

Explicit null removes requirements. `target_lufs: null` also clears an inherited tolerance unless the YAML explicitly supplies one; an explicit orphan tolerance is rejected. Missing measured values remain unavailable. True Peak scheduling retains its existing dependency on enabled loudness or a configured maximum, disclosed in the editor/report summary.

## Files changed for M4

- `src/audio_qc/config.py`: canonical in-memory resolution, strengthened validation, atomic YAML save.
- `src/audio_qc/gui_window.py`: editor integration, read-only preset summary, Copy/Load/Save, snapshot and lifecycle guard.
- `src/audio_qc/spec_editor.py` (new): Spanish controls and projection to canonical configuration.
- `src/audio_qc/reports/specification.py` (new): presentation-only specification summary.
- `src/audio_qc/reports/html_report.py`: effective specification table.
- `tests/test_custom_config.py`, `tests/test_custom_policy.py`, `tests/test_custom_gui.py`, `tests/test_custom_reports.py` (new): 64 deterministic test cases.
- `scripts/validate_custom_smoke.py` (new): repeatable offscreen GUI-save/QProcess/CLI equivalence and evidence/source checks.
- `README.md` and this validation record.

Hash comparison against `/private/tmp/audio-qc-m4-before.json` confirmed all other existing implementation files unchanged, including `rules.py`, `measurement.py`, `scanner.py`, `defects.py`, `consolidation.py`, `issues.py`, `samples.py`, `timecode.py`, `snippets.py`, CLI and launchers. No dependency/environment rebuild was needed.

## Automated validation, in requested order

All commands used `.venv/bin/python -m pytest -q` in this repository. Counts below overlap between focused groups; the full suite is the unique total.

| Step | Test files | Exact result |
|---|---|---|
| 1. Configuration / policy / GUI | `test_custom_config.py test_custom_policy.py test_custom_gui.py test_config.py test_policy.py test_policy_separation.py test_gui.py` | **142 passed in 1.71s** |
| 2. Reports | `test_custom_reports.py test_reports_cli.py test_defect_csv.py test_consolidation_reports.py test_policy_baseline.py` | **25 passed in 5.28s** |
| 3. Defects / consolidation / evidence | `test_defects.py test_consolidation.py test_issues.py test_issue_severity.py test_issue_evidence.py test_consolidation_reports.py` | **158 passed in 6.95s** |
| 4. Timecode / recursive discovery | `test_timecode.py test_scanner_rules.py` | **126 passed in 2.89s** |
| 5. Complete suite | All tests | **467 passed in 17.25s** |

No failures, errors or skipped tests in the full suite. Golden baselines were not regenerated. No production code changed after these runs.

The focused policy checks include −14 LUFS ±1 inclusive boundaries and existing epsilon behavior, True Peak below/equal/above −6, unavailable measurements, and evaluation of the same `AudioFile` under EBU and CUSTOM policies without numeric mutation. I/O, measurement and grouping entry points are forbidden during the reuse test. Existing focused policy tests cover required/preferred depth, all BWF modes, channel counts, report-only behavior and clipping FAIL/WARNING.

## Actual launcher and runtime

The unchanged `Open QC GUI.command` was launched and the native window was exercised. It selects this repository's `.venv/bin/python` and starts `-m audio_qc gui`; QProcess uses that same `sys.executable`.

```text
Python 3.14.8
/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/.venv/bin/python

audio_qc:
/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/__init__.py
config:
/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/config.py
GUI:
/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/gui_window.py
issues:
/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/issues.py
```

FFmpeg/ffprobe: 9.0.2. A new native GUI process loaded the M4 implementation; an older window would need reopening to load changed Python modules. No launcher or editable-installation change was required. Runtime paths are recorded in the smoke verification JSON files.

## GUI / CLI smoke checks

A new three-second stereo, 48 kHz, 24-bit BWF fixture with TimeReference 172800000 was generated under `reports/m4-verified-smoke/`. The supplied real reference source was not used for M4; synthetic input is the requested smoke fixture.

Configured specification: 48000 Hz required; 24 bits required; −14 LUFS ±1; maximum −6 dBTP; BWF required; allowed physical channel counts `[2, 6]`; clipping FAIL. Detection, SHA-256 and evidence export were enabled.

First, the repeatable script saved `Especificación CUSTOM.yaml` through the GUI handler, loaded it into a fresh window, ran a real QProcess worker, then used that exact YAML with the CLI. **Passed.** Reproduce with a new output directory:

```sh
.venv/bin/python scripts/validate_custom_smoke.py reports/new-m4-smoke
```

Second, actual native GUI interactions through the real launcher verified:

1. FILM read-only summary and disabled Save.
2. Copy to CUSTOM exposed editable controls.
3. Native Load dialog loaded the saved full CUSTOM specification.
4. A tolerance of `-1` blocked Run with a visible validation message and preserved the invalid entry.
5. Correcting tolerance to `1,0` and using the native Save dialog wrote `interactive-custom.yaml`.
6. Evidence/hash checkboxes and Run started the real scan and disabled settings/Run.

The native scan created a fresh report. A new CLI scan used **that exact interactively saved YAML** and matched the GUI's complete JSON after removing only `scan_date` and `elapsed_seconds`. Configuration, measurements, checks, overall status, issue fields, TC, source paths and evidence references all match. The evidence WAVs are byte-identical.

Both report sets have `schema_version: 3`, `channels`, `channel_events` and `configuration.defects.issues.cross_channel_merge_ms: 1.0`. Four primitive candidates become two channel events and one stereo issue. Evidence preserves both channels in their original order; decoded snippet samples equal the corresponding quantized source interval with no gain change. Fixture status is deliberately **FAIL** because it violates the configured loudness/peak limits; worker exit code 1 is the expected QC result, not an execution error. The validation script exits 0.

Artifacts relative to this repository:

- [Interactively saved CUSTOM YAML](reports/m4-verified-smoke/interactive-custom.yaml)
- [Fresh CLI HTML](reports/m4-verified-smoke/interactive-cli/QC_REPORT.html)
- [Fresh CLI JSON](reports/m4-verified-smoke/interactive-cli/QC_REPORT.json)
- [Interactive verification and exact native report path](reports/m4-verified-smoke/interactive-verification.json)
- [Automated GUI/CLI verification](reports/m4-verified-smoke/verification.json)

Two initial script attempts exposed NFC/NFD spelling differences in accented paths passed through Qt on macOS. The harness now supplies the same decomposed source spelling to both entry points on macOS; application path behavior was not changed. Final comparison still excludes only date/elapsed metadata, not paths or results. Those attempts remain in `reports/m4-smoke/` and `reports/m4-smoke-final/`; the passing artifacts are in `reports/m4-verified-smoke/`.

## Source remains read-only

Before/after GUI and CLI scans plus evidence export:

```text
SHA-256: 3ff10b8e531d3a94a993fa6d44bb188138193e2f02d2b7845195464c0a011039
Size: 864706 bytes
mtime_ns: 1791415308140429113
```

All three match exactly. No source was deleted, renamed, moved, normalized, rewritten, gain-adjusted or given new metadata. Only newly designated specifications, reports and evidence files were written.

## Limits of this verification

Native GUI interaction was performed, separately from automated/offscreen tests. After Run began, the accessibility service timed out on completion-state reads; completion and equivalence were verified from the fresh report artifacts rather than a final screen observation. Native close and the final Open Report button state were not interactively verified. Browser rendering and interactive HTML playback were not exercised; report content, CSP, relative links and evidence audio are tested. Other operating systems were not interactively tested.

These are physical-file policies; no ProgrammeGroup, cross-file grouping, virtual multichannel loudness, new platform preset, detector tuning or M5 work is included.
