# Operational robustness follow-up

Validated locally on 2026-10-15, Europe/Madrid. This work improves the existing M4 application; M5/M6 are not implemented by this change.

## Findings and implemented corrections

The repository already contained strict YAML validation, a working PySide6 GUI and 467 tests. Existing tests covered loudness reference signals, true/intersample peaks, clipping, silence/dropouts, corrupt media, BWF, evidence preservation and subprocess timeouts. FFmpeg and ffprobe already used structured argument lists with local-only input protocols. Those implementations were retained.

- `src/audio_qc/diagnostics.py` adds per-run Python logging with timestamped rotating `scan.log` and lazy `error.log` files. A failed file-handler write records its failure without emitting Python logging's secondary traceback. Run handlers are closed and detached after use.
- `src/audio_qc/cli.py` catches unexpected top-level exceptions, reports exit code 2, writes tracebacks only to local logs when possible, and honestly reports unavailable logs. Known configuration/dependency/I/O failures retain concise errors. Cancellation still returns 130. A report-writing failure never prints a successful HTML report location. Unexpected evidence-export errors retain the file measurements already collected, while marking the file failed and continuing other files.
- `--verbose` exposes per-file progress and diagnostic checks. Default and `--quiet` output retain the summary and errors. Detailed logs are written regardless of console verbosity. `gui_window.py` passes `--verbose` so the existing GUI progress display remains useful.
- `src/audio_qc/config.py` retains the canonical strict validator and safe YAML loader, adding source marks and field identifiers to validation failures. Error messages include path, line and column when the offending setting is present. Cross-field errors identify an involved field; parse errors use PyYAML's locations. Missing fields/default-only failures may have only the path. No Pydantic/jsonschema dependency or second policy representation was added.
- `.github/workflows/tests.yml` adds push, pull-request and manual CI triggers. Python 3.11/3.14 jobs install FFmpeg and optional GUI/test dependencies, then run the full suite offscreen. A separate strict dependency-audit job checks the installed environment. Read-only repository permissions, non-persisted checkout credentials and pinned official action commit hashes are used.
- `tests/test_operational_robustness.py` adds 25 cases. README documents changed verbosity, local logs, failure semantics and CI.

## Verification

| Check | Exact result |
|---|---|
| New robustness tests | 25 passed in 0.34s |
| Focused robustness/config/GUI/report/loudness/policy tests | 157 passed in 3.79s |
| Complete pytest suite | 492 passed in 18.58s |
| Workflow YAML/triggers/matrix/permissions | Local structural checks passed |
| Existing GUI-save / CLI-equivalence smoke | Passed, script exit 0 |
| pip-audit 2.10.1, installed dependency versions | Exit 0; 14 dependencies; no known vulnerabilities found |

Full suite had no failures, errors or skips. Golden fixtures were not regenerated. No production changes followed the full test run.

Fault tests inject ENOSPC and permission failures into report writing and log opening, including simultaneous report/log failure. These are deterministic injected failures, not a claim that the physical disk was filled. Tests also cover pre-output failures, existing-output protection, partial inspection/evidence failures, repeated CLI invocations without duplicate handlers, normal/quiet/verbose output, duplicate/unknown/invalid YAML locations, and cancelled child-process cleanup. A real subprocess is interrupted with KeyboardInterrupt; the test verifies it is reaped and both pipes are closed.

A failed FFmpeg run that has already emitted a plausible EBU summary remains unavailable rather than producing a false successful measurement. A BWF fixture without iXML is inspected read-only and remains valid BWF; its deliberately excessive loudness fails the existing EBU policy. Missing iXML was not turned into a new delivery requirement.

## Smoke and source safety

The unchanged runtime `.venv/bin/python` (Python 3.14.8) imports this checkout under `src/audio_qc`; FFmpeg/ffprobe are 9.0.2. The smoke uses real GUI handlers and a real QProcess worker with Qt offscreen, followed by the CLI with the exact GUI-saved CUSTOM YAML. It is an automated GUI check, not a new interactive visual check.

The complete GUI/CLI JSON matches after excluding only scan date and elapsed time. Schema remains 3. The deliberately out-of-spec fixture has QC status FAIL and worker exit 1, as expected; this is not a processing failure. Stereo evidence samples match the original source interval and channel order.

Artifacts:

- `reports/operational-robustness/gui-cli-smoke/verification.json`
- `reports/operational-robustness/gui-cli-smoke/cli/QC_REPORT.html`
- `reports/operational-robustness/gui-cli-smoke/cli/scan.log`
- `reports/operational-robustness/pip-audit.json`
- `reports/operational-robustness/installed-requirements.txt`

Source fingerprint, identical before and after scanning/evidence export:

```text
SHA-256: 3ff10b8e531d3a94a993fa6d44bb188138193e2f02d2b7845195464c0a011039
Size: 864706 bytes
mtime_ns: 1792098337471794426
```

## Security review and audit scope

Production subprocess calls in `process.py` and callers were inspected: all use argument lists, none enable `shell=True`. Source filenames are passed as literal arguments; report/evidence filenames are generated separately. Existing canonical output-path validation also rejects an output symlink resolving inside the source folder. HTML escaping, CSV formula escaping, relative snippet links and source-integrity regressions still pass. No source data was sent to the vulnerability service.

The audit tool was installed in `/private/tmp/audio-qc-audit-env`, separate from the application environment. The input was generated from its actual installed distribution names/versions, excluding only the local application package; it includes NumPy, PyYAML, PySide6 and build/test tools. It was audited with `--no-deps --disable-pip --strict` against that fully pinned list. No application dependencies were changed. This checks known Python package advisories at audit time; it does not audit FFmpeg/Homebrew libraries, prove absence of vulnerabilities, or replace decoder sandboxing.

Primary implementation references: [GitHub Python CI documentation](https://docs.github.com/en/actions/tutorials/build-and-test-code/python), [official checkout action](https://github.com/actions/checkout), [official setup-python action](https://github.com/actions/setup-python), and [PyPA pip-audit](https://github.com/pypa/pip-audit).

## Remaining limits

The workflow has been added locally but has not yet run on GitHub; hosted Linux/Python-version results are unverified until pushed. The local suite is verified on this Mac. No new native GUI visual check was performed. Logs are diagnostic artifacts, not a transaction that makes partial report sets usable after an I/O failure. Runtime sources are always opened read-only.

Parallel `--jobs` remains deferred in favor of reliability; changing concurrency also requires coordinated cancellation, bounded work scheduling and deterministic ordering tests. No measurement formula, preset default, defect threshold or M3/M4 architectural boundary changed.
