# AUDIO DELIVERY QC INSPECTOR

**Estado vigente y continuidad:** consulta [PROJECT_STATE.md](PROJECT_STATE.md)
para la baseline M5 aceptada, arquitectura, limitaciones y próximos hitos pendientes
de aprobación. Los documentos `*_VALIDATION.md`, auditorías y el seguimiento M5
son registros históricos; sus pruebas no se consideran reejecutadas al actualizar
documentación. Las referencias de este README a M3.1 y al hotfix describen el
alcance de esas etapas; la sección M5 recoge la extensión multiple-mono posterior.

A local, read-only technical inspector for film and TV audio deliveries: Full Mix, M&E, DIA, FX, MX, stems and printmasters. It scans a folder recursively, or one file, and creates **QC_REPORT.html**, **QC_REPORT.csv**, and **QC_REPORT.json**, plus a candidate-level **QC_DEFECTS.csv**, in a new, separate report folder.

**Sources stay untouched.** The application does not normalize, repair, rename, move, rewrite headers, change metadata or deliberately change source timestamps. Sources are opened for reading. There are no network clients, telemetry, uploads, cloud processing, AI APIs or automatic crash-report uploads. FFmpeg input protocols are restricted to local files/pipes. No internet is needed after installation.

## Start here on this Mac

The application and isolated Python environment are already installed. FFmpeg and ffprobe are available. Choose either workflow:

1. Double-click **Open QC GUI.command** in Finder. Select a file/folder, QC preset, **Frame Rate** and TC source, then Run QC. Use Open Report when finished. This is a local desktop window with no server or network processing. **Run QC.command** retains the original Terminal workflow.
2. Or paste these commands in Terminal and replace the example project and audio paths:

```sh
cd "/path/to/XQC/audio-delivery-qc"
source .venv/bin/activate
audio-qc inspect "/path/to/your/audio folder"
```

The last line gives the location of **QC_REPORT.html**. Double-click it to open the report. A ready-made example is available at `reports/validated-smoke/QC_REPORT.html`; it intentionally contains bad audio, so some FAIL results are expected.

## Installation on another Mac

Requirements: Python 3.11+, FFmpeg and ffprobe with the `ebur128` filter and true-peak support. Apple Silicon macOS is the primary platform. Core dependencies are NumPy and PyYAML. The optional desktop interface uses PySide6; pytest is needed for tests.

