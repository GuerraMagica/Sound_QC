# M5 implementation and validation — 2026-10-16

M5 is implemented locally on baseline `65a5537fa61285da990e90ccd7438fb927618a7d`
(branch `main`). This document records validation before publication of the M5
commit; no remote M5 CI success is claimed. M6 has not been started.

## Implementation

- Optional exact filename discovery, custom suffix conventions and explicit YAML
  definitions, separate from delivery presets. Stereo and 5.1 logical mappings.
- Structural validation before cross-file consolidation; incomplete, ambiguous
  and inconsistent groups retain independent file inspection and reason codes.
- Conservative sample-space alignment: equal valid BWF origins, or a disclosed
  common-file-start policy when all origins are absent. Explicit common-start
  assertions disclose contradictory metadata. No inferred offsets or rollover.
- Fixed earliest-start/type/channel predicate shared with M3.1, default 1 ms,
  preserving constituents, maximum severity, exact samples and bounded caps.
- Per-source evidence links, separate file/group counts, additive JSON schema 4,
  a separate group CSV, and GUI loading/preview/validation with immutable snapshots.
- Combined loudness, LRA and True Peak remain **not measured**.

See [full format, rules and limitations](docs/PROGRAMME_GROUPS.md).

## Files changed

| File | Change |
| --- | --- |
| `src/audio_qc/programme.py` | Definitions, safe strict YAML, naming discovery, technical validation and measurement-side cross-file issue construction |
| `src/audio_qc/issues.py` | Extract shared type/start/channel predicate; existing single-source algorithm retained |
| `src/audio_qc/cli.py` | Opt-in groups, once-per-source inspection, group diagnostics and report inputs |
| `src/audio_qc/gui_window.py` | Minimal group controls, mapping preview, snapshot and results |
| `src/audio_qc/reports/programme_report.py` | Group TC navigation, HTML provenance/evidence and CSV |
| `src/audio_qc/reports/__init__.py` | Additive group JSON/counts/configuration and completion-marker deliverable |
| `src/audio_qc/reports/html_report.py` | Group section and collapsed original grouped-file forensic issues |
| `tests/test_programme.py` | Deterministic group, alignment, cap, forensic and report tests |
| `tests/test_programme_integration.py` | Actual FFmpeg/CLI/evidence/JSON/HTML/CSV and read-only integration |
| `tests/test_programme_gui.py` | Group configuration snapshots and actual GUI worker integration |
| `scripts/verify_m5.py` | Reproducible standalone CLI acceptance artifact generator |
| `docs/PROGRAMME_GROUPS.md`, `README.md`, this file | Configuration, compatibility, operational usage and validation |

No dependencies were added. Measurement/QC boundaries remain intact: the programme
module validates media relationships and constructs evidence; canonical policy
continues assessing each physical source. Group structural states are not acoustic
QC PASS/FAIL decisions. No threshold comparisons were duplicated.

## Executed tests

Working directory: `audio-delivery-qc`; interpreter: `.venv/bin/python`.
Runtime: Python **3.14.8**, macOS **26.5.2 ARM64**, FFmpeg/ffprobe **9.0.2**.

| Command | Passed | Failed | Skipped | Duration |
| --- | ---: | ---: | ---: | ---: |
| `.venv/bin/python -m pytest tests/test_programme.py tests/test_programme_integration.py tests/test_programme_gui.py -q` | 60 | 0 | 0 | 3.12 s |
| Focused existing regression command below | 420 | 0 | 0 | 9.91 s |
| `.venv/bin/python -m pytest -q` | 602 | 0 | 0 | 24.09 s |

Focused existing regression command:

```sh
.venv/bin/python -m pytest \
  tests/test_policy.py tests/test_policy_separation.py \
  tests/test_custom_policy.py tests/test_custom_config.py tests/test_config.py \
  tests/test_consolidation.py tests/test_consolidation_reports.py \
  tests/test_issues.py tests/test_issue_severity.py tests/test_issue_evidence.py \
  tests/test_timecode.py tests/test_scanner_rules.py tests/test_hotfix_acceptance.py -q
```

