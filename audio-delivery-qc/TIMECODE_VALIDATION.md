# Timecode reporting validation — 7 October 2026

Implemented the reporting-only timecode layer, GUI/CLI/YAML controls, HTML/CSV/JSON fields and optional local PySide6 GUI. The scanner still detects defects at sample resolution.

## Exact test results

- Focused command: `.venv/bin/python -m pytest tests/test_timecode.py tests/test_gui.py -q --junitxml=reports/timecode-focused.xml`
- **85 passed, 0 failed, 0 errors, 0 skipped** in 1.266 s (pytest console: 1.28 s).
- Complete regression command: `.venv/bin/python -m pytest -q --junitxml=reports/timecode-regression.xml`
- **175 passed, 0 failed, 0 errors, 0 skipped** in 9.791 s (pytest console: 9.81 s).
- `pip check`, Python byte compilation, and `zsh -n 'Open QC GUI.command'` passed.

Focused coverage includes all six reporting rates; exact rational boundaries and very large positions; minute/hour/day boundaries; the full 17,982-frame ten-minute DF sequence; skipped DF labels; AUTO fallback; a valid zero TimeReference; manual starts; subframe BWF origins; sample/timestamp preservation; mixed-file report origins; HTML/CSV/JSON; configuration/CLI validation; and GUI controls and a real GUI-to-CLI scan.

## Real synthetic BWF scan

A new 54-second synthetic WAV was created with a BEXT TimeReference of 172800000 at 48000 Hz and a three-sample artificial click starting at sample 2529767. No existing audio or BWF headers were changed to construct it.

Command: `.venv/bin/audio-qc inspect test_audio/timecode-example.wav --frame-rate 25 --hash --export-defect-snippets --output reports/timecode-demo --quiet`

Result: one candidate, WARNING, zero failures; three reports and one evidence WAV were generated. File start TC is **01:00:00:00**, event TC is **01:00:52:17**, offset is **00:00:52.703**. Exact JSON values remain `sample_index: 2529767` and `timestamp_seconds: 52.70347916666667`. BWF TimeReference remains 172800000. The source SHA-256, size and nanosecond mtime match the pre-scan manifest. All 20 prior demo sources also retain their original hashes, sizes and mtimes.

## Detector preservation

SHA-256 comparisons confirm that `defects.py`, `samples.py`, `scanner.py`, `bwf.py`, `rules.py` and `snippets.py` are byte-for-byte unchanged from before this task. The reporting layer enriches copies and does not mutate the detector's Defect/AudioFile instances. Test-media creation gained an optional TimeReference argument for newly created fixtures only.

## GUI and review

PySide6 6.11.2 was installed only in `.venv`. Qt's offscreen tests verify the six frame-rate choices beside the QC preset, AUTO default, conditional manual entry, semicolon handling, invalid DF rejection and an actual asynchronous scan. The generated GUI layout was inspected visually in `reports/timecode-gui.png`. This is an offscreen review, not a native macOS interaction test.

The HTML content, headings, exact evidence and local links are tested. No browser visual review was performed; the browser's previously observed policy rejects local file URLs. The report remains a self-contained local file for the operator to open.

## Artifacts

- `reports/timecode-demo/QC_REPORT.html`
- `reports/timecode-demo/QC_REPORT.csv`
- `reports/timecode-demo/QC_REPORT.json`
- `reports/timecode-demo/verification.json`
- `reports/timecode-focused.xml`
- `reports/timecode-regression.xml`
- `reports/timecode-gui.png`
- `test_audio/timecode-source-manifest.json`

Operational conventions: 25 fps / AUTO by default; 23.976 = 24000/1001, 29.97 = 30000/1001; frame labels use floor/containing-frame conversion; file offsets truncate to milliseconds; TC wraps at 24 hours with separate day offsets; sample positions remain authoritative. NDF labels at fractional rates do not run at wall-clock speed.
