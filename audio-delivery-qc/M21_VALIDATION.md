# M2.1 — Candidate consolidation and Evidence WAV links

Completed 2026-10-08 on this Apple Silicon Mac using the existing environment. Tests ran late on 2026-10-07 Europe/Madrid; the final smoke test followed after midnight. No dependencies were added.

## Root cause and implementation

Confirmed in `StreamingDefects.feed`: raw `detect_window()` results were sliced directly into the retained list, and their raw count exhausted `max_candidates`. There was no final interval consolidation across core windows. The detector itself can legitimately measure multiple opposite-edge pairs within one transient.

`consolidation.py` now supplies the shared consolidation logic, a pure `consolidate_candidates()` batch helper, and a bounded `CandidateConsolidator` used by each file's streaming detector. Raw `detect_window()`, `runs()`, `rms()` and `db()` functions are unchanged, verified against pre-change AST snapshots. Click sensitivity, click/dropout thresholds and every previous configuration default are unchanged.

- Only clicks with the same source file, channel and event type consolidate. Dropouts and other types remain separate. Each source has its own consolidator.
- Intervals are `[sample_index, sample_index + duration_samples)`. Exact measured duration samples take precedence; legacy seconds-only durations recover the nearest sample count.
- Overlap, touching, and an interval gap **≤ the configured gap** join one cluster. The default `defects.clicks.merge_gap_ms` is **1.0**, validated as a finite number from **0 to 10 ms**. The inclusive boundary is 48 gap samples at 48 kHz. Rational conversion floors fractional sample limits: 1 ms at 44.1 kHz accepts 44 samples and rejects 45.
- Connected intervals cluster transitively. Cluster extent is retained independently from the representative. Neither TC nor rounded offsets are used.
- The representative is the existing candidate with the highest finite `impulse_deviation_db`; ties or entirely unavailable scores choose the earliest sample. Its sample index, timestamp, duration, method, severity and measurements remain intact.
- `merged_candidate_count`, `cluster_first_sample` and inclusive `cluster_last_sample` are available in JSON and expanded HTML Evidence. The normal table remains compact and keeps Channel visible.
- The cap counts consolidated detector issues. Retained clusters remain open across windows until the next possible sample position is beyond their inclusive merge range. On overflow, they finish before analysis stops; discarded issues do not consume retained storage. Exactly reaching the cap without another issue does not warn. Memory retains at most the cap's representatives and one pending index per retained click channel, plus the existing bounded detector window.
- The existing snippet exporter receives this consolidated list, producing one WAV per issue without exporter changes.
- Evidence links preserve URL-escaped relative paths and add `target="_blank" rel="noopener"`. The CSP is unchanged; no JavaScript was added.

## Exact changed files

1. `src/audio_qc/consolidation.py` — new shared consolidation implementation
2. `src/audio_qc/defects.py` — streaming consolidation/cap integration only
3. `src/audio_qc/models.py` — compact cluster metadata
4. `src/audio_qc/config.py` — default and validation for merge gap
5. `src/audio_qc/samples.py` — cap warning wording only
6. `src/audio_qc/reports/html_report.py` — evidence metadata and new-tab links
7. `config/default.yaml` — explicit 1.0 ms merge gap
8. `tests/test_consolidation.py` — new focused coverage
9. `tests/test_consolidation_reports.py` — new report/snippet coverage
10. `README.md` — configuration, behavior and limitations
11. `M21_VALIDATION.md` — this validation record

Generated artifacts are separate: six `reports/m21-*.xml` JUnit files, `test_audio/m21-transients.wav`, `reports/m21-smoke-input.json`, and `reports/m21-smoke/` containing the four reports, four evidence WAVs and `verification.json`. No earlier report or source fixture was overwritten. The existing ZIP was left untouched.

## Tests, in the requested order

All commands ran from the project directory and exited **0**:

| Stage | Pytest selection | Exact terminal result |
|---|---|---|
| New consolidation | `tests/test_consolidation.py` | **48 passed in 0.21s** |
| Existing defects | `tests/test_defects.py` | **30 passed in 4.60s** |
| Reports/snippets | `tests/test_reports_cli.py tests/test_defect_csv.py tests/test_consolidation_reports.py` | **17 passed in 1.39s** |
| Timecode | `tests/test_timecode.py` | **113 passed in 1.00s** |
| Recursive scanner/rules | `tests/test_scanner_rules.py` | **13 passed in 1.89s** |
| Complete suite | all tests | **262 passed in 10.43s** |

