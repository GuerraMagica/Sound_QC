from html import escape
import json
from urllib.parse import quote
from ..signal_loss import METHOD as SIGNAL_LOSS_METHOD
from .specification import specification_rows


def esc(value):
    return escape(str(value), quote=True)


def val(value, digits=2):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return esc(value)


def badge(status):
    status = status if status in ("PASS", "WARNING", "FAIL", "INFO", "INCOMPLETE") else "INFO"
    return f'<span class="badge {status}">{status}</span>'


def tc_label(tc, day):
    return f'<span class="tc">{val(tc)}</span>' + (f' <small>(+{day}d)</small>' if day else '')


def write_html(report, path):
    from .programme_report import programme_html
    s = report["summary"]
    compliance_label = "Delivery QC (physical technical checks + programme levels)" if report.get("programme_groups") else "Audio QC"
    programme_notice = (f'<p class="notice"><b>Programme compliance: {esc(report.get("programme_compliance"))}.</b> '
                        'File PASS/FAIL counts below apply to configured physical-file checks. '
                        'Mono levels are diagnostic; programme targets are evaluated once against the virtual multichannel measurement.</p>'
                        if report.get("programme_groups") else "")
    timing = report["timecode_reporting"]
    specification = "".join(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>"
                            for label, value in specification_rows(report["configuration"]))
    source_labels = {a["timecode_reporting"]["source_label"] for a in report["files"]}
    starts = {(a["timecode_reporting"]["file_start_timecode"], a["timecode_reporting"]["file_start_day_offset"]) for a in report["files"]}
    source_label = next(iter(source_labels)) if len(source_labels) == 1 else "Mixed — see each file" if source_labels else "No audio files"
    start_label = tc_label(*next(iter(starts))) if len(starts) == 1 else "Varies by file — see file details" if starts else "—"
    timing_header = (f'<p class="timing">Frame rate: <b>{esc(timing["frame_rate"]["label"])} fps</b> &nbsp; '
                     f'TC source: <b>{esc(source_label)}</b> ({esc(timing["requested_source"])}) &nbsp; '
                     f'File start TC: {start_label}</p>')
    cards = "".join(f'<div class="card"><strong>{s[k]}</strong><span>{esc("file-level issues" if k == "defect_issues" and report.get("programme_groups") else k.replace("_", " "))}</span></div>'
                    for k in ("total_files", "PASS", "WARNING", "FAIL", "INCOMPLETE", "defect_issues"))
    rows, details, loss_rows, loss_coverage = [], [], [], []
    grouped_paths = {m["file"] for g in report.get("programme_groups", [])
                     if g["valid_for_consolidation"] for m in g["members"]}
    for index, a in enumerate(report["files"], 1):
        m, b = a["measurements"], a["bwf"]
        loss = m.get('signal_loss')
        if loss:
            loss_coverage.append(f"<li>{esc(a['filename'])}: scan {'COMPLETE' if loss['complete'] else 'INCOMPLETE'}; "
                                 f"retained evidence {'INCOMPLETE (limit reached)' if loss['truncated'] else 'complete for recorded intervals'}; "
                                 f"{loss['checked_sample_frames']} sample frames checked.</li>")
        elif report['configuration'].get('signal_loss', {}).get('enabled'):
            loss_coverage.append(f"<li>{esc(a['filename'])}: INCOMPLETE — signal-loss measurement unavailable.</li>")
        origin = a["timecode_reporting"]
        origin_line = (f'<p>TC source: <b>{esc(origin["source_label"])}</b> · File start TC: '
                       f'{tc_label(origin["file_start_timecode"], origin["file_start_day_offset"])} · '
                       f'Frame rate: {esc(origin["frame_rate"]["label"])} fps</p>')
        if origin["fallback_reason"]:
            origin_line += f'<p class="path">AUTO fallback: {esc(origin["fallback_reason"])}</p>'
        fields = [a["duration_seconds"], a["sample_rate"], a["bit_depth"], a["channels"], a["channel_layout"],
                  m.get("sample_peak_dbfs"), m.get("true_peak_dbtp"), m.get("integrated_lufs"), m.get("lra_lu"),
                  b.get("present"), b.get("time_reference")]
        rows.append(f'<tr><td>{badge(a["status"])}</td><th scope="row"><a href="#file-{index}">{esc(a["filename"])}</a></th>'
                    + "".join(f"<td>{val(v, 3)}</td>" for v in fields) + "</tr>")
        checks = "".join(f'<li>{badge(c["status"])} <b>{esc(c["code"])}</b> · {esc(c["message"])}</li>' for c in a["checks"])
        diagnostics = "".join(f'<li><b>{esc(d["code"])}</b> · {esc(d["message"])}</li>' for d in a["operational_diagnostics"])
        outcomes = "".join(f'<li>{esc(metric)}: <b>{esc(o["state"])}</b>' +
                           (f' · {esc(o["reason"])}' if o["reason"] else '') + '</li>'
                           for metric, o in a["measurement_outcomes"].items())
        checks += f'<li>Execution: <b>{esc(a["execution_status"])}</b></li>'
        checks += f'<li>Measurement outcomes<ul>{outcomes}</ul></li>'
        if diagnostics:
            checks += f'<li>Operational diagnostics (separate from audio compliance)<ul>{diagnostics}</ul></li>'
        events = []
        for e in a["defects"]:
            snippet = (f'<a href="{quote(e["snippet"], safe="/")}" target="_blank" rel="noopener">Evidence WAV</a>' if e["snippet"] else "—")
            if e['detection_method'] == SIGNAL_LOSS_METHOD:
                loss_rows.append(f"<tr><td>{badge(e['severity'])}</td><td>{esc(a['filename'])}</td>"
                                 f"<td>{esc(e['event_type'])}</td><td>{esc(', '.join(map(str, e['channels'])))}</td>"
                                 f"<td>{tc_label(e['timecode'], e['timecode_day_offset'])}</td>"
                                 f"<td>{tc_label(e.get('end_timecode_exclusive'), e.get('end_timecode_day_offset'))}</td>"
                                 f"<td>{e['duration_seconds']:.6f}</td><td>{e['sample_index']}–{e['measurements']['end_sample_exclusive']} (exclusive)</td>"
                                 f"<td>{snippet}</td></tr>")
            evidence = {"sample_index": e["sample_index"], "timestamp_seconds": e["timestamp_seconds"],
                        "timecode_basis": e["timecode_basis"], "timecode_frame_rate": e["timecode_frame_rate"],
                        "timecode_day_offset": e["timecode_day_offset"],
                        "merged_candidate_count": e["merged_candidate_count"],
                        "cluster_first_sample": e["cluster_first_sample"],
                        "cluster_last_sample": e["cluster_last_sample"], "measurements": e["measurements"],
                        "channels": e.get("channels", [e["channel"]]),
                        "channel_events": e.get("channel_events", [])}
            channels = ", ".join(str(ch) for ch in e.get("channels", [e["channel"]]))
            events.append(f'<tr><td>{badge(e["severity"])}</td><td>{esc(e["event_type"])}</td>'
                          f'<td>{tc_label(e["timecode"], e["timecode_day_offset"])}</td><td class="offset">{val(e["offset"])}</td><td>{esc(channels)}</td>'
                          f'<td>{e["duration_seconds"]*1000:.3f}</td><td>{esc(e["detection_method"])}</td><td>{snippet}</td>'
                          f'<td><details><summary>Exact samples / measurements</summary><pre>{esc(json.dumps(evidence, ensure_ascii=False, indent=2))}</pre></details></td></tr>')
        event_table = ('<h3>Defect issues</h3><div class="scroll"><table><thead><tr>'
                       '<th>Severity</th><th>Type</th><th>TC</th><th>Offset</th><th>Channels</th><th>Length (ms)</th><th>Method</th><th>Listen</th><th>Evidence</th>'
                       '</tr></thead><tbody>' + "".join(events) + '</tbody></table></div>') if events else ""
        if events and a["path"] in grouped_paths:
            event_table = '<details><summary>Original file-level issues (forensic view)</summary>' + event_table + '</details>'
        technical = {k: v for k, v in a.items() if k not in ("checks", "defects")}
        details.append(f'<article id="file-{index}"><h3>{index:03d} · {esc(a["filename"])} {badge(a["status"])}</h3>'
                       f'<p class="path">{esc(a["path"])}</p>{origin_line}<ul class="checks">{checks}</ul>{event_table}'
                       f'<details><summary>Technical metadata, measurements and hashes</summary><pre>{esc(json.dumps(technical, ensure_ascii=False, indent=2))}</pre></details></article>')
        if a["path"] in grouped_paths:
            details[-1] = (f'<details><summary>Physical file diagnostics: {esc(a["filename"])} {badge(a["status"])}</summary>'
                           + details[-1] + '</details>')
    groups = "".join(f'<li>{badge(c["status"])} <b>{esc(c["code"])}</b> · {esc(c["message"])}'
                     + (f'<details><summary>Affected files ({len(c["files"])})</summary><pre>{esc(chr(10).join(c["files"]))}</pre></details>' if c["files"] else "") + '</li>' for c in report["group_checks"])
    operational = "".join(f'<li><b>{esc(d["code"])}</b> · {esc(d["message"])}</li>' for d in report["operational_diagnostics"])
    loss_section = ('<h2>Digital signal loss / MOS (Missing of sound)</h2>'
                    '<p>Physical-file check, independent of the click candidate limit. Exact digital zero only; '
                    'intent cannot be inferred. Internal cuts and wholly silent files/channels follow the explicit failure rule. '
                    'Leading/trailing silence is informational. These rows are also retained in file evidence; do not sum the views.</p>'
                    '<ul>' + ''.join(loss_coverage) + '</ul>'
                    '<div class="scroll"><table><thead><tr><th>Severity</th><th>File</th><th>Type</th><th>Channels</th>'
                    '<th>Start TC</th><th>End TC (exclusive)</th><th>Duration (s)</th><th>Exact sample interval</th><th>Evidence</th>'
                    '</tr></thead><tbody>' + ''.join(loss_rows) + '</tbody></table></div>') if loss_coverage else ''
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; media-src 'self' file:; base-uri 'none'; form-action 'none'">
<title>Audio Delivery QC Inspector — {esc(report['scan_date'][:10])}</title>
<style>
:root{{color-scheme:light;--ink:#172c38;--muted:#576975;--line:#dce3e7}}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f6;color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{background:#162d38;color:#fff;padding:38px 5vw 30px;border-bottom:4px solid #68b6b0}}
header small{{letter-spacing:.16em;color:#b4d3d5}}h1{{font-size:28px;letter-spacing:.03em;margin:8px 0}}h2{{font-size:20px;margin-top:34px}}h3{{font-size:16px}}
main{{padding:24px 5vw 60px;max-width:1800px;margin:auto}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}
.card{{padding:18px;background:#fff;border:1px solid var(--line);border-radius:7px}}.card strong{{display:block;font-size:30px}}.card span{{color:var(--muted);font-size:12px}}
.notice{{padding:14px 18px;border-left:3px solid #68b6b0;background:#e6f0f1}}.scroll{{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:7px}}
.tc,.offset{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}}.tc{{font-size:16px;font-weight:700;white-space:nowrap;user-select:all}}.offset{{color:var(--muted)}}header .timing{{font-size:13px;line-height:2}}header .timing small{{letter-spacing:normal}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:top}}thead th{{background:#eaf0f3;color:#40545f}}tbody tr:hover{{background:#f4f8fa}}
a{{color:#126a7c;text-decoration:none}}a:hover{{text-decoration:underline}}.badge{{display:inline-block;font-size:10px;letter-spacing:.05em;font-weight:700;padding:3px 7px;border-radius:4px}}
.PASS{{background:#e1f2e9;color:#19633d}}.WARNING{{background:#fff0ce;color:#7e5100}}.INCOMPLETE{{background:#eee0ff;color:#522787}}.FAIL{{background:#fce3e3;color:#a42b2b}}.INFO{{background:#e7edf3;color:#455b6a}}
article{{margin:14px 0;padding:20px;background:#fff;border:1px solid var(--line);border-radius:7px;scroll-margin-top:15px}}
.path{{font-size:12px;color:var(--muted);overflow-wrap:anywhere}}.checks{{padding-left:0;list-style:none}}li{{margin:8px 0}}.checks li{{padding:4px 0}}
details{{margin-top:12px}}summary{{cursor:pointer;color:#126a7c}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;max-width:100%;background:#f2f5f7;padding:14px;border-radius:5px}}td pre{{min-width:230px;margin:0}}
footer{{margin-top:32px;color:var(--muted);font-size:12px}}@media(max-width:800px){{.cards{{grid-template-columns:repeat(3,1fr)}}h1{{font-size:22px}}}}@media print{{header{{color:#172c38;background:#fff}}main{{padding:10px}}.scroll{{overflow:visible}}table{{font-size:8px}}th,td{{padding:4px;white-space:normal}}article{{break-inside:avoid}}}}
</style></head><body><header><small>LOCAL TECHNICAL QUALITY CONTROL</small><h1>AUDIO DELIVERY QC INSPECTOR</h1>
<p>{compliance_label}: {badge(report['audio_compliance'])} · Execution: <b>{esc(report['execution_status'])}</b> &nbsp; {esc(report['configuration']['preset'])} · {esc(report['scan_date'])} · v{esc(report['tool_version'])}</p>{timing_header}</header>
<main>{programme_notice}<div class="cards">{cards}</div><p class="path">Source: {esc(report['source'])} · Elapsed: {report['elapsed_seconds']:.1f} s</p>
<h2>Especificación efectiva · {esc(report['configuration']['preset'])}</h2><div class="scroll"><table><tbody>{specification}</tbody></table></div>
<p class="notice">{esc(report['defect_notice'])}</p>
<p>Frame rate is a reporting setting. TC and File start TC are derived navigation labels, not timecode metadata embedded in the WAV. TC identifies the video frame containing the exact sample. Offset is file-relative (milliseconds). The authoritative sample index and full timestamp remain in Evidence and JSON. TC wraps at 24 hours; any extra days are shown separately.</p>
<p>Defect issues group same-type channel events from one source within the configured start tolerance. Length, TC and method describe the earliest channel representative; Evidence retains every channel event and the full sample extent. One Evidence WAV preserves the original multichannel context.</p>
<p>PASS: configured checks satisfied · WARNING: review required · FAIL: configured audio/technical rule violated · INCOMPLETE: required analysis could not finish; valid findings remain listed · INFO: observation. Execution and operational diagnostics are separate from compliance. Status counts describe files; defect issues count report rows. Group warnings also affect the overall status. “—” means unavailable.</p>
{loss_section}
{programme_html(report)}
<h2>Physical-file overview</h2><div class="scroll"><table><thead><tr><th>Status</th><th>File / details</th><th>Duration (s)</th><th>Rate (Hz)</th><th>Bits</th><th>Physical channels/file</th><th>Layout</th><th>Peak (dBFS)</th><th>TP (dBTP)</th><th>I (LUFS, file)</th><th>LRA (LU)</th><th>BEXT</th><th>TimeReference</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Operational diagnostics</h2><ul>{operational or "<li>No scan-level operational diagnostics.</li>"}</ul><p>{esc(report["report_delivery"])}</p>
<h2>Group consistency</h2><ul class="checks">{groups or '<li>No group inconsistencies detected.</li>'}</ul>
<h2>Physical file checks and forensic evidence</h2>{''.join(details) or '<p>No supported audio files found.</p>'}
<h2>Configuration and provenance</h2><details><summary>Configuration used</summary><pre>{esc(json.dumps(report['configuration'], ensure_ascii=False, indent=2))}</pre></details>
<details><summary>Measurement conventions and tools</summary><pre>{esc(json.dumps({'conventions': report['conventions'], 'dependencies': report['dependencies']}, indent=2))}</pre></details>
<footer>Self-contained local report. Source media opened read-only. No telemetry, remote assets or server required. True Peak is reported at 0.1 dB resolution; verify values near a delivery limit with the required reference meter. LRA is report-only.</footer>
</main></body></html>'''
    with path.open("x", encoding="utf-8") as handle:
        handle.write(html)
