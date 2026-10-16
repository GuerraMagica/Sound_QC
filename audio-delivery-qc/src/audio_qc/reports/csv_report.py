import csv
import json


def safe_cell(value):
    # Filenames and BWF fields are untrusted spreadsheet input. Numeric values
    # remain numeric; text that could become a formula is explicitly quoted.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(report, path):
    columns = ["Status", "File", "Full Path", "File Size Bytes", "Duration Seconds", "Decoded Duration Seconds",
               "Sample Rate", "Codec", "PCM Format", "Bit Depth", "Channels", "Layout", "Peak dBFS", "True Peak dBTP",
               "Integrated LUFS", "LRA LU", "Max Momentary LUFS", "Max Short-term LUFS", "BWF", "TimeReference",
               "Originator", "OriginationDate", "OriginationTime", "Defect Candidates", "SHA-256", "Audio SHA-256", "Warnings", "Errors",
               "Reporting Frame Rate", "TC Source", "File Start TC", "File Start TC Day Offset", "Defect TCs", "Audio Compliance", "Execution Status", "Operational Diagnostics", "Measurement Outcomes"]
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for a in report["files"]:
            m, b = a["measurements"], a["bwf"]
            row = [a["status"], a["filename"], a["path"], a["size_bytes"], a["duration_seconds"], a["decoded_duration_seconds"],
                   a["sample_rate"], a["codec"], a["pcm_format"], a["bit_depth"], a["channels"], a["channel_layout"],
                   m.get("sample_peak_dbfs"), m.get("true_peak_dbtp"), m.get("integrated_lufs"), m.get("lra_lu"),
                   m.get("max_momentary_lufs"), m.get("max_short_term_lufs"), b.get("present"), b.get("time_reference"),
                   b.get("originator"), b.get("origination_date"), b.get("origination_time"), len(a["defects"]),
                   a["sha256"], a["audio_sha256"],
                   " | ".join(c["message"] for c in a["checks"] if c["status"] == "WARNING"),
                   " | ".join(c["message"] for c in a["checks"] if c["status"] == "FAIL"),
                   a["timecode_reporting"]["frame_rate"]["label"], a["timecode_reporting"]["source_label"],
                   a["timecode_reporting"]["file_start_timecode"], a["timecode_reporting"]["file_start_day_offset"],
                   " | ".join(f"{e['timecode']} (+{e['timecode_day_offset']}d), offset {e['offset']}, ch {','.join(map(str, e.get('channels', [e['channel']])))}, sample {e['sample_index']}" for e in a["defects"])]
            row += [a["audio_compliance"], a["execution_status"],
                    json.dumps(a["operational_diagnostics"], ensure_ascii=False),
                    json.dumps(a["measurement_outcomes"], ensure_ascii=False)]
            writer.writerow([safe_cell(v) for v in row])


def write_defects_csv(report, path):
    """One row per issue, using the same canonical fields as HTML and JSON.

    Keep QC_REPORT.csv's existing file-level rows/columns unchanged so consumers
    do not have to deduplicate files or parse packed candidate strings.
    """
    columns = ["File", "Full Path", "Severity", "Type", "TC", "Offset", "Frame Rate", "TC Basis",
               "File Start TC", "TC Day Offset", "File Start TC Day Offset", "TimeReference",
               "Sample Rate", "Sample Index", "Timestamp Seconds", "Channel", "Length (ms)",
               "Method", "Listen", "Evidence", "Channels", "Channel Events", "Merged Candidate Count",
               "Cluster First Sample", "Cluster Last Sample"]
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for audio in report["files"]:
            for event in audio["defects"]:
                row = [audio["filename"], audio["path"], event["severity"], event["event_type"],
                       event["timecode"], event["offset"], event["timecode_frame_rate"], event["timecode_basis"],
                       event["file_start_timecode"], event["timecode_day_offset"],
                       audio["timecode_reporting"]["file_start_day_offset"], audio["bwf"].get("time_reference"),
                       audio["sample_rate"], event["sample_index"], event["timestamp_seconds"], event["channel"],
                       event["duration_seconds"] * 1000, event["detection_method"], event["snippet"],
                       json.dumps(event["measurements"], ensure_ascii=False, allow_nan=False),
                       ", ".join(map(str, event.get("channels", [event["channel"]]))),
                       json.dumps(event.get("channel_events", []), ensure_ascii=False, allow_nan=False),
                       event["merged_candidate_count"], event["cluster_first_sample"], event["cluster_last_sample"]]
                writer.writerow([safe_cell(value) for value in row])