The complete suite retains all 542 baseline tests and adds 60 M5 tests. Existing
test expectations and golden fixtures were not changed. An initial regression
exposed an unnecessary label change in reports without groups; that implementation
was corrected, the two affected report tests passed, and both focused regression
and the full suite then passed. A review also ensured unresolved sample alignment
never emits invented group positions, with two explicit regression tests.

Final logs: `reports/m5-final/pytest-groups.txt`, `pytest-regression.txt`,
`pytest-full.txt` (generated local artifacts, not versioned).

## Operational acceptance

Executed:

```sh
.venv/bin/python scripts/verify_m5.py --output reports/m5-final
```

The script invokes the actual `python -m audio_qc inspect` runtime twice on the same
12 generated PCM24 WAVs, with and without `--detect-groups`, both exporting snippets.
Both CLI executions returned **0** (QC warnings are expected from these synthetic
fixtures). Exact argv, runtime, results and source fingerprints are recorded in
`reports/m5-final/acceptance.json`.

| Scenario | Actual result |
| --- | --- |
| Stereo multiple-mono | VALID, complete defect coverage, 4 group issues |
| 5.1 multiple-mono | VALID, complete defect coverage, 4 group issues |
| Shared dropout at sample 48000 | One issue per programme with all expected logical channels; TC 01:00:01:00 |
| L-only dropout at sample 96000 | Separate L issue |
| Clicks at samples 120000 and 120377 | Two separate issues despite identical displayed 25 fps TC |
| Missing R | INCOMPLETE, no cross-file issues |
| BWF origins 1000 versus 1001 | TECHNICALLY_INCONSISTENT, no cross-file issues; exact discrepancy retained |
| Existing interleaved source | Ordinary independent file; original channel layout and processing retained |
| Reporting | 17 file-level issues, 8 group-level issues, no sum presented as unique defects |
| Source evidence | Existing mono snippets referenced with logical-channel labels; no assembled WAV |
| GUI | Actual offscreen Qt window starts CLI, displays valid/incomplete groups and enables the completed report |

Complete physical-file report objects (including numeric measurements, checks,
forensic events and snippet references) were **exactly identical** with grouping
on and off. All 12 source SHA-256 hashes, byte sizes and nanosecond modification
timestamps were unchanged after both scans.

`git diff --exit-code 65a5537 --` confirmed no changes to `loudness.py`, `samples.py`,
`defects.py`, `rules.py`, `config.py`, `timecode.py`, `scanner.py`, `snippets.py` or
`consolidation.py`. The small `issues.py` predicate extraction is exercised by the
existing consolidation, cap, severity and multichannel evidence regressions.
`git diff --check` passed.

## Compatibility and limitations

- Existing file results and CSV shapes remain authoritative. JSON schema 4 is
  extended additively; `QC_GROUP_ISSUES.csv` is a separate view and part of the
  completion marker only when grouping was requested.
- Names are a declared convention, not proof of shared editorial content. An L/R
  pair alone cannot reveal whether four 5.1 channels are missing: select an explicit
  layout or supply a manifest when that distinction matters.
- Exact lengths and BWF starts are deliberately conservative structural criteria.
  Different origins are rejected in BWF/automatic mode; no resynchronization or
  offset-aligned assembly is implemented.
- Per-file caps remain bounded and can limit group coverage. Such results are
  labelled incomplete; a globally complete first-K group stream is not promised.
- Validation used synthetic audio, not client programme material. GUI integration
  was offscreen; no separate manual visual desktop test is claimed.
- This execution verified macOS/Python 3.14. Native Windows and the new remote
  Linux/Python 3.11/3.14 CI run have not been executed for this local M5 change.
- No combined LUFS/LRA/True Peak, new detector, audio reconstruction, downmixing,
  normalization or M6 work was added.

M5 local functional/integration acceptance: **PASS** within the documented scope.
