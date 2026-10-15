# M1 — SMPTE timecode reporting validation

Validated on 2026-10-07 on this Apple Silicon Mac using the existing virtual environment. No dependencies were added.

## Implementation

The repository already had the dedicated rational timecode converter, GUI controls beside the QC preset, CLI flags, all six frame rates, AUTO/FILE_RELATIVE/MANUAL modes, and canonical JSON/HTML timing data. M1 was completed incrementally:

- Accept `timecode.mode` as an alias for the existing `timecode.source` configuration key. Reject conflicting values before scanning, and retain `source` in serialized configuration.
- Add `QC_DEFECTS.csv`, with one row per candidate and separate TC, Offset, Frame Rate, TC Basis, original TimeReference, sample index, full timestamp and evidence columns. Keep `QC_REPORT.csv`'s existing file-level rows and columns.
- Explicitly identify frame rate as a reporting setting and timecodes as derived navigation labels in HTML.
- Make offset validation independent of any video frame rate.
- Expand deterministic coverage for second boundaries, configuration aliases, unsupported CLI rates, structured CSV, and preservation of actual detector results across every frame rate and source mode.

The reporting conversion uses exact integer ratios: 24000/1001 for 23.976 and 30000/1001 for 29.97. BWF conversion adds TimeReference and defect sample index before converting to a containing frame. Drop-frame numbering skips labels ;00 and ;01 at minutes not divisible by ten. OriginationTime is never used as a timeline origin. No detector or measurement logic or thresholds were changed.

## Changed files

Relative to the start of this M1 pass, the exact source, test and documentation changes are:

1. `src/audio_qc/timecode.py`
2. `src/audio_qc/config.py`
3. `src/audio_qc/reports/csv_report.py`
4. `src/audio_qc/reports/__init__.py`
5. `src/audio_qc/reports/html_report.py`
6. `tests/test_timecode.py`
7. `tests/test_defect_csv.py` — new
8. `README.md`
9. `M1_VALIDATION.md` — new

Generated validation artifacts are separate: `reports/m1-focused.xml`, `reports/m1-reports.xml`, `reports/m1-regression.xml`, and `reports/m1-smoke/` containing the four reports, one evidence WAV, and `verification.json`. Earlier validation reports were retained.

## Automated tests

Executed in the requested order from the project directory:

| Run | Command | Exact pytest terminal result |
|---|---|---|
| Focused timecode | `.venv/bin/python -m pytest tests/test_timecode.py -q --junitxml=reports/m1-focused.xml` | **113 passed in 1.09s** |
| Existing reports, new CSV and GUI | `.venv/bin/python -m pytest tests/test_reports_cli.py tests/test_defect_csv.py tests/test_gui.py -q --junitxml=reports/m1-reports.xml` | **19 passed in 1.95s** |
| Complete regression | `.venv/bin/python -m pytest -q --junitxml=reports/m1-regression.xml` | **212 passed in 10.01s** |

All three commands exited 0, with **0 failures, 0 errors and 0 skipped tests**. JUnit files record the results; their suite durations differ slightly from pytest's terminal totals.

Coverage includes all six rates, the required BWF reference case, missing/invalid/zero TimeReference, ignoring OriginationTime, FILE_RELATIVE and MANUAL, frame/second/minute/hour/24-hour boundaries, fractional frame boundaries, very large sample counts without drift, DF minute and ten-minute transitions, and all 17,982 sequential valid labels in a DF ten-minute block. Existing sample index and float timestamp values survive JSON round trips. A real detector fixture is preserved field-for-field across all 18 rate/source combinations. GUI tests run using Qt's offscreen platform.

## Representative BWF smoke test

After the complete suite:

```sh
.venv/bin/audio-qc inspect test_audio/timecode-example.wav --frame-rate 25 --hash --export-defect-snippets --output reports/m1-smoke --quiet
```

Result: **exit 0; 1 file, 0 PASS, 1 WARNING, 0 FAIL; 1 defect candidate**. The warning is the deliberately inserted click in this synthetic reference fixture.

| Field | Verified result |
|---|---|
| Sample rate | 48000 |
| Original BWF TimeReference | 172800000 |
| Reporting rate/source | 25 fps / AUTO → BWF TimeReference |
| File start TC | 01:00:00:00 |
| Defect sample index | 2529767 |
| Full timestamp_seconds | 52.70347916666667 |
| Displayed TC | 01:00:52:17 |
| File-relative offset | 00:00:52.703 |
| Duration | 3 samples / 0.0625 ms |

JSON, HTML and candidate CSV agree. All defect fields, candidate count, audio measurements and BWF data match the previous `reports/timecode-demo/QC_REPORT.json`. The existing basis identifier `BWF_TIMEREFERENCE` is retained for compatibility.

The source's SHA-256, byte count and modification timestamp were captured before this work and checked after the smoke test. SHA-256 remains `a434cd54b6feedf126fac1461dbbced1941bfecbce00b6c60a3a8d29dcfe3e55`; size remains 7,776,682 bytes; mtime remains 1791406747441920864 ns. Detector, audio measurement, BWF reader, scanner, presets and default defect configuration match the pre-change snapshots. Detailed assertions and hashes are saved in `reports/m1-smoke/verification.json`.

## Limits and conventions

- TC labels identify the containing video frame; sample index remains the exact location. Millisecond offsets are truncated for display, while JSON retains the existing float timestamp.
- TC wraps at 24 hours with separate day-offset fields. File-relative offsets can exceed 24 hours.
- Fractional NDF labels differ from elapsed wall time by design. BWF TimeReference does not identify a video frame rate; the operator must select the timeline's rate.
- This pass verified HTML structure and content automatically and GUI behavior offscreen. It did not perform a new browser visual review; local-file browser navigation was previously blocked by the browser policy.
