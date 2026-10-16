# M5 real-world acceptance follow-up — 2026-10-17

Baseline: `03dfdae394e644b045a79b3c3f88b2e65c575ff2` (M5).
Scope: measurement-result interpretation, operator reporting and configuration
clarity. No M6, detector tuning, grouping tolerance changes or new acoustic engine.

## Findings and disposition

| Finding | Confirmed cause / action |
| --- | --- |
| Six BWF mono members identified as valid 5.1 | Correct: all origins 172800000, 48 kHz, PCM24, 155806080 decoded samples each. Membership/alignment code unchanged. |
| Mono C/LFE fail a -24 LUFS comparison | Existing policy compares each physical file. It cannot establish assembled-programme compliance. Preserve these diagnostic comparisons and explicitly label their scope; programme compliance is NOT_EVALUATED. |
| Four Integrated LUFS errors | Reproduced: FFmpeg emitted NaN in M/S windows, while final I and LRA remained finite. The parser incorrectly invalidated all integrated results when any auxiliary metric was invalid. Isolate auxiliary errors; retain null/ERROR and operational diagnostics for affected maxima. |
| Issues 0032/0033 did not consolidate | Correct under the accepted rule: cluster starts differ by 110 samples, exceeding the inclusive 48-sample window at 48 kHz. Representatives one sample apart and identical TC do not override cluster starts. Add deterministic tests; do not change grouping. |
| 1957 file / 1000 group issues | Retained counts, not full coverage. Member C and group caps are reached. Preserve INCOMPLETE coverage and show a prominent warning; no limit changes. |
| Overwhelming HTML | Summarize programme issues by category with collapsed tables and counts of retained rows; collapse grouped-file forensic details. Keep every row, source reference, evidence link and exact sample. |
| True Peak screenshot -1 versus report null | No synchronization defect reproduced. User supplied the screenshot and confirmed the prior run might lack that setting. GUI/save/load/snapshot/actual-worker tests preserve -1. Add an effective-limit hint and log the applied snapshot; do not retroactively change the original configuration. |
| Assessed group severity lost | Final real-scan review exposed unclassified group rows despite WARNING file issues. Preserve the existing file-issue classification separately as `file_issue_severity`, aggregate highest applicable severity, and keep unclassified measurement events unchanged. No classification is invented. |
| Physical versus logical channels | Clarify that multiple-mono 5.1 has six logical roles in six one-channel files; `channels.allowed: [6]` checks physical channels inside each file and is not the programme layout. |

## Reproduced FFmpeg observations

Original report: `5_QC_20261016_215333_974e3a41/QC_REPORT.json`, scan date
`2026-10-16T22:09:02.171232+00:00`, schema 4. Actual local runtime and original
report both use FFmpeg/ffprobe 9.0.2. The six original WAVs were read without
modification. The probe records the first invalid observation for each metric:

| Role | Invalid metadata observed | Final Integrated LUFS metadata | Final LRA metadata |
| --- | --- | ---: | ---: |
| C | none | -25.326 | 20.67 |
| L | S=nan at 12.0 s | -30.127 | 18.28 |
| LFE | none | -42.774 | 20.46 |
| Ls | M=nan at 9.5 s; S=nan at 2389.0 s | -33.735 | 16.85 |
| R | M=nan at 9.5 s | -30.367 | 17.86 |
| Rs | M=nan at 9.5 s; S=nan at 489.7 s | -33.680 | 17.50 |

These four files are not silent/undefined Integrated measurements and FFmpeg did
not terminate unsuccessfully. The verified parser defect was cross-metric error
propagation. The internal FFmpeg cause of those NaN windows remains unresolved;
this change does not claim to repair FFmpeg or reconstruct missing maxima.

Outcome semantics remain SUCCESS / UNAVAILABLE / ERROR. Affected M/S maxima stay
null and ERROR, even if later observations become finite. Their errors produce
operational warnings, not invented acoustic defects. Independent valid I/LRA/TP
results survive. Invalid or missing mandatory I/TP, process failures and timeouts
still prevent a completed QC PASS. True silence/negative infinity is not reclassified
as an execution failure.

The complete suite caught an additional required distinction: non-finite samples
in the source WAV must not be confused with an isolated invalid FFmpeg statistic
on finite PCM. A measurement-side guard now uses the existing decoded
`nonfinite_samples` fact to withhold certification of EBU R128 results on known
corrupt samples. The existing acoustic nonfinite-sample FAIL and operational
INCOMPLETE/PARTIAL behaviour remain intact; original tests were not weakened.

