# M3.1 audit follow-up

Completed 8 October 2026, Europe/Madrid. This follow-up stops before M4.

## Confirmed report discrepancy

The exact supplied report was found at:

`/Users/juliomartinrodriguez/Desktop/Test/TEST_QC_AUDIO/LABM_QC_20261007_220417_013532/QC_REPORT.json`

It has schema **2**, the exact supplied `scan_date` **2026-10-07T22:25:22.006108+00:00** (8 October, **00:25:22 Madrid**), and no issue fields/configuration. This is an older report artifact, completed before M3.1 existed in this checkout:

- `issues.py` was created at **00:27:47 Madrid**.
- The schema-3 report writer was updated at **00:30:54 Madrid**.
- A later real report already generated schema **3** with `channels`, `channel_events` and `cross_channel_merge_ms: 1.0` at **00:40:45 Madrid**. Its path is `/Users/juliomartinrodriguez/Desktop/Test/TEST_QC_AUDIO/LABM/ST/LBM_CAP8_PM_2CH_18_09_26.R_QC_20261007_223844_255640/QC_REPORT.json`.

The current launcher imports the correct checkout; no installation or launcher correction was necessary. Reopening the earlier static HTML/JSON does not regenerate it. The older report does not record its historical executable/import paths, so its exact terminated process cannot be reconstructed from that file alone. Current runtime paths, the file chronology, the later real report and the fresh audit scan establish that the supplied schema-2 artifact predates M3.1; there is no evidence of an incorrect current installation.

## Actual launcher and runtime

Both `Open QC GUI.command` and `Run QC.command` resolve their own directory and explicitly use its `.venv/bin/python`. The GUI starts every scan as a fresh process using `sys.executable -u -m audio_qc ...`; it does not run the detector inside the persistent GUI process.

Verified runtime paths:

| Item | Actual path |
|---|---|
| Python executable (`sys.executable`) | `/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/.venv/bin/python` |
| Resolved executable | `/opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/bin/python3.14` |
| Imported `audio_qc` | `/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/__init__.py` |
| Imported `issues.py` | `/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/issues.py` |
| Imported report writer | `/Users/juliomartinrodriguez/Documents/ChatGPT/XQC/audio-delivery-qc/src/audio_qc/reports/__init__.py` |

Python is **3.14.8**. Editable-install metadata and the `.pth` file both point to this checkout's `src` directory. No dependencies were installed, replaced or rebuilt. Process inspection also observed the fresh scan running under this Homebrew Python framework, with the requested source and CLI arguments.

**No QC GUI process was running when inspected, so no GUI restart was needed.** Its scan worker imports current code on every new scan. GUI/launcher files are unchanged. The fresh scan below used the exact Python/CLI runtime that the GUI launches, with an explicit workspace output directory; it was not initiated by clicking the GUI.

Runtime evidence is recorded in [runtime-before.json](reports/m31-audit/runtime-before.json).

## Severity correction

Before this fix, `_issue()` copied severity from the earliest representative. An INFO representative could therefore hide a WARNING or FAIL on another channel. A second path existed in `_merge()`: replacing a channel representative with a stronger candidate could discard an earlier higher severity before issue construction.

Both aggregation points now preserve the highest **existing** classification using one small model helper. Precedence follows the application's existing status ordering: **FAIL > WARNING > PASS > INFO**. `None` contributes no classification; all-`None` events produce an unclassified channel event and issue. No threshold, QC decision or default severity is introduced during measurement.

Representative selection still preserves the same sample index, exact timestamp, duration, detection method and measured values. Constituent channel events remain available. The issue's severity is aggregated independently of representative selection. Input objects are not mutated.

QC policy code is unchanged. Its existing default assessment still classifies an unclassified issue as WARNING on an independent report copy. Already classified issues retain their aggregated severity. Measurement-side channel events remain `None` under the normal detector workflow.

## Validation in the requested order

| Stage | Command | Exact result |
|---|---|---|
| Focused severity/policy | `.venv/bin/python -m pytest -q tests/test_issue_severity.py tests/test_policy.py tests/test_policy_separation.py` | **87 passed in 0.65s** |
| Consolidation/evidence regression | `.venv/bin/python -m pytest -q tests/test_consolidation.py tests/test_issues.py tests/test_consolidation_reports.py tests/test_issue_evidence.py tests/test_defects.py tests/test_reports_cli.py tests/test_defect_csv.py` | **143 passed in 7.91s** |
| Complete suite | `.venv/bin/python -m pytest -q` | **403 passed in 16.48s** |
| Fresh real-source scan | Actual launcher Python/CLI runtime, command below | Completed; schema **3**, expected QC FAIL / exit **1** |

All pytest commands exited **0**, with **0 failures, 0 errors and 0 skips**. Thirty new severity tests cover INFO+WARNING, WARNING+FAIL, constituent order, representative changes, existing PASS handling, unclassified measurements, default policy, repeated assessment and input immutability. One new regression preserves the supplied reference intervals. Existing M3 golden/purity and M3.1 bounded-cap/evidence tests pass.