Commands used `.venv/bin/python -m pytest <selection> -q --junitxml=reports/m21-<stage>.xml`, with `consolidation`, `defects`, `reports`, `timecode`, `scanner`, and `regression` as stage names. The full-suite command omitted `<selection>`. Every run had **0 failures, 0 errors and 0 skips**. JUnit suite timings differ slightly from terminal totals.

Coverage includes the exact supplied 2529767/2529771 geometry and scores; overlap/touching/inclusive and excessive gaps; different channels and event types; separate clicks inside one TC; finite-score selection and ties; exact duration precedence; actual audio across a core boundary at four input block sizes; cap overflow with an unfinished retained cluster; an end-of-file cluster; 10,000 raw detections stored as one representative; and configuration validation. Existing positive and negative audio fixtures remain valid. Integration checks verify consolidated HTML/JSON/CSV counts, one snippet per issue, visible channel numbers, exact evidence positions, new-tab link attributes, relative URL escaping, unchanged CSP and read-only source integrity.

## Representative smoke test

Created a new deterministic 54-second, stereo, 48 kHz, 24-bit BWF fixture with TimeReference 172800000. The unchanged raw detector, evaluated using the same PCM quantization and streaming core/padding, produced six detections:

| Raw sample | Channel | Purpose |
|---|---|---|
| 47996 | 1 | First member before a core boundary |
| 48000 | 1 | Stronger member after that boundary |
| 2529767 | 1 | Supplied reference geometry, first member |
| 2529771 | 1 | Supplied reference geometry, stronger member |
| 2529771 | 2 | Same position on a separate channel |
| 2530247 | 1 | Distinct click roughly 10 ms later, within the same video frame |

Then ran:

```sh
.venv/bin/audio-qc inspect test_audio/m21-transients.wav --frame-rate 25 --hash --export-defect-snippets --output reports/m21-smoke --quiet
```

Result: **exit 0; 1 file, 1 WARNING, 0 FAIL; 6 raw detections → 4 consolidated issues → 4 evidence WAVs**. Warnings are expected for deliberately inserted clicks.

| Representative sample | Channel | Merged count | TC | Offset |
|---|---|---|---|---|
| 48000 | 1 | 2 | 01:00:01:00 | 00:00:01.000 |
| 2529771 | 1 | 2 | 01:00:52:17 | 00:00:52.703 |
| 2529771 | 2 | 1 | 01:00:52:17 | 00:00:52.703 |
| 2530247 | 1 | 1 | 01:00:52:17 | 00:00:52.713 |

The reference cluster keeps sample **2529771** and timestamp **52.7035625**, matching the stronger existing candidate. Three distinct issues share `01:00:52:17` and remain three rows. Every retained representative's original detection fields match its raw measurement record. HTML, JSON and both CSV counts agree, and all four WAV links request new tabs safely.

Source SHA-256 remained `15c2307ecc50ae57d874203eb4c8810a3f744d53861c17b38e5f2ec4abe71555`, size 15,552,682 bytes, and modification time 1791410407763349119 ns. Timecode, BWF, loudness, scanner, rules, snippet export, metadata, CLI and GUI source files match their pre-change hashes. `verification.json` records the assertions and exact changed-file list.

## Known limitations

- Consolidation is an explicit proximity rule, not a new audibility classifier. Independent clicks within the configured interval gap can merge. Use a smaller gap when needed; zero still merges touching/overlapping intervals.
- Transitive chains can span longer than one merge gap. The representative retains its measured duration; snippet context is centered on that representative and may not cover an unusually long chain.
- Raw counts recorded for this smoke fixture are complete. When the configured cap stops analysis, no complete raw count for the remainder of a real file is available.
- Browser settings determine whether a WAV plays in a new tab/window or downloads. Link markup and CSP were verified automatically; no new browser playback review was performed because local-file browser navigation was previously blocked by browser policy.
