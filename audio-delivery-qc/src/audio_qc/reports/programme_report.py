"""Programme report views; grouping and validation happen before reporting."""
import csv
from copy import deepcopy
import json
from urllib.parse import quote

from ..timecode import parse_frame_rate, sample_frame, format_frame, format_offset, parse_start_timecode
from .csv_report import safe_cell
from .html_report import esc, badge, tc_label


def programme_timecodes(groups, settings):
    result = deepcopy(groups)
    rate = parse_frame_rate(settings["frame_rate"])
    for group in result:
        basis = "GROUP_RELATIVE"
        start = 0
        manual = 0
        if settings["source"] == "MANUAL":
            manual = parse_start_timecode(settings["manual_start"], rate)
            basis = "MANUAL"
        elif settings["source"] == "AUTO" and group["alignment_mode"] == "bwf_time_reference":
            start = group["group_origin"]
            basis = "BWF_TIMEREFERENCE"
        for issue in group["issues"]:
            frame = manual + sample_frame(start + issue["sample_index"], group["sample_rate"], rate)
            issue.update(timecode=format_frame(frame, rate), timecode_frame_rate=rate.label,
                         timecode_basis=basis, timecode_day_offset=frame // rate.frames_per_day,
                         offset=format_offset(issue["sample_index"], group["sample_rate"]))
    return result


def programme_html(report):
    groups = report.get("programme_groups", [])
    settings = report.get("programme_group_configuration")
    if not groups and settings is None:
        return ""
    configuration = ('<details><summary>Programme group definitions / naming configuration</summary><pre>' +
                     esc(json.dumps(settings, ensure_ascii=False, indent=2)) + '</pre></details>')
    if not groups:
        return '<h2>Programme groups</h2><p>No matching programme definitions found.</p>' + configuration
    sections = []
    for group in groups:
        mapping = "".join(f'<li><b>{esc(m["channel"])}</b> ← {esc(m["file"])} · physical channel 1</li>' for m in group["members"])
        reasons = "".join(f'<li>{esc(r["code"])}: {esc(r["message"])}</li>' for r in group["reasons"] + group["warnings"])
        limitations = "".join(f'<li>{esc(r)}</li>' for r in group["coverage_limitations"])
        rows = []
        for issue in group["issues"]:
            links = []
            for event in issue["channel_events"]:
                label = f'Evidence {event["logical_channel"]} — {event["source_path"]}'
                links.append(f'<a href="{quote(event["snippet"], safe="/")}" target="_blank" rel="noopener">{esc(label)}</a>'
                             if event["snippet"] else esc(label) + " (not exported)")
            rows.append(f'<tr data-group-issue="{esc(issue["id"])}"><td>{esc(issue["id"])}</td><td>{badge(issue["severity"])}</td>'
                        f'<td>{esc(issue["event_type"])}</td><td>{tc_label(issue["timecode"], issue["timecode_day_offset"])}</td>'
                        f'<td>{esc(issue["offset"])}</td><td>Channels: {esc(", ".join(issue["channels"]))}</td>'
                        f'<td>{"<br>".join(links)}</td><td><details><summary>Source events / exact samples</summary>'
                        f'<pre>{esc(json.dumps(issue, ensure_ascii=False, indent=2))}</pre></details></td></tr>')
        table = ('<div class="scroll"><table><thead><tr><th>ID</th><th>Severity</th><th>Type</th><th>TC</th><th>Group offset</th>'
                 '<th>Logical channels</th><th>Source evidence</th><th>Provenance</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
        facts = {k: v for k, v in group.items() if k not in ("issues",)}
        sections.append(f'<article><h3>{esc(group["name"])} · {esc(group["layout"])} · {esc(group["validation_status"])}</h3>'
                        f'<p>ID: {esc(group["id"])} · Alignment: {esc(group["alignment_mode"])} · '
                        f'Defect coverage: {esc(group["defect_coverage"])}</p><ul>{mapping}</ul><ul>{reasons}{limitations}</ul>'
                        '<p>Combined programme loudness: <b>Not measured in M5.</b> Combined True Peak: not measured. '
                        'Measurements and QC compliance below belong to physical files.</p>'
                        f'{table}<details><summary>Validation / coverage facts</summary><pre>{esc(json.dumps(facts, ensure_ascii=False, indent=2))}</pre></details></article>')
    return ('<h2>Programme groups</h2><p>File-level issues: ' + str(report["summary"]["file_level_issues"]) +
            ' · Group-level issues: ' + str(report["summary"]["group_level_issues"]) +
            '. These are separate views of related detections; do not add them as a unique defect total. '
            'Original file issues remain in forensic file details.</p>' + ''.join(sections) + configuration)


def write_group_csv(report, path):
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Group ID", "Group Name", "Issue ID", "Severity", "Type", "TC", "Group Offset",
                         "Channels", "Group Sample", "First Sample", "Last Sample Inclusive", "Coverage", "Source Events"])
        for group in report["programme_groups"]:
            for issue in group["issues"]:
                row = [group["id"], group["name"], issue["id"], issue["severity"], issue["event_type"],
                       issue["timecode"], issue["offset"], ", ".join(issue["channels"]), issue["sample_index"],
                       issue["cluster_first_sample"], issue["cluster_last_sample"], group["defect_coverage"],
                       json.dumps(issue["channel_events"], ensure_ascii=False, allow_nan=False)]
                writer.writerow([safe_cell(value) for value in row])
