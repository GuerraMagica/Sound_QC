# M3.1 — Defect event / issue consolidation

Completed 2026-10-08, using the current post-M3 repository, its existing Python environment and FFmpeg/ffprobe 9.0.2. No dependency added. No subsequent milestone implemented.

## Behavior and architecture

The previous production stream capped intra-channel events before cross-channel consolidation existed. `StreamingDefects` now feeds a file-scoped `IssueConsolidator` on the measurement/evidence side. It reuses the unchanged M2.1 sample interval and strongest-representative functions, then constructs operator-facing issues. QC policy receives those issues; it does not cluster, group channels, inspect signals or reinterpret their sample positions.

Terminology:

- **candidate / raw detection:** primitive `detect_window()` output.
- **channel event:** M2.1 intra-channel consolidation result; strongest finite click evidence remains the representative, with original sample, timestamp, duration, method and measurements. Dropouts remain individual channel events.
- **issue:** one operator-facing event, with sorted `channels` and all constituent `channel_events`.

Cross-channel grouping requires the **same physical source**, **same event type** and channel-event **first starts within `cross_channel_merge_ms` of the earliest start**. The canonical configuration is `defects.issues.cross_channel_merge_ms`, default **1.0 ms**, validated from 0 through 10 ms. Exact rational arithmetic converts it to an integer sample limit; 1 ms accepts 48 samples at 48 kHz or 44 samples at 44.1 kHz. Interval overlap alone never qualifies. The window remains anchored to the earliest start and cannot chain through later channels.

The first start means `cluster_first_sample`, not the potentially later strongest representative's `sample_index`. There is at most one channel event per channel in an issue. Separate same-channel events remain separate issues; when a new channel qualifies for several issues, the earliest issue wins. Each file gets independent state, so separate mono sources never group. These rules define a deterministic navigation issue, not proof of a shared physical cause.

Issues are ordered by their earliest starts. Legacy scalar `sample_index`, `timestamp_seconds`, `channel`, duration, method and measurements describe the earliest constituent channel representative (lowest channel breaks ties). Issue bounds cover the union of all channel events; `merged_candidate_count` is their total raw detection count. Each channel event preserves its own representative fields and inclusive sample bounds.

## Cap and memory

The public `defects.max_candidates` caps **issues after both consolidation stages**. Raw detections and constituent channel events cannot exhaust the cap independently.

The two stages are evaluated incrementally together. The stream retains at most the configured number of issues, each holding at most the physical source channel count of forensic representatives. Pending state contains only channel/index references and open issue indices; no raw history is retained. The existing bounded detector window remains unchanged. Long intra-channel chains update aggregate counts, sample bounds and one representative without increasing the number of retained events.

Once a genuinely additional issue exceeds the cap, retained click clusters and cross-channel start windows are allowed to finish, including across detector core boundaries. Further candidate analysis then stops while normal technical measurements continue. Filling the cap exactly without encountering another issue does not warn. Deterministic tests verify capped results equal the first K uncapped issues, including complete constituent evidence after overflow.

The pre-existing explicit zero-run policy rule remains independent of the detector cap and can add its legacy per-channel failure rows. This preserves the M3 policy boundary and contract-rule behavior; it is not a raw candidate truncation path.

## Reports, evidence and compatibility

- HTML now labels operator rows/counts as **Defect issues**, keeps prominent monospaced TC and readable Offset, displays all affected **Channels**, and exposes nested channel evidence in technical details.
- JSON schema is **3**. The existing `defects` list and scalar fields remain; detector issues add `channels` and `channel_events`. `summary.defect_issues` is the row count; `defect_candidates` remains a legacy alias. Timecode enrichment also reaches nested channel events on report copies only.
- `QC_DEFECTS.csv` has one row per issue. Existing columns retain their representative values; appended columns contain Channels, Channel Events, Merged Candidate Count, Cluster First Sample and Cluster Last Sample. The file CSV retains its legacy count column.
- Consumers that assumed one channel per defect row must read `channels` / `channel_events`. Explicit zero-run policy evidence retains its existing single-channel shape.
- One evidence WAV is exported per issue, covering the full inclusive issue extent plus configured context. It comes from the original multichannel source, preserving every source channel in order, with no downmix, channel selection or gain change. Existing 32-bit float export and metadata stripping remain. Higher precision source formats retain the previously documented float conversion limitation.
- Evidence links retain escaped relative paths, `target="_blank" rel="noopener"`, and the existing local report CSP.

## Source and architecture audit

Before edits, SHA-256 snapshots of existing source/tests/configuration/docs and all three resolved presets were saved. AST comparisons confirm that `detect_window`, `runs`, `rms` and `db` are unchanged. All policy evaluation/assessment functions are unchanged. The sole `rules.py` change projects the new technical issue configuration into measurement requirements.

M2.1 consolidation mathematics, measurement orchestration, sample analysis, loudness, BWF parsing, metadata, hashing, discovery, CLI and GUI production code remain unchanged. Resolved FILM_48K, BROADCAST_EBU_R128 and CUSTOM dictionaries match their snapshots after removing the new issue configuration. The pre-M3 golden fixture was not regenerated. Its 42 file/configuration comparisons still pass; the test strips only the new single-channel issue wrappers after verifying their forensic equivalence.

