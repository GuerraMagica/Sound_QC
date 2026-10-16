# M5 programme groups

M5 adds an optional validated relationship between independently inspected mono
PCM WAV/BWF files. It does not assemble audio or measure combined loudness, LRA
or True Peak. Individual-channel LUFS remains a **physical-file** result.

## CLI

```sh
audio-qc inspect /delivery --detect-groups --defects --output /reports/new-run
audio-qc inspect /delivery --groups /delivery/programme_groups.yaml --export-defect-snippets --output /reports/new-run
```

Grouping is opt-in, preserving ordinary CLI behaviour. `--groups` and
`--detect-groups` are mutually exclusive. The first uses a strict separate YAML
configuration; the second uses the standard filename convention. It never becomes
part of a CUSTOM delivery specification. Malformed YAML is rejected before scanning.
Explicit members outside the discovery root are inspected as well, exactly once.
Missing/unreadable media invalidates its group without aborting other inspections.

## Standard identity and roles

Case-sensitive terminal suffixes: `_L`, `_R`, `_C`, `_LFE`, `_Ls`, `_Rs`, and their
period equivalents (`.L`, `.R`, etc.), immediately before the WAV extension.
Identity is the **entire remaining stem and canonical parent directory**; no
language/mix/stem/version tokens are discarded, no fuzzy or case-folded matching.
Files in different directories never form an automatic group. Matching names
alone do not validate media or prove editorial synchronism.

Canonical logical order:

| Layout | Logical roles, in order |
| --- | --- |
| stereo | L (left), R (right) |
| 5.1 | L, R, C (centre), LFE (low-frequency effects), Ls (left surround), Rs (right surround) |

Physical channel 1 in a mono C file is **logical C**, not logical L. Both identifiers
survive in provenance. No 7.1 mapping is inferred.

`layout: auto` chooses 5.1 if any surround-only role is present, stereo otherwise.
Consequently, L/R alone cannot distinguish complete stereo from incomplete 5.1:
use an explicit layout or manifest when 5.1 is intended. A lone L is incomplete
stereo. Files such as `mix_L.wav` and `mix.L.wav` compete for L and are ambiguous.
Exact names can still encode an incorrect relationship; use explicit manifests
when naming conventions do not reliably identify the programme.

## YAML schema 1

```yaml
schema_version: 1
naming:
  enabled: true
  layout: stereo  # auto, stereo or "5.1"
  alignment: auto
  suffixes:
    L: ["-LEFT"]
    R: ["-RIGHT"]
programme_groups:
  - id: episode_108_pm_51
    name: Episode 108 Printmaster 5.1
    layout: "5.1"
    alignment:
      mode: bwf_time_reference
    members:
      - {channel: L, file: "Episode.L.wav"}
      - {channel: R, file: "Episode.R.wav"}
      - {channel: C, file: "Episode.C.wav"}
      - {channel: LFE, file: "Episode.LFE.wav"}
      - {channel: Ls, file: "Episode.Ls.wav"}
      - {channel: Rs, file: "Episode.Rs.wav"}
```

`naming` and `programme_groups` are optional; naming defaults to disabled in YAML.
Omitting `suffixes` uses the standard suffixes. A supplied suffix map replaces the
entire map and must cover the selected layout (`auto` requires all six roles).
Suffixes must begin with `_`, `.` or `-`, be unique and non-overlapping. Unknown
keys, duplicate YAML keys, unsupported layouts, invalid types, duplicate group IDs
and unsafe YAML tags are rejected. IDs starting with `naming:` are reserved.

Explicit members override automatic naming for those files. Relative paths resolve
against the manifest's directory; spaces and Unicode are preserved. Canonical
paths catch aliases. Duplicate logical assignments, physical files or membership
across multiple explicit groups produce `AMBIGUOUS` results rather than silent repair.
Explicit manifests assert programme identity even when filenames differ.

## Alignment and structural validation

All members must decode successfully as mono PCM WAV-family sources, have a common
positive sample rate and **identical exact decoded sample counts**. Different PCM
bit depths/encodings are reported as consistency warnings, not automatic invalidity.
No padding, trimming, resampling, gain changes or channel reordering occurs.

Modes:

- `auto`: all valid BWF origins → BWF mode; all BWF origins absent → common-file-start
  assumption, clearly warned. Mixed available/missing BWF timing is rejected.
- `bwf_time_reference`: every member requires a valid integer BEXT TimeReference.
  M5 conservatively requires identical origins. Differing origins are reported
  exactly and rejected; no rollover or arbitrary offset inference occurs.
- `common_file_start`: explicit assertion that all file-relative zeros coincide.
  Conflicting BWF origins are warned; the explicit mode governs alignment.

Invalid BWF references and corrupt containers cannot silently trigger fallback.
BWF group origin is the earliest TimeReference; `group_sample = TimeReference +
file_sample - group_origin`. Because valid BWF groups currently require equal
origins, group and file samples coincide. Common-start origin is zero. No
OriginationTime, displayed TC, rounded seconds or modulo arithmetic is used.
Supporting deliberately offset/edit-aligned members is outside this conservative
M5 implementation; it is not silently enabled.

Results are `VALID`, `INCOMPLETE`, `AMBIGUOUS` or `TECHNICALLY_INCONSISTENT`, with
machine-readable reason codes. Exact start/end and sample-count differences,
intersection and union coverage are retained. Coverage endpoints are exclusive;
issue interval endpoints are inclusive. A one-sample length discrepancy invalidates
alignment even below the existing human-facing delivery duration tolerance.
Existing delivery consistency checks and policy thresholds remain unchanged.
Structural validity is separate from acoustic QC compliance: invalid grouping does
not fabricate an acoustic FAIL. Each source retains canonical file-level QC results.

