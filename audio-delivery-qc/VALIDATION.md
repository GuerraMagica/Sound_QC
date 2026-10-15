# Validation record — 7 October 2026

Verified locally on macOS 26.5.2 / Apple Silicon, Python 3.14.8, FFmpeg and ffprobe 9.0.2. See `requirements-verified.txt` for exact Python dependency versions.

## Automated tests

Command: `.venv/bin/python -m pytest -q --junitxml=reports/pytest-validation.xml`

**90 passed, 0 failed, 0 skipped**, in 8.43 seconds. The installed CLI, `python -m audio_qc`, and the Finder launcher's interactive Terminal flow all ran successfully. `pip check`, Python byte-compilation, and the launcher shell syntax check also passed.

Tests exercise real FFmpeg decoding and loudness, 5.1 LFE exclusion, 7.1, unavailable unknown layouts, intersample peaks exceeding sample peaks, BEXT 64-bit fields, RF64 seeks beyond 4 GiB, corrupt/truncated files, read-only sources, clipping/overload/non-finite samples, Unicode/nested paths, preset/config validation, rule/status logic, group consistency, duplicates, reports and process errors/timeouts. Evidence export is compared against the original samples. Processing-boundary tests cover clicks and dropouts. The sparse >4 GiB fixture tests metadata seeking, not a full-duration >4 GiB decode benchmark.

## Full application smoke test

Command: `.venv/bin/audio-qc inspect test_audio/synthetic --output reports/validated-smoke --hash --export-defect-snippets --quiet`

Twenty locally generated audio files were scanned in 4.149 seconds. Result: **3 PASS, 14 WARNING, 3 FAIL**. Exit code 1 is expected: the deliberately clipped source, wrong-rate source and corrupt source fail their intended checks. Warnings include absent BEXT and candidate defects; clean negative-control audio is not asserted to satisfy every unrelated delivery rule.

All three reports exist and parse. Five evidence WAVs exist. The HTML has 20 unique file anchors and five valid local evidence links. The before/after SHA-256, file size and nanosecond modification time match for **all 20 source files**. Group findings include mixed rates/counts, duration differences/outlier, identical decoded audio, and the intentionally missing MX stem.

Artifacts:

- `reports/validated-smoke/QC_REPORT.html`
- `reports/validated-smoke/QC_REPORT.csv`
- `reports/validated-smoke/QC_REPORT.json`
- `reports/validated-smoke/defect_snippets/`
- `reports/validated-smoke/verification.json`
- `reports/pytest-validation.xml`
- `test_audio/source_manifest.json`

## Defect regression benchmark

Five positives (one-sample click, multi-sample click, exact-zero dropout, attenuation dropout, one-channel dropout): **5 detected, 0 missed**. Three negatives (clean sine, controlled legitimate transient, intentional one-second silence): **0 false positives, 3 correctly unflagged**. Both array fixtures and quantized PCM files were tested. Additional attenuation tests span 5–490 ms.

These are small deterministic regression controls, not accuracy estimates for real productions. Automated defect detection identifies candidates for human QC review. It does not prove that an audible defect exists.

## Verification limits

The HTML structure, escaping, data and local links were verified automatically. A visual browser inspection was **not completed**: the browser tool's URL policy rejects `file://` URLs. No alternate browser or server workaround was used. Open the HTML directly in Finder for the remaining visual review.

The optional native GUI was omitted because importing tkinter fails with `ModuleNotFoundError: _tkinter` on this Python installation. The tested Finder Terminal launcher remains available. True-peak reporting precision is 0.1 dB. The scope and other technical limitations are documented in README.md.
