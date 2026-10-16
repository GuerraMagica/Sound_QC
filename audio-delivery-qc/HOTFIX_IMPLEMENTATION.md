# Reliability hotfix — implementation and acceptance record

## Repository state established before edits

Branch `main`, clean workspace, local HEAD and fetched `origin/main` both:
`9fc3b337721cc153919f481fdf42b16a386f6592`.

Baseline: `2e213732f2be1bafc3833eebcacd655b02de94ef`.

Previously published fixes:
- `cbdb68220aeb1caffdecda9682c4209f5f6a9fcc`: strict dependency-audit inventory, FFmpeg 6 input-layout compatibility, portable one-ULP libm baseline comparison.
- `fdfb001e72d0c727778f151d60b0046a50d39161`: deterministic Qt widget/application teardown.
- `9fc3b337721cc153919f481fdf42b16a386f6592`: audit documentation and reproductions, not H2–H5 implementation.

H1 was already implemented and remotely verified in [run 38810075928](https://github.com/GuerraMagica/Sound_QC/actions/runs/38810075928). The older failed run 38808334416 remains historical evidence; its visibility does not mean the fixes were absent. Before this release H2/H3 were missing, H4 was broken and H5 was partial. No uncommitted work was discarded.

## Root causes and corrections

| Gate | Root cause | Implementation / regression coverage |
|---|---|---|
| H1 | Strict audit rejected the editable project; FFmpeg 6 could not relabel the unknown input layout using aformat; Qt wrappers outlived test widgets | Existing fixes retained. No tests disabled, dependency advisories ignored or runtime downgraded. Linux headless Qt uses a session QApplication and explicit deletion/shutdown. Operational acceptance now also runs in CI. |
| H2 | Failed, absent and legitimately undefined measurements shared null/warning handling; invalid later metadata retained an earlier value | `MeasurementOutcome` records SUCCESS/UNAVAILABLE/ERROR. Parser validates complete numeric tokens and final True Peak summary, latches corrupt metadata and invalidates unverified loudness values. Silence remains unavailable. Scanner records requested failures; policy marks those results INCOMPLETE without new thresholds. Tests cover missing/corrupt output, real subprocess timeout and valid/undefined values. |
| H3 | One FAIL/check/status path combined process/evidence errors with delivery violations | Separate operational diagnostics and execution status. Genuine QC checks and evidence are preserved. Requested evidence failure returns 2; audio compliance does not become FAIL. Decode/inspection failures become incomplete execution. Tests cover genuine loudness/TP FAIL, evidence errors including actual directory creation denial, recovery, cancellation and preservation. |
| H4 | Handler detection assumed `/error.log` suffix | Explicit handler identity, independent of path spelling. Tests use POSIX, drive-letter and UNC Windows representations and check failed/not-yet-open handlers and repeated runs. |
| H5 | Logging warnings affected acoustic status; shutdown removed console handlers before reporting close errors; partial exports could look complete | Operational warnings in a single report snapshot; direct best-effort stderr for logging failures; atomic completion marker; best-effort recovery JSON on required report failure. HTML/JSON/CSV/CLI/GUI expose consistent compliance/execution. Tests include disk full, permissions, late logging, close failure, partial marker and GUI partial-report handling. |

Measurement modules still do not import policy targets. `rules.py` remains the canonical evaluator; no clustering or signal processing moved into policy. All raw detector severities remain unclassified before policy. Exact sample positions and source channel order remain authoritative.

## Changed files and purpose

- `models.py`: measurement outcomes, operational diagnostics, execution status and INCOMPLETE compliance.
- `loudness.py`: output validity/completeness, with unchanged valid-result calculations and EBU filter options.
- `scanner.py`: retain measured facts and record execution failures independently of QC.
- `rules.py`: canonical incomplete-result assessment; existing numerical comparisons unchanged.
- `snippets.py`: evidence errors as operational diagnostics, no acoustic FAIL.
- `diagnostics.py`: explicit error handler reference and non-recursive console warnings, including close errors.
- `cli.py`: separate inspection/export catches, consistent exit precedence, snapshot diagnostics and recovery attempt.
- `reports/__init__.py`, `html_report.py`, `csv_report.py`: schema 4, separate status displays, atomic completion marker and recovery snapshot. JSON serializer remains unchanged.
- `gui_window.py`: open complete partial-execution reports honestly, reject missing completion markers.
- `tests/test_hotfix_acceptance.py`: controlled failure, outcome, logging, evidence, recovery and source-integrity coverage.
- Existing operational, policy-separation, scanner, GUI, report and baseline tests: explicit new status/schema contract, retaining numerical and forensic assertions. No golden fixture rewritten. Broken-file legacy FAIL is now INCOMPLETE with the original diagnostic preserved separately; silence warning wording no longer conflates operational failure. The pre-existing one-ULP cross-platform float allowance was not widened.
- `scripts/verify_hotfix_release.py`: reproducible scenarios A–F, source fingerprints, runtime/commit provenance and optional exact baseline comparison.
- `.github/workflows/tests.yml`: execute operational acceptance after the unchanged complete test suite on Python 3.11/3.14.
- `README.md`, this document: status/exit/schema compatibility, finalization policy, validation and known limits.

## Verification commands

From `audio-delivery-qc`:

```sh
.venv/bin/python -m pytest -q tests/test_hotfix_acceptance.py tests/test_operational_robustness.py tests/test_policy_baseline.py tests/test_loudness.py tests/test_policy_separation.py tests/test_issue_severity.py tests/test_gui.py tests/test_custom_gui.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_hotfix_release.py --output reports/hotfix-release-acceptance --baseline-source /private/tmp/audio-qc-pre-hotfix-baseline/audio-delivery-qc/src
```

The old source was extracted read-only using `git archive 2e213732f2be1bafc3833eebcacd655b02de94ef audio-delivery-qc/src`. No environment or dependency installation was changed. The baseline comparison uses the same Python/FFmpeg process environment for both versions, avoiding runtime-version differences.

The installed app dependencies plus audit tooling were inventoried with `pip list --format=freeze --exclude audio-delivery-qc` using the application site-packages in the separate audit environment. `pip check` passed. Strict pip-audit used the exact pinned inventory, `--no-deps --disable-pip`, and a fresh advisory cache: 39 dependencies, no known vulnerabilities, exit 0. No packages or advisories were excluded except the unpublished local project itself; all its dependencies remain audited.

## Local test results (final code)

macOS 26.5.2 ARM64; Python 3.14.8; FFmpeg/ffprobe 9.0.2.

| Check | Passed | Failed | Skipped | Duration |
|---|---:|---:|---:|---|
| Focused command above | 153 | 0 | 0 | 11.26 s |
| Complete pytest suite | 542 | 0 | 0 | 21.52 s |
| Security inventory audit | 39 packages | 0 known advisories | 0 packages skipped | exit 0 |

The complete suite includes 22 offscreen GUI cases, real GUI CLI workers, executable/module/Finder-launcher tests, 35 new hotfix acceptance cases and the existing measurement/forensic regressions. The new INCOMPLETE enum expands the existing severity matrix by nine cases; no existing test was removed or skipped. Failures encountered during development were resolved by implementing the required status contract, adjusting explicitly obsolete failure classifications, and fixing the evidence test to compare identical detector configurations. No numeric reference or tolerance was weakened.

The final operational rerun is in `reports/hotfix-release-final`; the earlier security files remain in `reports/hotfix-release-acceptance`. Local artifact provenance records the pre-commit HEAD plus tracked changes; the accepted commit is established independently by the post-push GitHub run.

## Operational outcomes

Controlled synthetic WAVs only; no client delivery was available in the fixture folders inspected. Actual local acceptance results:

| Scenario | Measurement | Audio compliance | Execution | CLI |
|---|---|---|---|---:|
| A compliant mono BWF | SUCCESS | PASS | COMPLETED | 0 |
| B excessive loudness | SUCCESS | FAIL | COMPLETED | 1 |
| B excessive True Peak against configured limit | SUCCESS | FAIL | COMPLETED | 1 |
| C injected mandatory FFmpeg failure | ERROR | INCOMPLETE | PARTIAL | 2 |
| D injected evidence permission error | SUCCESS, original candidate retained | WARNING | PARTIAL | 2 |
| E digital silence | UNAVAILABLE, numeric null | WARNING | COMPLETED | 0 |
| F required HTML export failure | SUCCESS, recovery data preserved | PASS | FAILED | 2 |

Completed JSON/HTML agree; F has recovery JSON and no completion marker or success announcement. Tests also exercise true ENOSPC/EACCES exception classes, cancellation (130), malformed outputs and a real subprocess deadline. Disk failure is controlled injection, not an actual full disk.

All seven source fixtures retained SHA-256, size and mtime_ns. Seven measurement dictionaries matched baseline **exactly**, including Integrated, LRA, True Peak, sample peaks and zero-run data. Fixtures include mono, stereo, 5.1, silence, click, loud tone and a 60-second varying-level LRA signal. No threshold, detector, format support, normalization or source-writing change was introduced.

## Evidence and limits

Local artifacts are under `reports/hotfix-release-acceptance`: acceptance JSON, per-scenario reports/console, fingerprints, baseline measurements and dependency audit. These generated WAV/report files are intentionally not committed. The script reproduces them in a NEW output directory and CI prints its complete acceptance JSON, including exact HEAD and tracked-change status.

The final accepted commit and remote run are supplied in the release acceptance report after the push; this pre-publication document does not claim that a future run has passed. The two test jobs and security job must all succeed on that exact commit. Reviewers can reproduce the same commands from that checkout.

Limitations: GUI checks are automated offscreen tests with real CLI workers, not a new interactive visual review. Windows path semantics are deterministically tested; a native Windows OS run is not part of this Linux/macOS support matrix. Security checks cover known Python-package advisories, not external FFmpeg system libraries. Recovery and late diagnostics are best effort when the filesystem or stderr is unavailable. Report snapshots do not promise retroactive updates after a later logging failure. Schema 4 consumers must handle INCOMPLETE and separate operational state.

No M5/M6 implementation. M5 readiness requires verified remote acceptance of the finished commit.