## Exact event evidence

| Group issue | Role | Cluster first | Representative | Cluster last (inclusive) | Raw count |
| --- | --- | ---: | ---: | ---: | ---: |
| 0032 | Rs | 4800077 | 4800188 | 4800202 | 2 |
| 0033 | Ls | 4800187 | 4800187 | 4800203 | 1 |

`4800187 - 4800077 = 110` samples = `2.2916666667 ms`. The configured
cross-channel tolerance is 1 ms = 48 samples. Both display `01:01:40:00` at
25 fps. Regression tests preserve this pair as two issues, also testing 49 samples
(separate), 48 samples (merge) and 47 samples (merge), with unchanged forensic data.

## Reporting and configuration compatibility

JSON schema remains **4**, extended additively:

- `compliance_scope: PHYSICAL_FILES` at scan level.
- `programme_compliance: NOT_EVALUATED` for grouped scans and each group.
- Group `compliance_note` and `issue_summary` (retained count, by type/severity,
  coverage). No unobserved issues are estimated.
- Per-metric outcomes now include LRA, maximum momentary and maximum short-term
  loudness when the parser has completed a summary.

`audio_compliance`, `status`, file checks and CLI exit codes retain their original
physical-file semantics. A mono diagnostic FAIL is not silently converted into
PASS and is not presented as a programme verdict. No virtual measurement exists.
CSV shapes and evidence exporting are unchanged. HTML exposes programme/category
summaries first and keeps complete forensic rows in native expandable sections.

For the historical -1 dBTP screenshot, scan timing cannot be reconstructed from the
image alone. The authoritative old report configuration is `maximum: null`. Tests
verify both active -1 and an inactive retained -1 value, save/load, immutable worker
snapshots and an actual GUI scan whose report contains `maximum: -1`. The GUI log
now records the effective limit at scan start. Restart an already-open GUI to load
the new controls/help text; old reports remain historical snapshots.

## Changes

- `loudness.py`: independent metric outcomes and finite-source validity guard.
- `scanner.py`: report optional measurement errors as operational diagnostics.
- `reports/__init__.py`, `html_report.py`, `programme_report.py`: explicit compliance
  scope, retained category counts and progressive disclosure.
- `spec_editor.py`, `gui_window.py`: effective True Peak feedback and channel meaning.
- `programme.py`: retain assessed parent-file issue severity with forensic provenance; temporal rules unchanged.
- `cli.py`: explicit programme-versus-file compliance summary.
- `tests/test_m5_followup.py`, `tests/test_m5_followup_gui.py`: 25 focused regressions; `test_programme_integration.py` also verifies severity through actual CLI detection/policy/group/report execution.
- This report and `PROGRAMME_GROUPS.md`: evidence and semantics.

The following modules remain unchanged: `defects.py`, `samples.py`, `issues.py`,
`consolidation.py`, `rules.py`, `config.py`, `timecode.py`,
`snippets.py`, and the FFmpeg filter/arguments. No source audio, BWF metadata,
thresholds, candidate limits, merge gaps or navigation calculations were modified.

## Automated validation

Local runtime: Python 3.14.8, macOS 26.5.2 ARM64, FFmpeg 9.0.2.

```sh
.venv/bin/python -m pytest \
  tests/test_scanner_rules.py::test_float_overload_and_nan \
  tests/test_m5_followup.py tests/test_m5_followup_gui.py \
  tests/test_hotfix_acceptance.py tests/test_programme.py \
  tests/test_programme_integration.py tests/test_programme_gui.py \
  tests/test_custom_gui.py -q
# 137 passed, 0 failed, 0 skipped, 9.26 s

.venv/bin/python -m pytest -q
# 627 passed, 0 failed, 0 skipped, 25.27 s

.venv/bin/python scripts/verify_hotfix_release.py \
  --output reports/m5-followup/hotfix-acceptance
# Exit 0; operational acceptance scenarios A–F passed.
```

No golden fixtures or existing expected results were changed. The old corrupt-WAV
regression initially failed after isolating auxiliary outcomes; the source-validity
guard corrected it and both focused/full suites were rerun successfully. GUI checks
use actual Qt offscreen windows and subprocess workers. Remote CI for the published
commit must be verified separately; local results are not remote CI evidence.