The detector, thresholds, sensitivity, merge tolerances, timecode, policy, measurement interfaces, snippet exporter, GUI and launchers are byte-for-byte unchanged against the pre-audit snapshot. Only severity aggregation changes in consolidation; sample interval/strength calculations are unchanged.

## Fresh real-source scan

The real reference source was locally available and was scanned in full:

`/Users/juliomartinrodriguez/Desktop/Test/TEST_QC_AUDIO/LABM/5.1/LBM_CAP8_PM_6CH_18_09_26.C.wav`

Despite its filename, this physical source is **mono**, **48 kHz**, **24-bit**, **3245.96 seconds**. The scan decoded **155,806,080** sample frames. It used the original report's Broadcast preset, 25 fps, AUTO TC, medium click sensitivity and unchanged 1.0 ms intra-channel tolerance. The default 1,000-issue cap was retained.

```sh
.venv/bin/python -u -m audio_qc inspect \
  '/Users/juliomartinrodriguez/Desktop/Test/TEST_QC_AUDIO/LABM/5.1/LBM_CAP8_PM_6CH_18_09_26.C.wav' \
  --preset BROADCAST_EBU_R128 --frame-rate 25 --defects --hash \
  --output reports/m31-audit/real-source
```

The fresh report completed at **00:59:23 Madrid** on 8 October (JSON UTC timestamp `2026-10-07T22:59:23.139680+00:00`), in **76.104 seconds**. It contains:

- `schema_version: 3`;
- `channels` and `channel_events` on all **1,000** retained issues;
- `configuration.defects.issues.cross_channel_merge_ms: 1.0`.

Fresh artifacts:

- [QC_REPORT.json](reports/m31-audit/real-source/QC_REPORT.json)
- [QC_REPORT.html](reports/m31-audit/real-source/QC_REPORT.html)
- [Verification record](reports/m31-audit/real-source-verification.json)

The CLI exit **1** is its expected QC-failure result, not an execution failure: the source retains the original integrated-loudness failure, **−25.326 LUFS against −23 ±0.5 LU**. All file measurements, BWF fields and ordered checks match the old report exactly. All 1,000 legacy issue records match as a multiset, excluding snippet paths and the new issue wrapper fields. Sample/timestamp precision is unchanged.

## Reference clusters and evidence

| Cluster | First sample | Last sample (inclusive) | Representative sample | Merged raw count |
|---|---:|---:|---:|---:|
| A | 1933158 | 1933175 | 1933168 | 2 |
| B | 1933553 | 1934029 | 1933792 | 2 |

Both fresh issues match the supplied report exactly. The gap is `1933553 − 1933175 − 1 = 377` samples, or **7.854166666666667 ms**. They remain **two issues** under the unchanged 1.0 ms merge tolerance.

Two reference snippets were exported separately after the scan using the unchanged safe exporter and the fresh issue data. The exporter preserves the full issue extent with one second before/after. No other source audio was exported during this audit.

- [Cluster A WAV](reports/m31-audit/reference-evidence/defect_snippets/file_00001_event_00001.wav): source sample range `[1885158, 1981176)`, 96,018 frames.
- [Cluster B WAV](reports/m31-audit/reference-evidence/defect_snippets/file_00001_event_00002.wav): source sample range `[1885553, 1982030)`, 96,477 frames.

Both remain mono/48 kHz. Their decoded samples match independent direct PCM reads from the original WAV exactly. Their **95,623 overlapping samples** are identical, as expected from shared source context; this does not affect consolidation. [Evidence verification](reports/m31-audit/reference-evidence-verification.json) records the ranges and comparisons.

The source SHA-256 before/after scan and export is unchanged:

`e71f3680c189dfc755b128754229f579f3283a2a531ded7ce6dbb359f8050482`

Source size (**469,892,352 bytes**), modification time and inode are unchanged. The old report is also unchanged. No BWF metadata was rewritten.

## Files changed and limits

- `src/audio_qc/models.py` — aggregate existing severities without classifying `None`.
- `src/audio_qc/issues.py` — issue severity independent of representative selection.
- `src/audio_qc/consolidation.py` — preserve severity when a channel representative changes.
- `tests/test_issue_severity.py` — new severity/policy/immutability coverage.
- `tests/test_issues.py` — exact real-reference interval regression.
- `M31_AUDIT.md` — this audit record.

Generated records/reports/two evidence WAVs are confined to the new `reports/m31-audit/` directory. No installation/launcher/dependency/configuration change was required.

The real scan retains the existing 1,000-issue cap and corresponding cap warning; it is not an exhaustive defect inventory beyond that limit. The normal sample/loudness passes still covered the full source. Fresh full-report snippet links are empty because the scan used `--defects`, with only the two reference evidence WAVs exported separately. GUI tests ran offscreen; this audit did not add an interactive GUI/browser playback check or proceed to M4.