Source audio and BWF metadata are never rewritten. Integration tests verify source SHA-256, size and modification time across inspection, evidence export and reporting.

## Exact tests executed

| Stage | Command | Exact terminal result |
|---|---|---|
| Initial consolidation tests | `.venv/bin/python -m pytest -q tests/test_issues.py tests/test_consolidation.py tests/test_consolidation_reports.py` | **89 passed in 1.45s** |
| Final focused tests including evidence | `.venv/bin/python -m pytest -q tests/test_issues.py tests/test_issue_evidence.py tests/test_consolidation.py tests/test_consolidation_reports.py` | **97 passed in 2.15s** |
| Complete regression | `.venv/bin/python -m pytest -q` | **372 passed in 16.64s** |

Every command exited **0**, with **0 failures, 0 errors and 0 skips**. The previous suite had 325 tests; this milestone adds 47. The final focused run preceded the complete regression, followed by CLI smoke validation.

Coverage includes exact/inclusive cross-channel boundaries at 44.1/48/96 kHz, zero tolerance, non-transitive earliest-start grouping, long overlapping events that must remain separate, differing types, separate physical sources, same-channel event separation, representative changes, overflow followed by late constituent updates, chunk/core boundaries, cap-prefix equivalence for eight deterministic generated corpora, 30,000 raw detections retained as one bounded issue, invalid configuration, policy purity, report counts/links, all six reporting frame rates and unchanged sample/timestamp precision.

The 5.1 integration test runs with both zero and 125 ms evidence context. It verifies one issue affecting channels 1, 2 and 5, one six-channel 5.1 WAV, exact source-range coverage, and equality of every decoded exported sample in every channel to the original 24-bit source. Different tones on all six channels detect downmixing, reordering, gain changes or lost unaffected-channel context.

The full suite includes existing loudness, configuration, timecode, recursive scanning, GUI offscreen, report safety, defect benchmark and M3 policy regression coverage. A new interactive browser/playback check was not performed: local-file browser navigation was previously blocked by browser policy. HTML structure, escaping and local links were checked automatically.

## CLI smoke after the full suite

Created only a new deterministic three-second 48 kHz/24-bit 5.1 BWF fixture at `test_audio/m31-smoke/5.1 BWF issue demo.wav`, with TimeReference **172800000**. Five raw detections consolidate into four channel events and two issues. The first issue affects channels **1, 2, 5**, retaining four raw detections; the second affects channel **4**. Both displayed TCs are **01:00:01:00**, proving displayed frame equality does not merge distinct issues.

For each cap in 1 and 2, ran:

```sh
.venv/bin/audio-qc inspect 'test_audio/m31-smoke/5.1 BWF issue demo.wav' \
  --config reports/m31-smoke/cap-<cap>.yaml --frame-rate 25 --hash \
  --export-defect-snippets --output reports/m31-smoke/cap-<cap> --quiet
```

| Cap | Retained issues | Retained raw detections | Evidence WAVs | Cap warning | CLI exit / status |
|---:|---:|---:|---:|---|---|
| 1 | 1 | 4 | 1 | Yes | **0 / WARNING** |
| 2 | 2 | 5 | 2 | No | **0 / WARNING** |

All three evidence WAVs have six channels, layout 5.1, 48 kHz, float32 PCM and exact decoded sample equality to their original source ranges. JSON/CSV/HTML agree on issue counts and affected channels. Original TimeReference, SHA-256, size and modification time are unchanged. Commands, ranges, counts and fingerprints are recorded in `reports/m31-smoke/verification.json`.

## Files changed

- `src/audio_qc/issues.py` — new bounded measurement-side issue construction.
- `src/audio_qc/models.py` — issue model retaining channel events.
- `src/audio_qc/defects.py` — production streaming integration; detector algorithm unchanged.
- `src/audio_qc/config.py`, `config/default.yaml` — validated cross-channel start tolerance.
- `src/audio_qc/rules.py` — technical option projection only.
- `src/audio_qc/snippets.py` — export full issue extent once from the original source.
- `src/audio_qc/timecode.py` — report-copy enrichment of channel events.
- `src/audio_qc/reports/__init__.py`, `html_report.py`, `csv_report.py` — issue counts, channels, nested evidence and schema conventions.
- `tests/test_issues.py`, `tests/test_issue_evidence.py` — new deterministic and multichannel integration coverage.
- `tests/test_consolidation.py`, `tests/test_consolidation_reports.py` — update production issue/cap expectations; intra-channel mathematics tests retained.
- `tests/test_policy_separation.py`, `tests/test_policy_baseline.py` — new measurement module/option checks and verified additive wrapper normalization.
- `README.md`, `M31_VALIDATION.md` — behavior, compatibility and validation documentation.

Generated artifacts are confined to the new `test_audio/m31-smoke/` and `reports/m31-smoke/` folders. Earlier source fixtures, golden data, reports and archives were not rewritten.