## Completed real-source acceptance

The six actual production WAVs were scanned, using the historical report's exact
configuration without altering it:

```sh
.venv/bin/python -m audio_qc inspect \
  '/Users/juliomartinrodriguez/Desktop/Test/TEST_QC_AUDIO/LABM/5.1' \
  --config reports/m5-followup/real-config.yaml --detect-groups --defects \
  --verbose --output reports/m5-followup/real-scan
# CLI exit 1: physical-file QC FAIL; execution COMPLETED_WITH_WARNINGS.
# Elapsed 884.788 s. Schema 4.
.venv/bin/python reports/m5-followup/verify_real.py
# All assertions passed; evidence: reports/m5-followup/real-acceptance.json.
```

Actual results:

- All six Integrated measurements SUCCESS; all six physical-file diagnostics FAIL
  under the unchanged -24 ±1 LUFS target. Programme compliance NOT_EVALUATED.
  The physical-channel restriction remains [6], as in the original configuration;
  the sources each have one physical channel. These are separate from logical 5.1.
- Four formerly invalidated Integrated results now retain the independently finite
  values in the table above. Auxiliary M/S errors remain explicit, with null values.
- All 1957 file issues and 1000 group issues matched the original report exactly,
  excluding snippet paths because the existing 1957 evidence WAVs were not exported
  a second time. No source evidence was deleted or overwritten.
- Group VALID, origin 172800000; 995 click/tick and 5 dropout issues retained.
  The C member and group cap warnings are unchanged. Coverage INCOMPLETE.
- Every non-loudness measurement, BWF value, sample position, raw-candidate count,
  and grouping interval matched. C/LFE measurement dictionaries matched completely.
- All six source SHA-256 hashes, file sizes and nanosecond modification times
  matched their pre-scan fingerprints. Each source is 469892352 bytes.

The final severity propagation correction was discovered after this full real
scan. The measured results were reused through the actual group builder and report
writer (`reports/m5-followup/replay_groups.py`) to produce **real-final/**. This is
explicitly recorded as a group/report replay, not another decode. Every source
channel-event, group membership, bound and measurement was asserted identical;
only existing WARNING classification propagation and its provenance field changed.
All 1000 retained group issues now have WARNING. The final full suite includes a
fresh synthetic CLI detection/policy/group/evidence run with this correction.

Local evidence (excluded from Git to avoid distributing production media/reports):

- `reports/m5-followup/real-scan/QC_REPORT.json`: original fresh full CLI result.
- `reports/m5-followup/real-final/QC_REPORT.html` and `.json`: final group/report view.
- `reports/m5-followup/real-acceptance.json`: exact comparison and integrity checks.
- `reports/m5-followup/group-replay-acceptance.json`: final severity/provenance checks.
- `reports/m5-followup/source-before.json`: source fingerprints.
- `reports/m5-followup/loudness-probe.json`: independent FFmpeg metadata observations.
- `reports/m5-followup/pytest-focused-final.txt`, `pytest-full-final.txt`: test logs.

## Remaining limitations and acceptance scope

- This delivery has **INCOMPLETE defect coverage** because configured caps were
  reached. Retained results do not establish complete programme inspection.
- Combined programme Integrated LUFS, LRA and True Peak remain unmeasured in M5;
  programme compliance is NOT_EVALUATED. No M6 implementation is included.
- FFmpeg 9.0.2 emitted invalid M/S windows on finite PCM. Their internal cause is
  unresolved; affected maxima are not certified or reconstructed.
- The historical screenshot does not prove the settings at scan start. The user
  explicitly noted that -1 dBTP might have been entered later. Restart the GUI and
  inspect its applied snapshot/new report on the next operator run.
- GUI tests are Qt offscreen, including real subprocess scans. Visual inspection
  of the fresh local HTML in the automated browser was unavailable: its URL policy
  blocks `file:` navigation. HTML structure, retained rows, escaping and evidence
  links are covered by automated tests; no visual inspection success is claimed.
- Final publication SHA and exact remote Actions outcome are supplied in the
  release completion response. M5 GO requires those jobs to pass; a previous run
  is insufficient. GO refers to M5 grouping/assisted review, not certification of
  this delivery's programme loudness or complete defect coverage.