If necessary, install Homebrew following [brew.sh](https://brew.sh), then run:

```sh
brew install python ffmpeg
cd "/path/to/audio-delivery-qc"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,gui]"
audio-qc --version
ffmpeg -version
ffprobe -version
```

The application never installs software automatically or invokes sudo. `.venv` separates its packages from other applications. In each new Terminal window activate it with `source .venv/bin/activate`, or run `.venv/bin/audio-qc` directly. `requirements-verified.txt` records versions tested on this Mac; the normal installation command chooses dependencies compatible with your Python.

## Commands and outputs

```sh
audio-qc inspect "/Volumes/Delivery/Film"
audio-qc "/Volumes/Delivery/Film"
python -m audio_qc "/Volumes/Delivery/Film"
audio-qc inspect "/Volumes/Delivery/Full Mix.wav"
audio-qc inspect "/Volumes/Delivery/Film" --preset FILM_48K
audio-qc inspect "/Volumes/Delivery/TV" --preset BROADCAST_EBU_R128
audio-qc inspect "/Volumes/Delivery/Film" --config config/custom.yaml
audio-qc inspect "/Volumes/Delivery/Film" --hash
audio-qc inspect "/Volumes/Delivery/Film" --defects
audio-qc inspect "/Volumes/Delivery/Film" --export-defect-snippets
audio-qc inspect "/Volumes/Delivery/Film" --output "/Volumes/Reports/Film_QC_001"
audio-qc inspect "/Volumes/Delivery/Film" --frame-rate 25
audio-qc inspect "/Volumes/Delivery/Film" --frame-rate "29.97 DF" --timecode-source AUTO
audio-qc inspect "/Volumes/Delivery/Film" --frame-rate 24 --start-timecode "10:00:00:00"
audio-qc gui
audio-qc inspect --help
```

Quote paths containing spaces. `--export-defect-snippets` enables detection too. `--no-defects` overrides YAML enabling detection. `--verbose` shows per-file progress and diagnostics. Normal mode prints the summary and errors; `--quiet` explicitly selects that same concise output. The GUI requests verbose progress automatically.

A timestamped report folder is created **beside** the source by default. Report dates and folder timestamps are explicitly UTC. A custom `--output` must be a **new** directory outside the scanned source folder. Existing reports are never overwritten. Nested symbolic links are skipped and reported to avoid traversal cycles; use actual source locations.

Exit codes: **0** completed with PASS/WARNING/INFO (optional diagnostic-log warnings do not fail the run); **1** completed with acoustic/technical QC FAIL; **2** operational failure or incomplete requested analysis/evidence/report delivery; **130** cancelled. Operational failure takes precedence over a simultaneous acoustic FAIL, whose checks are preserved. An empty folder still produces the report set with WARNING and a header-only defect CSV. One corrupt file cannot abort the delivery. Ctrl-C terminates the current decoder; partial evidence may remain in the new report folder.

## Operational diagnostics

Each new report directory receives a local `scan.log` with timestamps and log levels. Unexpected failures and report-writing errors also create `error.log` with technical details. Logs rotate at 2 MiB with two backups per log. They are never uploaded by the application. Logs can include source paths and exception details; share them deliberately.

Unexpected top-level failures return exit code 2 with a concise message instead of a console traceback. If a full disk or permission problem prevents saving the log, the console explicitly says so. Errors before a new report directory is created do not write logs beside source media or into an existing report directory. A failed report write is never announced as a completed report; partial outputs may remain and should not be treated as a completed QC run. Per-file failures still permit inspection of other files, and an unexpected snippet-export failure retains the measurements already collected for that file.

YAML uses the existing strict canonical validator and safe loader. Unknown keys, duplicate keys and invalid types/values are rejected before scanning; loaded YAML validation errors now include the source path and field location where available. No second configuration schema or new runtime dependency was introduced.

Processing remains sequential. Parallel jobs are deferred until their cancellation, memory bounds, source-read-only behavior and deterministic report ordering are validated. Measurement calculations, detector thresholds and QC policy are unchanged.

## Checks and scope

- Filename, full path, size, header duration, decoded duration and sample-frame count.
- Sample rate, codec, PCM/sample representation, meaningful bit depth when available, channels and declared layout.
- Overall/per-channel sample peak, rail plateaus, float overloads and non-finite samples.
- Integrated LUFS, LRA, maximum momentary/short-term loudness and true peak where supported.
- RIFF/RF64/BW64 integrity; BEXT presence, unsigned 64-bit TimeReference, originator, originator reference, date/time, description, version and CodingHistory. Additional FFprobe tags remain in JSON/HTML.
- Readability through a complete decode, not merely a header probe.
- Group format/rate/depth differences, duration spreads/outliers, channel-count information, duplicate names, optional duplicate hashes, and possible missing stems when naming provides evidence.

Recursive extensions: WAV, WAVE, BWF, RF64, BW64, W64, AIF, AIFF, AIFC, FLAC. Actual decoding depends on the installed FFmpeg build. Mono, stereo, 5.1 and 7.1 PCM are supported. Other immersive beds receive sample analysis where decodable; object metadata and renderer-dependent loudness are outside scope.

This does not certify subjective quality, intelligibility, sync to picture, phase/polarity, channel content/order, theatrical calibration, ADM/Atmos conformance, or an entire broadcaster specification. It cannot know the intended stem list without evidence. It does not repair anything.

## Presets

| Preset | Defaults |
|---|---|
| FILM_48K | 48 kHz required; 24-bit PCM preferred; digital overload/rail plateaus fail; missing BEXT warns. **No loudness or true-peak target.** |
| BROADCAST_EBU_R128 | Film technical preferences plus −23 LUFS ±0.5 LU; maximum −1 dBTP. LRA report-only. Confirm the actual delivery specification. |
| CUSTOM | No rate/depth/channel/loudness target until configured. Integrity, measurements and clipping checks still run. |

## CUSTOM specification in the desktop GUI

Select **CUSTOM**, or choose a built-in preset and click **Copiar a CUSTOM**. Built-in settings are shown read-only; copying does not change their defaults. The Spanish editor exposes required Sample Rate, required/preferred Bit Depth, integrated Loudness (disabled, report-only, or target and tolerance), a True Peak maximum or report-only mode, BWF requirements, allowed physical channel counts, and clipping FAIL/WARNING. Blank allowed-channel counts mean unrestricted. Decimal fields accept either a comma or a period, without thousands separators.

Use **Guardar especificación…** to save the complete effective configuration as YAML with `preset: CUSTOM`; **Cargar especificación…** validates a whole file before applying it. Saves are atomic and cannot overwrite bundled preset files. Choose an existing destination directory. Invalid values or file errors appear in the status message; they are not clamped or silently replaced. Cancelling a dialog leaves the settings intact.

The exact saved file also works with the CLI:

```sh
audio-qc inspect "/path/to/audio.wav" --config "/path/to/Especificación CUSTOM.yaml"
```

GUI, YAML and CLI all use the same configuration resolver and QC policy evaluator. Run captures a private validated configuration snapshot; later edits to the original YAML cannot affect that scan. The controls and Run button are disabled until completion. JSON retains the resolved configuration in schema version **5**, and HTML displays an **Especificación efectiva** table. Defect and timecode settings remain outside the delivery editor and are retained in saved YAML. Hashing and evidence-export checkboxes remain execution options; use `--hash` and `--export-defect-snippets` for equivalent CLI runs.

True Peak is an upper limit: a maximum of −6 dBTP accepts −8 and −6, and rejects −5. Loudness −14 LUFS ±1 accepts −15 through −13 under the existing numeric tolerance. Disabling Loudness with no True Peak maximum retains the existing behavior of not scheduling that FFmpeg measurement; unavailable values remain unavailable. Clipping uses the existing criterion, and allowed channel counts refer to one physical file.

M4 preserves the shipped YAML files and preset values. Strict validation now additionally rejects unsupported bit depths (supported: 8, 16, 20, 24, 32, 64), conflicting required/preferred depths, and a tolerance without a loudness target. Previously accepted files containing those settings need correction. Explicit `target_lufs: null` removes the inherited target and, unless explicitly supplied, its inherited tolerance; other explicit null requirements remain unset. See [M4_VALIDATION.md](M4_VALIDATION.md) for test results, native GUI/CLI equivalence and source-integrity checks.

## Timeline navigation and timecode

The **Frame Rate** selector sits beside the QC preset in the GUI. It changes reporting only: the detector still operates on exact audio samples, with the same thresholds. CLI equivalents are `--frame-rate`, `--timecode-source` and `--start-timecode`. The default reporting frame rate is **25 fps**, independent of QC preset; select the rate used by your Pro Tools/Resolve timeline. BWF TimeReference itself does not supply a video frame rate.

| Reporting selection | Exact rate | Numbering |
|---|---|---|
| 23.976 | 24000/1001 | 24 nominal frame labels per second, non-drop |
| 24 | 24/1 | Non-drop |
| 25 | 25/1 | Non-drop |
| 29.97 NDF | 30000/1001 | 30 nominal frame labels per second, non-drop |
| 29.97 DF | 30000/1001 | Drop-frame, `HH:MM:SS;FF` |
| 30 | 30/1 | Non-drop |

`--frame-rate 29.97` explicitly resolves to **29.97 NDF** in the saved configuration/report. Compact `29.97DF` and `29.97NDF` spellings also work. The decimal display labels map to the exact rational rates in the table; they are never accumulated as floating-point seconds.

- **AUTO** (default): use a parsed BEXT unsigned 64-bit TimeReference, including zero. Otherwise use file-relative TC and show the fallback reason. `OriginationTime` is never used as timeline TC.
- **FILE_RELATIVE**: ignore BWF for displayed TC. First sample is `00:00:00:00` (`00:00:00;00` for DF). Original BWF values remain in the report.
- **MANUAL**: use the supplied frame label as the first sample's timeline start, for example `10:00:00:00`. Supply `--timecode-source MANUAL --start-timecode "10:00:00:00"`, or just `--start-timecode`, which implies MANUAL. For DF use `"10:00:00;00"`. Nonexistent skipped DF labels and incompatible separators are rejected before scanning.

For BWF, the conversion is `floor((TimeReference + sample_index) × fps_numerator / (sample_rate × fps_denominator))`. The sum happens **before** conversion, so subframe BWF origins are preserved. Manual TC is parsed into an exact frame count and offsets are added from audio samples. Each displayed TC identifies the video frame containing that exact sample; nothing is snapped, quantized or moved in the source or detector.

The defect table makes monospaced **TC** the primary location and shows **Offset** as `HH:MM:SS.mmm` from file start, truncated to the containing millisecond. Full `sample_index` and `timestamp_seconds` remain unchanged in JSON and under Evidence. New JSON fields include `timecode`, `timecode_frame_rate`, `timecode_basis`, `file_start_timecode`, `timecode_day_offset` and `offset`. Each file also has `timecode_reporting` with the exact rate, effective source, fallback reason and start TC. These fields were added in schema version 2 and remain in the current schema version 5 with issue consolidation and execution diagnostics; original fields are retained.

The header states frame rate, TC source and file start TC. It explicitly identifies frame rate as a reporting setting and the TC labels as derived navigation data, rather than metadata embedded in the WAV. For a mixed folder it directs the operator to each file's start/source rather than assigning one shared origin. The existing file-level CSV keeps all columns and one row per file. Conventional TC wraps at 24 hours; separate day offsets avoid losing the elapsed day count. File-relative offsets can exceed 24 hours.

**QC_DEFECTS.csv** provides one row per candidate, including TC, Offset, Frame Rate, TC Basis, file start/day offsets, original TimeReference, exact Sample Index and full-precision Timestamp Seconds, channel, duration, method, evidence WAV path and measurements. All positions come from the same canonical report data as HTML/JSON. With no candidates it contains the column headings only. The existing JSON basis identifier `BWF_TIMEREFERENCE` is retained for compatibility, alongside `FILE_RELATIVE` and `MANUAL`.

At fractional **NDF** rates the label clock differs from elapsed wall time. For example a BWF sample position at exactly 3600 seconds displays `00:59:56:12` at 29.97 NDF, while it displays `01:00:00;00` at 29.97 DF. DF skips labels `;00` and `;01` at the start of minutes not divisible by ten; it never removes samples or video frames.

Verified example: 48 kHz, TimeReference `172800000`, sample index `2529767` → **`01:00:52:17` at 25 fps**, offset `00:00:52.703`, with the original timestamp `52.70347916666667` and sample index retained. See `reports/m1-smoke/QC_REPORT.html`, `reports/m1-smoke/QC_DEFECTS.csv` and `M1_VALIDATION.md` for the latest milestone validation.

## Configuration

YAML is validated before scanning. Unknown/duplicate keys, wrong types, invalid ranges and contradictory loudness settings are rejected. `--preset` chooses the base; YAML values then override rules, including explicit `null`. Thus `--preset BROADCAST_EBU_R128 --config config/default.yaml` still clears targets because that YAML explicitly clears them. Use `ebu_r128.yaml` or a small partial override for broadcast.

```yaml
preset: FILM_48K
sample_rate:
  required: 48000
bit_depth:
  preferred: 24
  required: null                 # e.g. 24 makes a mismatch FAIL
pcm:
  preferred: true
channels:
  allowed: null                  # e.g. [1, 2, 6, 8]; other counts WARN
loudness:
  enabled: true
  target_lufs: null
  tolerance: null                # required with a numeric target
true_peak:
  maximum: null
bwf:
  required: false                # true makes absent BEXT FAIL
  warn_if_missing: true
clipping:
  fail: true
  consecutive_samples: 3
duration_tolerance_ms: 20
large_duration_difference_ms: 1000
expected_stems: []               # DIA, FX, MX, ME, FULLMIX
process_timeout_seconds: null   # per analysis/export subprocess
timecode:
  frame_rate: "25"             # quote fractional/drop-frame labels
  mode: AUTO                   # AUTO / FILE_RELATIVE / MANUAL
  manual_start: null           # e.g. "10:00:00:00" with MANUAL
defects:
  enabled: false
  max_candidates: 1000
  snippet_before_seconds: 1
  snippet_after_seconds: 1
  issues:
    cross_channel_merge_ms: 1.0  # earliest channel-event starts; 0–10 ms
  clicks:
    enabled: true
    sensitivity: medium         # low / medium / high
    min_local_deviation_db: 12
    max_duration_ms: 5
    merge_gap_ms: 1.0            # click consolidation only; 0–10 ms, inclusive gap
  dropouts:
    enabled: true
    zero_run_ms: 5
    relative_level_drop_db: 30
    min_duration_ms: 2
    max_duration_ms: 500
    fail_zero_run_ms: null       # explicit contractual rule only
```

Lower click sensitivity is more conservative. `max_candidates` counts operator-facing detector issues **after both intra-channel and cross-channel consolidation**. Raw detections and channel events do not consume separate slots. When an additional issue would exceed the cap, the detector finishes retained click clusters and open cross-channel start windows (including across core windows), then stops candidate analysis and warns; technical measurements continue. Exactly filling the cap without additional issues does not warn. The existing explicit zero-run policy rule still examines the full decoded stream and records the longest violating run per channel, independently of this detector cap. Those explicit rule findings can add report rows. This can fail intentional silence: leave it null unless explicitly required.

CLI timecode flags override YAML before validation. `--timecode-source AUTO` or `FILE_RELATIVE` clears a YAML manual start; an explicitly conflicting `--start-timecode` is rejected. The GUI can load YAML and its visible reporting controls override those settings. Timecode changes do not modify any defect settings.

`timecode.mode` and the existing `timecode.source` are equivalent YAML spellings. Use either; conflicting values are rejected before scanning. Reports retain `source` as the canonical configuration key to preserve compatibility. No new dependency is required for M1.

## Measurement and QC policy architecture

M3 preserves the existing presets, measurements and report schema while making measurement reusable. `load_config()` resolves every preset and override into the same validated policy shape. `rules.measurement_requirements()` projects it into execution inputs: the combined EBU R128/true-peak pass, optional defect detection and hashing, process timeout, and detector parameters. Sample analysis receives these execution inputs without delivery targets, clipping policy or the explicit zero-run failure threshold.

`scanner.measure_file(path, requirements)` collects an `AudioFile` and `MeasurementContext` containing zero-run facts and availability/operational state. It does not apply specification checks. Metadata, BWF parsing, sample measurements, FFmpeg EBU R128 and hashes retain their existing numerical implementations. Defect detection, intra-channel consolidation and M3.1 cross-channel issue construction all run on this measurement/evidence side. Raw candidates, channel events and unassessed issues have `severity=None`. QC policy consumes issues and assigns severity without temporal clustering, channel grouping or signal analysis.

`rules.evaluate_file_policy(audio, policy, context)` returns a fresh list of `Check` objects without audio I/O, process calls or mutation. Reuse the same measured object and context with different policies. `rules.assess_file()` creates an independent report copy, adds checks, assigns the existing WARNING candidate severity, and creates explicit zero-run failure evidence when that policy requires it. `inspect_file()` remains the complete, compatible scan-and-assess entry point, including final source-integrity checking. The existing mutating `apply_rules()` remains a compatibility adapter.

Integrated loudness uses the existing inclusive target/tolerance comparison. True peak remains an upper limit. `evaluate_level_policy(measurements, policy)` shares these rules without requiring a physical file, leaving room for future programme measurements. Existing delivery consistency checks remain in `consistency.py`; programme grouping and virtual multichannel measurement are not implemented in M3.

Re-evaluation can use only facts actually collected. Numeric measurements omitted by the execution plan retain the existing unavailable handling; evaluation does not trigger hidden remeasurement. Detector-dependent policies need the corresponding evidence, and changing detection/consolidation parameters requires a new measurement pass. CLI, GUI controls, presets, timecode navigation and source-read-only behavior are retained. See `M3_VALIDATION.md` for the architecture validation and `M31_VALIDATION.md` for issue consolidation and schema compatibility.

## Report interpretation

**PASS:** evaluated configured checks passed. **WARNING:** review needed or a metric is legitimately unavailable. **FAIL:** a configured acoustic/technical rule was violated or invalid samples were measured. **INCOMPLETE:** requested analysis could not finish; genuine FAIL findings remain in the checks. **INFO:** observation without a pass/fail requirement. Overall precedence is INCOMPLETE, FAIL, WARNING, PASS, INFO. Group warnings can raise overall status without changing file counts/statuses.

The self-contained HTML needs no server or external assets. Click filenames for all checks and expand technical details for metadata, loudness maxima and hashes. Each defect issue shows TC, offset, affected channels, representative duration/method, and expandable per-channel evidence. CSV is UTF-8 with BOM; possible spreadsheet formulas in text fields are escaped. JSON contains complete data. Unavailable metrics are **null** in JSON, blank in CSV, and **—** in HTML, never fabricated zeros. Digital silence has a separate flag.

JSON schema **5** retains the `defects` list and its scalar fields, now representing operator-facing issues. Detector issues add `channels` and `channel_events`; each nested event retains its original sample/timestamp/measurements, raw count, sample bounds and report-only TC. `summary.defect_issues` is the row count; `defect_candidates` remains a legacy alias for that count. `QC_DEFECTS.csv` has one row per issue and appends Channels, Channel Events, Merged Candidate Count and sample bounds; the existing scalar Channel/Evidence columns still describe the representative. `QC_REPORT.csv` keeps its file rows and legacy Defect Candidates count column. Explicit zero-run policy findings retain their prior single-channel shape. Schema 2 consumers that assumed one channel per row must use the new channels array.

Mixed mono/stereo/surround counts are informational unless `channels.allowed` is configured. Group duration/format differences warn because the folder may contain unrelated programmes. Default missing-stem inference requires at least two exact delimited DIA/FX/MX tokens with the same parent and name skeleton, such as `REEL01_DIA_v2.wav` and `REEL01_FX_v2.wav`. It never assumes every folder requires an M&E/full mix. Explicit `expected_stems` uses those same name groups and still warns.

## Measurement methods and limitations

**Loudness:** FFmpeg `ebur128` is used as a pass-through analyzer; LUFS is not estimated from RMS. Integrated/LRA use frame metadata. Momentary (400 ms) and short-term (3 s) maxima use 100 ms updates rather than continuous sliding maxima. Dual-mono compensation is off. Undeclared mono/stereo layouts use conventional assignments; other layouts must be explicit and supported. Unknown/object/unsupported layouts leave loudness/true peak unavailable. LFE is excluded from programme loudness by the assigned layout. Silent/below-gate material and clips shorter than 400 ms have no integrated result. LRA/short-term are unavailable below 3 s; short-programme LRA is unstable and report-only.

**True peak:** FFmpeg oversampling measures intersample peaks, with **0.1 dB** summary resolution disclosed in the report. Non-finite output stays unavailable. Limits apply to the reported value; check borderline results with the customer's reference meter and required precision. True-peak excess and sample overload are different findings.

**Clipping:** normalized float64 decoded samples are analyzed without downmixing/resampling. Float values outside ±1.0 fail. Three consecutive same-polarity full-scale samples (configurable) indicate a clipping/overload plateau; isolated rail samples warn. Historically clipped audio later reduced in level may evade this check. `s32` may be FFmpeg's representation for 24-bit PCM; meaningful depth is separate.

**BWF:** the reader seeks past audio, including BEXT following data. TimeReference is a 64-bit count of samples since midnight, not a frame-rate-specific timecode; divide by sample rate for seconds. Presence does not certify field semantics. RIFX/Wave64 BEXT, iXML, ADM and proprietary metadata are not fully interpreted. CodingHistory display is capped at 64 KiB; FFprobe metadata at 2 MiB; chunk walks at 100,000 entries, with limits disclosed. BEXT loudness fields are not substituted for current measurements.

**Hashes:** `--hash` adds file-byte SHA-256 and a second SHA-256 over rate/channel count plus interleaved float64 decoded audio. The latter identifies identical audio with different BWF metadata. Matching is exact, not perceptual; timing, channel order and representation can affect results. Hashing adds file I/O. A source size/inode/mtime change observed during analysis creates a FAIL requiring a rescan of stable material.

**Performance:** files run sequentially, normally with one streaming sample pass and one EBU R128 pass. Audio is never loaded in full. Blocks hold 8,192 frames; overlapping defect windows have a 128 MiB limit. Up to 256 channels / 768 kHz are accepted; extreme combinations can make defect analysis unavailable. Report memory grows with file/event count. Evidence export can dominate time/disk usage. Stderr is drained concurrently into a bounded diagnostic tail. The header probe times out at 60 s; optional `process_timeout_seconds` limits each decode/loudness/export subprocess, not file hashing.

## Defect candidates and evidence WAVs

> Automated defect detection identifies candidates for human QC review. It does not prove that an audible defect exists.

Clicks combine local first-derivative median absolute deviation, nearby opposite discontinuities, short duration and an isolated impulse relative to local RMS. An absolute peak alone does not trigger a click. Dropouts combine exact zero/constant runs or sudden energy collapses with active context on both sides. Correlated channels that continue are recorded as additional evidence. Energy-collapse timing has approximately 1 ms resolution; exact zeros and impulse edges have sample precision. Overlap prevents gaps at processing boundaries.

After detection, click candidates from the same file and channel are consolidated into **channel events** using exact sample intervals. Intervals that overlap, touch, or have a gap **≤ `defects.clicks.merge_gap_ms`** join one cluster; the default is **1.0 ms**, validated in the range 0–10 ms. Zero merges only overlapping/touching intervals. Fractional sample limits are rounded down (1 ms at 44.1 kHz accepts 44 gap samples, not 45). Connected intervals are clustered transitively across detector windows, with bounded retained state. This M2.1 intra-channel rule is unchanged; dropouts retain individual channel events. TC and displayed offsets play no role in merging.

Each cluster retains the original candidate with the highest finite `impulse_deviation_db`, breaking ties or missing-score cases by earliest sample index. Its exact sample, timestamp, duration, method and measurements remain together. JSON and expanded HTML Evidence include `merged_candidate_count`, `cluster_first_sample` and `cluster_last_sample` (inclusive bounds); the representative duration is not replaced with the cluster span. Very close independent clicks can meet this proximity rule; reduce the gap when that distinction matters. Several-millisecond gaps remain separate at the default setting, even inside one video frame.

M3.1 groups channel events into an **issue** only within the same physical source and `event_type`, when their first detected samples (`cluster_first_sample`) are within **`defects.issues.cross_channel_merge_ms`** of the issue's earliest start. The default is **1.0 ms**, validated at 0–10 ms and converted to an exact integer sample tolerance. Interval overlap alone does not qualify. This fixed earliest-start window does not extend through later channels. Separate mono files never group. A stronger later click can change the channel representative without changing its first start. At most one channel event per channel joins an issue; if several issues qualify, the earliest issue wins deterministically. This is an operator navigation convention, not proof of a shared physical cause.

Issues stay in earliest-start order. Their legacy scalar fields describe the earliest channel representative (lowest channel breaks ties); `merged_candidate_count` sums all underlying raw detections and issue bounds cover every channel event. Streaming retains at most `max_candidates` issues with at most the source channel count of forensic events each, plus bounded pending indices and the existing detector window. Long intra-channel chains update representatives/counts without retaining raw history. The cap never applies to raw detections, even within one detector window.

Offsets and full-precision timestamps are relative to file start; sample indices are zero-based, and channels are one-based in source order. The separate displayed TC follows the selected BWF/file-relative/manual origin. Leading/trailing silence and context-free edge events generally produce no candidates. Intentional short edits/percussion can trigger warnings; noise can conceal defects. Events beyond configured durations and subjective audibility remain limitations. Default candidates are WARNING; only an explicitly configured exact zero-run rule can fail.

`--export-defect-snippets` writes one WAV per consolidated issue in `defect_snippets/` inside the report folder: one second before the full issue's first sample and one second after its last sample, clipped to source boundaries. A 5.1 issue affecting channels 1, 2 and 5 produces one six-channel snippet, preserving original channel count/order, rate and gain without downmixing. Evidence is converted to 32-bit float (high-resolution formats may have representational rounding). It does not inherit BWF metadata. Clicking an Evidence WAV link requests a new tab/window using `target="_blank" rel="noopener"`; local relative paths and the report CSP are retained. Browser settings may instead download the WAV; use a DAW/player if the browser cannot play multichannel float WAV. See `M31_VALIDATION.md` for consolidation and evidence validation.

## Continuous integration and dependency audit

The repository-root `.github/workflows/tests.yml` runs the complete suite on pushes and pull requests, with Python 3.11 and 3.14 on Ubuntu 24.04. It installs FFmpeg/ffprobe and PySide6 and runs the GUI tests offscreen. Synthetic WAVs are generated during tests; professional source media is not uploaded. Workflow permissions are read-only, checkout credentials are not persisted, and the official checkout/setup-python actions are pinned to commit hashes.

A separate CI job checks installed dependency consistency with `pip check`, exports their exact versions with `pip list --format=freeze --exclude audio-delivery-qc`, and runs `pip-audit --strict --no-deps --disable-pip` against that list. Only the unpublished local application is excluded; all its dependencies and the audit tools remain included. This development check uses the public vulnerability service; the local QC application remains offline. Known advisories or audit-service failures fail that job instead of being suppressed. The audit does not automatically upgrade packages and is not a proof that dependencies have no vulnerabilities.

See [ROBUSTNESS_VALIDATION.md](ROBUSTNESS_VALIDATION.md) for the local tests, dependency audit, source-integrity smoke and hosted-CI limitation.

## Tests and demonstration

No copyrighted media is used. Synthetic fixtures cover mono/stereo/5.1/7.1, RF64, sample rates, depths, durations, clipped/quiet/corrupt files, Unicode paths and defects.

```sh
source .venv/bin/activate
python -m pytest -q
python scripts/generate_test_audio.py test_audio/my_new_demo
audio-qc inspect test_audio/my_new_demo --hash --export-defect-snippets --output reports/my_new_demo
```

Use new demo/output directory names. The demo intentionally exits **1** for clipped, wrong-rate and corrupt files. Tests cover parser/rule boundaries, group logic, reports, error isolation, CLI invocation, SHA/mtime preservation, evidence sample accuracy, processing boundaries, a sparse RF64 over 4 GiB, true detections and false positives. FFmpeg integration tests are explicitly skipped if tools are missing; skips do not demonstrate working end-to-end analysis.

See **VALIDATION.md** for actual results on this Mac. The small defect benchmark uses five positive signals and three negative controls; it is a regression check, not a measured false-positive rate on professional programmes.

The local PySide6 GUI is now installed in this project's virtual environment and runs through `audio-qc gui` or **Open QC GUI.command**. It delegates scans to the same CLI, keeps the window responsive, displays progress and opens the resulting local report on request. A CLI-only installation can omit the `[gui]` extra. GUI tests use Qt's offscreen platform; without PySide6 they are explicitly skipped, so install `[test,gui]` to run the complete suite.

## Technical references

- [FFmpeg ebur128 documentation](https://ffmpeg.org/ffmpeg-filters.html#ebur128)
- [EBU R 128](https://tech.ebu.ch/publications/r128)
- [EBU Tech 3285: Broadcast Wave Format](https://tech.ebu.ch/docs/tech/tech3285.pdf)
- [EBU RF64 specification](https://tech.ebu.ch/files/live/sites/tech/files/shared/tech/tech3285s6.pdf)
- [FFmpeg timecode reference, including drop-frame numbering](https://ffmpeg.org/doxygen/trunk/timecode_8c.html)

The application does not access these documentation links at runtime.


## Reliability hotfix: measurement and execution contract

Schema 4 adds `audio_compliance`, `execution_status`, `measurement_outcomes` and `operational_diagnostics`. The existing `status` remains an alias of audio compliance and now supports `INCOMPLETE`. File-level CSV appends the new fields without moving existing columns. Schema 3 consumers must accept the new enum and distinguish execution from compliance; defect/sample/timecode fields and QC thresholds are unchanged.

- Measurement outcomes: `SUCCESS`, `UNAVAILABLE` (e.g. silence/below gate/too short or unsupported channel weighting), and `ERROR` (process failure, timeout, invalid/missing required output). Disabled measurements are not scheduled and have no outcome entry.
- The requested sample pass and requested Integrated/True Peak results must complete. Loudness enabled schedules Integrated and True Peak even in report-only mode; a True Peak limit alone schedules the same EBU pass, but Integrated is not required when loudness is disabled. LRA and maxima remain report-only; no new delivery limits are introduced.
- Execution: `COMPLETED`, `COMPLETED_WITH_WARNINGS` (optional diagnostics), `PARTIAL` (required operation failed but sample results exist), or `FAILED` (no sample results, or required report export failed). An acoustic FAIL can coexist with completed execution. Incomplete analysis takes precedence in the overall compliance label; existing valid FAIL checks are never removed.
- Requested evidence is a required output operation: an export error returns 2 and marks execution partial, retaining the original measurements, forensic events and acoustic status. It does not create an acoustic defect or artificial FAIL.
- Silence remains numeric null with an `UNAVAILABLE` reason and existing QC WARNING semantics. It is not a process error. Malformed/non-finite metadata cannot reuse an earlier value to pass QC; negative-infinity logarithmic silence is distinguished from NaN/corrupt output.

A report set is delivered only when its **QC_COMPLETE.json** marker exists, created atomically after all JSON/HTML/CSV files are written. The marker confirms report delivery, not successful QC: inspect its execution/compliance fields. A lone JSON or HTML may be a partial export. On report failure the CLI returns 2, never announces report success, and attempts an additional **QC_RECOVERY.json** snapshot with execution FAILED and preserved analysis. Recovery is best effort; full disks or denied permissions can prevent it too. Existing partial files are not overwritten.

Logging failures known before report finalization appear in both JSON and HTML as operational warnings. Events after finalization (including final-summary writes or closing logs) are best-effort stderr diagnostics; completed reports remain snapshots and are not rewritten. Optional log failures never invalidate measured audio. Close/write warnings bypass file logging to avoid recursion. The GUI opens a complete partial-execution report with an explicit partial status; it rejects an unfinished report set.

Reproduce the operational acceptance scenarios using a NEW output directory:

```sh
python scripts/verify_hotfix_release.py --output /tmp/audio-qc-acceptance-NEW
```

This creates controlled 48 kHz/24-bit fixtures, asserts scenarios A–F, verifies source SHA-256/size/mtime, and emits `acceptance.json` with the actual checkout commit, tools and results. CI runs this after the full suite on both supported Python versions. An optional `--baseline-source /path/to/extracted/audio-delivery-qc/src` compares all measurement dictionaries exactly using the same runtime. See `HOTFIX_IMPLEMENTATION.md` for the implementation and validation record. No M5/M6 work is included.

## M5 — optional multiple-mono programme groups

Use `--detect-groups` to recognize exact `_L`/`_R`/`_C`/`_LFE`/`_Ls`/`_Rs`
(and period-delimited) filenames, or `--groups programme_groups.yaml` for strict
explicit definitions and custom suffixes. Stereo and 5.1 membership, PCM mono
format, exact sample counts, rates and BWF alignment are validated before
cross-file issue consolidation. Rejected groups preserve independent file QC.
The GUI offers the same options and shows mappings and validation results.

One programme issue retains all source events and labelled mono evidence links.
File/group counts are separate. **Combined programme loudness, LRA and True Peak
are not measured in M5.** See [configuration, conservative alignment rules,
report compatibility and reproducible validation](docs/PROGRAMME_GROUPS.md).

## M6 — virtual programme levels (local implementation, acceptance pending)

For eligible stereo/5.1 groups, the existing `--groups groups.yaml` or
`--detect-groups` workflow now measures Integrated LUFS, LRA and True Peak from a
virtual multichannel stream. No full-length assembled master is written.
Stereo maps L/R to FL/FR; 5.1 maps L/R/C/LFE/Ls/Rs to FL/FR/FC/LFE/SL/SR
(`5.1(side)`). LFE contributes to True Peak, not programme loudness.

M6 requires a VALID M5 group, complete mono PCM sources with identical sample rate,
exact decoded length and reliable common timing. Missing BWF requires explicit
`common_file_start`; M5's automatic no-BWF fallback does not authorize programme
measurement. Contradictory BWF origins block M6 even in common-file-start mode.
No padding, trimming, gain changes or resynchronization is applied. Member bit depths
may differ; internal format conversion is checked for sample-value preservation.

Enabled mono EBU measurements are retained as diagnostics; one additional pass
measures each eligible programme. Existing targets are evaluated once on programme
levels; mono members no longer receive programme loudness/TP target failures.
Physical technical checks and defects remain active. Invalid groups never fall
back to mono programme targets. Requested unavailable/failed programme analysis
makes the scan incomplete (exit 2); a completed acoustic failure returns 1.
Legitimately undefined loudness remains null/UNAVAILABLE and uses existing policy.
LRA remains report-only. Disabling loudness with no True Peak maximum disables the
programme EBU pass; structural groups and evidence still work.

JSON **schema 5** retains source measurements, sample/timecode/event provenance,
file/group issue lists and existing CSV columns. It adds `programme_measurement`,
`measurement_eligibility`, `level_checks`, `level_scope`, `level_policy` and scoped
`programme_compliance`. Global QC combines physical technical checks and programme
level checks; file status counts still count physical files. A level PASS does not
certify full defect coverage; caps/INCOMPLETE remain visible. Schema 4 reports and
historical validation records are not rewritten.

GUI **Cancelar QC** requests cooperative cancellation, waits for the decoder and
returns control. CLI Ctrl+C also cleans up the current process. Exit 130 is not a
completed report: there is no `QC_COMPLETE.json`; available completed facts may be
saved as `QC_RECOVERY.json`. Existing evidence is retained. GUI configuration and
group membership use the same immutable scan snapshot as before.

Reproducible synthetic acceptance (choose a new output directory):

```sh
python scripts/verify_m6.py --output /tmp/xqc-m6-NEW --memory
```

The memory check uses local process RSS on macOS/Linux and may need permission to
inspect process statistics. The runner writes only new synthetic fixtures and
reports, preserves hashes/size/mtime, and records actual operational scenarios and
reference deltas. `verify_m5.py` records M5-specific scope expectations; use M6
acceptance for the new semantics rather than treating its historical assertions
as the current release gate. See [M6 validation](docs/M6_VALIDATION.md) for results
and outstanding Linux/professional acceptance checks. No M7/M8 work is included.
