# M3 — Measurement engine / QC policy separation

Completed 2026-10-08 (Europe/Madrid), using the existing environment and FFmpeg/ffprobe 9.0.2. No dependency was added. Work stops at M3.

## Previous coupling

The existing separation was retained: metadata, BWF, hashing and FFmpeg loudness already collected facts, and `rules.py` already owned most file QC decisions. Remaining coupling was:

- `scanner.py` inspected loudness enablement and the true-peak maximum directly to schedule the level pass.
- `samples.py` received the full resolved configuration, including unrelated delivery policy and the explicit zero-run failure threshold, and emitted warning checks for detector availability/capping.
- `detect_window()` assigned WARNING severity when creating raw evidence candidates.
- `apply_rules()` only exposed a mutating interface and appended explicit zero-run failure evidence to its input object.

## Architecture after M3

1. **Resolution:** unchanged `config.load_config()` validates presets and overrides into one canonical configuration before scanning. Preset names select data only.
2. **Requirements:** `rules.measurement_requirements(policy, with_hash)` creates `MeasurementRequirements`. It carries level-pass flags, process timeout, hashing and only the technical detector options. Delivery targets, allowed formats, clipping failure policy, timecode settings and the zero-run failure threshold never reach sample analysis.
3. **Measurement:** `scanner.measure_file(path, requirements)` returns measured `AudioFile` facts and `MeasurementContext`. The context retains zero-run positions/lengths and technical availability, capping and source-integrity state. Measurement modules emit no QC checks and import no policy/configuration logic. Scanner operational diagnostics remain separate from specification checks.
4. **Policy:** `rules.evaluate_file_policy(audio, policy, context) -> list[Check]` is pure: no filesystem access, subprocess calls, input mutation or hidden measurement. The same measured object can be evaluated repeatedly against different targets and limits.
5. **Report projection:** `rules.assess_file()` returns an independent copy with policy checks, classified candidates and any explicit zero-run failure evidence. The measured original remains reusable. `inspect_file()` preserves the complete scan/report workflow and performs the final source-integrity check after assessment. `apply_rules()` remains as a legacy mutating adapter.
6. **Future reuse:** `evaluate_level_policy(measurements, policy)` implements the existing loudness/true-peak rules independently of a physical file. No programme-group model, multiple-mono grouping or virtual multichannel measurement was added. Existing delivery consistency policy remains in `consistency.py`.

True peak remains an upper limit. Integrated loudness retains its inclusive target/tolerance comparison and existing 1e-9 numeric tolerance. Unavailable numeric facts remain unavailable; policy does not fabricate values or automatically run missing measurements.

## Behavior and compatibility

There is **no intended user-visible behavior change**. CLI/GUI controls, resolved preset values, report formats, check messages/order, numerical measurements, statuses, JSON schema version 2, M1 timecode and M2.1 consolidation are retained.

Internal API changes are deliberate:

- Raw detector `Defect.severity` is now `None` until policy classification. Normal inspected/reported candidates still have WARNING severity; explicit zero-run failures still have FAIL severity.
- `analyze_samples()` receives execution requirements/context instead of full configuration and a separate hash flag. Existing callers of the public scan workflow continue using `inspect_file()` unchanged.
- Supporting zero-run state is now reusable `MeasurementContext` data. Policy evaluation does not mutate it.

All three resolved preset dictionaries match their pre-M3 snapshots. Discovery and streaming/consolidation behavior were verified against pre-change source. The detector AST differs only in replacing raw WARNING annotation with `None`; all detection calculations are identical. Loudness, BWF, metadata, hashing, consolidation, timecode, consistency, snippet export, CLI/GUI and report writers are byte-for-byte unchanged.

## Exact changed files

1. `src/audio_qc/measurement.py` — new execution/context structures
2. `src/audio_qc/rules.py` — requirements, pure policy evaluation and report-copy assessment
3. `src/audio_qc/scanner.py` — measurement orchestration and assessment boundary
4. `src/audio_qc/samples.py` — execution-only inputs and technical diagnostics
5. `src/audio_qc/defects.py` — unclassified raw evidence; no detection change
6. `src/audio_qc/models.py` — optional internal raw-candidate severity
7. `tests/test_policy.py` — new policy semantics tests
8. `tests/test_policy_separation.py` — new purity, requirements and orchestration tests
9. `tests/test_policy_baseline.py` — new pre/post regression matrix
10. `tests/fixtures/m3_baseline.json` — data captured from M2.1 before production edits
11. `tests/test_defects.py` — direct detector assertion now expects unclassified evidence; inspected/report severity tests retained
12. `README.md` — architecture and API documentation
13. `M3_VALIDATION.md` — this record

Generated validation artifacts are separate: `test_audio/m3-baseline/`, `reports/m3-before/`, `reports/m3-source-before.json`, nine `reports/m3-*.xml` JUnit files, `reports/m3-test-runs.json`, initial `reports/m3-smoke/` results, and `reports/m3-smoke-final/` with per-preset reports, `results.json` and `verification.json`. Existing source media, prior reports and the existing ZIP were not rewritten.