## Defect issues and limits

Validated groups reuse per-file channel events; no second audio decode is needed.
Grouping shares the M3.1 type/start/channel predicate: same type, different logical
channels, starts within `defects.issues.cross_channel_merge_ms` of the earliest
cluster start (inclusive, default 1 ms). The window never moves, so chaining and
interval-overlap-only merging are forbidden. Strongest representatives do not
move the anchor. Same-channel independent events remain separate. Unclassified
measurements stay unclassified; assessed severities retain the strongest constituent.

`defects.max_candidates` also bounds **consolidated group issues**, not member events.
Existing per-file bounded processing is preserved. Group memory is bounded by up
to six per-file capped issue lists plus the capped group output, never an unbounded
raw stream. Any member cap/unavailable detection or group cap marks defect coverage
incomplete. A capped group is not guaranteed to contain the globally earliest K
issues of the full media, because upstream per-file caps may have omitted events.
Disabled detection is explicitly `NOT_MEASURED`.

Source events retain exact file samples, timestamps, detector methods, measurements,
cluster bounds, raw candidate counts, physical channel, logical role, source path
and file-issue index. Raw waveforms/detection lists discarded by existing bounded
consolidation are not reconstructed. All effective thresholds remain in report
configuration and constituent measured evidence.

## Evidence, reports and GUI

Each group issue has one primary row with separate `Evidence L`, `Evidence R`, etc.
actions referencing existing mono snippets. No combined WAV or duplicate source
snippet is generated. Interleaved multichannel evidence is unchanged.

JSON remains **schema_version 4**: additions are `programme_groups`,
`programme_group_configuration`, `summary.file_level_issues`, and
`summary.group_level_issues`. Existing `files`, `defect_issues` and legacy aliases
retain their meanings. File and group counts are related views, never summed into
a unique global count. Valid grouped file issues are collapsed in HTML forensic
details; group issues form the primary consolidated view. All source file details
remain available. Programme loudness and combined True Peak are explicitly unavailable.

Existing CSV files keep their shapes. When grouping is requested,
`QC_GROUP_ISSUES.csv` adds a separate issue/provenance view and is included in the
atomic completion marker. Empty group CSVs are valid. A missing completion marker
still means incomplete report delivery, preserving the reliability hotfix.

GUI: enable **Programme groups (naming / YAML)**, or **Load groups…**. The preview
shows identities and mappings; validation outcomes appear after QC and in the
report. **Use default naming** clears loaded overrides. Group settings and absolute
member paths are copied into the worker's read-only scan snapshot. Editing a loaded
YAML or changing controls cannot alter an active scan's configuration.

## Reproduction

```sh
python -m pytest tests/test_programme.py tests/test_programme_integration.py tests/test_programme_gui.py -q
python -m pytest -q
python scripts/verify_m5.py --output /new/acceptance-directory
```

The last command creates synthetic PCM24 stereo/5.1 groups, shared and single-channel
dropouts, separate clicks inside one video frame, invalid groups and an interleaved
source. It runs real CLI scans with/without grouping, asserts identical complete
file-level results, verifies source SHA-256/size/mtime and writes `acceptance.json`
plus HTML/JSON/CSV and per-source snippets. GUI tests use offscreen Qt and real CLI
workers. M6 combined measurements are not implemented.

## Real-source follow-up: compliance scope and operator review

Reports explicitly separate `compliance_scope: PHYSICAL_FILES` from
`programme_compliance: NOT_EVALUATED` (also recorded on each programme group).
Existing file-level statuses, configured comparisons and CLI exit codes are
preserved. In particular, comparing a mono C or LFE Integrated LUFS value with a
configured file target is a **physical-channel diagnostic**, not evidence that the
assembled 5.1 programme fails that target. M5 cannot certify programme loudness.
Do not interpret structural `VALID` as a delivery PASS.

HTML presents programme issues in collapsed category tables, with counts of
**retained** issues and a prominent coverage notice. The original technical rows,
source evidence actions and exact forensic data remain accessible. JSON adds an
`issue_summary` with retained total, category/severity counts and coverage; these
are not extrapolated totals when the cap has been reached.

Two issues can share both a timecode and almost identical strongest representative
samples while their **cluster starts** differ by more than 1 ms. For example,
starts 4800077 and 4800187 at 48 kHz differ by 110 samples (2.2916667 ms). They
remain separate even if their representatives are 4800188 and 4800187. Neither
interval overlap nor a common TC changes the canonical grouping rule.

The GUI now states the effective True Peak maximum, including when a displayed
inactive value is ignored, and records the scan snapshot's maximum in the progress
log. `Canales físicos permitidos` means channels **inside each file**: normally 1
for each multiple-mono member, or 6 for a single interleaved 5.1 file. Logical L/R/C/
LFE/Ls/Rs roles are assigned and validated separately by Programme Groups.

A non-finite FFmpeg M/S/LRA observation is now an error of that auxiliary metric,
not automatically an error of a separately valid Integrated LUFS result. A maximum
with missing/invalid windows is left null, marked ERROR and reported operationally;
no numerical value is invented. Integrated/True Peak failures still retain the
hotfix's mandatory-error behaviour. Known non-finite **source samples** prevent
certification of EBU R128 measurements and remain a genuine source QC failure.

Group events retain `file_issue_severity` alongside the unchanged source channel
event. This carries an already assessed file issue into the group view when its
measurement-side channel event remains unclassified. Highest constituent severity
is preserved; fully unclassified measurement input remains unclassified.