## Test results in requested order

| Stage | Pytest selection | Exact final terminal result |
|---|---|---|
| Focused policy | `tests/test_policy.py` | **42 passed in 0.03s** |
| Measurement/policy separation | `tests/test_policy_separation.py` | **15 passed in 0.59s** |
| Existing loudness | `tests/test_loudness.py` | **7 passed in 0.91s** |
| Existing configuration | `tests/test_config.py` | **19 passed in 0.06s** |
| Defects including M2.1 | `tests/test_defects.py tests/test_consolidation.py` | **78 passed in 4.77s** |
| Timecode | `tests/test_timecode.py` | **113 passed in 1.02s** |
| Recursive scanner/rules | `tests/test_scanner_rules.py` | **13 passed in 1.82s** |
| Reports/snippets and baseline | `tests/test_reports_cli.py tests/test_defect_csv.py tests/test_consolidation_reports.py tests/test_policy_baseline.py` | **23 passed in 5.15s** |
| Complete suite | all tests | **325 passed in 14.57s** |

Each command was `.venv/bin/python -m pytest <selection> -q --junitxml=reports/m3-<stage>.xml`, using stage names `policy`, `separation`, `loudness`, `config`, `defects`, `timecode`, `scanner`, `reports`, `regression`. The complete run omitted `<selection>`. All exited **0**, with **0 failures, 0 errors and 0 skips**. JUnit suite times can differ slightly from terminal totals.

The central architectural test constructs one measurement object with 48 kHz, 24-bit, -23 LUFS and -1.5 dBTP. EBU-style -23 ±0.5 / TP maximum -1 yields PASS/PASS; -14 ±1 / TP maximum -6 yields FAIL/FAIL, using that same untouched object. Additional tests block file opening and subprocess execution, repeat evaluation, verify no mutation of audio/configuration/context, and measure a real WAV once before applying two policies. Availability diagnostics survive both decoder errors and unexpected value errors. Source changes simulated after assessment still produce the final source-integrity failure without writing to the fixture.

## Baseline regression

Before changing production code, measured seven representative synthetic files with six resolved configurations: **42 file/configuration combinations**.

- Files: clean BWF, consolidated click pair plus a separate click, clipping, silence, long zero run, corrupt input, and nested 44.1 kHz/16-bit media.
- Configurations: FILM_48K, BROADCAST_EBU_R128, CUSTOM defaults, enabled defects with cap=1 and explicit zero-run failure, true-peak-only execution, and disabled level measurement.

Post-M3 results match the entire saved `AudioFile` dictionaries after replacing only temporary source path prefixes: all measured numbers, hashes, BWF metadata, ordered checks/messages, status and defect fields match. The golden data was captured before refactoring and was not regenerated from the new implementation. All four report outputs still generate, and the report schema remains version 2.

## CLI smoke tests

After the full suite, ran the equivalent of:

```sh
.venv/bin/audio-qc inspect test_audio/m3-baseline --preset FILM_48K --hash --output reports/m3-smoke-final/FILM_48K --quiet
.venv/bin/audio-qc inspect test_audio/m3-baseline --preset BROADCAST_EBU_R128 --hash --output reports/m3-smoke-final/BROADCAST_EBU_R128 --quiet
.venv/bin/audio-qc inspect test_audio/m3-baseline --preset CUSTOM --hash --output reports/m3-smoke-final/CUSTOM --quiet
```

| Preset | Files | PASS | WARNING | FAIL | CLI exit |
|---|---:|---:|---:|---:|---:|
| FILM_48K | 7 | 2 | 2 | 3 | 1 |
| BROADCAST_EBU_R128 | 7 | 1 | 1 | 5 | 1 |
| CUSTOM | 7 | 4 | 1 | 2 | 1 |

**All smoke comparisons passed.** Exit 1 is expected for this intentionally failing corpus, including corrupt and clipped media. Every per-file JSON result and the summary, configuration, timecode conventions and schema match the corresponding pre-M3 report. HTML, file CSV, defect CSV and JSON were generated for every preset. Nested media was discovered.

All seven smoke sources retain exactly the same SHA-256, byte size and modification time as before the refactor. Details are in `reports/m3-smoke-final/results.json` and `verification.json`.

## Known limitations

- Re-evaluation uses collected facts only. Numeric measurements omitted by the execution plan remain unavailable. Policies depending on detector evidence or zero-run facts require a plan that collected that evidence; changing detection parameters requires a new measurement pass.
- The golden numerical baseline was captured with FFmpeg/ffprobe 9.0.2. A future measurement-tool upgrade may require a reviewed baseline update; the tests do not silently regenerate it.
- HTML writers and local-link behavior are unchanged and report content was checked automatically. A new interactive browser-open/playback check was not performed because local-file navigation had previously been blocked by browser policy. GUI checks run offscreen in the full suite.
- Operational inspection/export failures still carry operational checks. They are distinct from delivery-specification policy; this milestone does not introduce a plugin framework or new presets.
