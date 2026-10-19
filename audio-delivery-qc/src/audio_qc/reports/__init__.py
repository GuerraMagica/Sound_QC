from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone

from .. import __version__
from ..models import DEFECT_NOTICE, Status, Check, overall_status, execution_status, OperationalDiagnostic
from copy import deepcopy
from ..timecode import file_timecode, parse_frame_rate
from .csv_report import write_csv, write_defects_csv
from .html_report import write_html
from .json_report import write_json
from .programme_report import programme_timecodes, write_group_csv


def build_report(source, files, group_checks, config, versions, elapsed, operational_diagnostics=(), programme_groups=(), programme_settings=None):
    operational_diagnostics = list(operational_diagnostics)
    for group in programme_groups:
        operational_diagnostics.extend(OperationalDiagnostic(**d) for d in
                                       group.get('programme_measurement', {}).get('operational_diagnostics', []))
    counts = Counter(a.status.value for a in files)
    checks = group_checks + [c for a in files for c in a.checks]
    checks += [Check(**c) for g in programme_groups for c in g.get('level_checks', [])]
    programme_statuses = [g.get('programme_compliance', 'NOT_EVALUATED') for g in programme_groups]
    evaluated = [Check('programme', Status(s), '') for s in programme_statuses if s != 'NOT_EVALUATED']
    programme_compliance = (overall_status(evaluated).value if evaluated else 'NOT_EVALUATED') if programme_groups else None
    if programme_groups and 'NOT_EVALUATED' in programme_statuses:
        programme_compliance = 'NOT_EVALUATED'
    diagnostics = list(operational_diagnostics) + [d for a in files for d in a.operational_diagnostics]
    compliance = overall_status(checks + [Check("file_status", a.status, "") for a in files])
    if any(d.affects_analysis for d in diagnostics):
        compliance = Status.INCOMPLETE
    return {
        "schema_version": 5,
        "programme_groups": programme_timecodes(programme_groups, config["timecode"]),
        "programme_group_configuration": deepcopy(programme_settings),
        "audio_compliance": compliance.value,
        "compliance_scope": "PHYSICAL_FILES_AND_PROGRAMME_LEVELS" if programme_groups else "PHYSICAL_FILES",
        "programme_compliance": programme_compliance,
        "execution_status": execution_status(diagnostics, any("decoded_sample_frames" in a.measurements for a in files), compliance == Status.INCOMPLETE).value,
        "operational_diagnostics": [asdict(d) for d in operational_diagnostics],
        "report_delivery": "Confirm all deliverables with QC_COMPLETE.json; without that marker this report set is incomplete",
        "tool": "AUDIO DELIVERY QC INSPECTOR",
        "tool_version": __version__,
        "scan_date": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "elapsed_seconds": round(elapsed, 3),
        "status": compliance.value,
        "summary": {"total_files": len(files), "total_programmes": len(programme_groups), **{s.value: counts[s.value] for s in Status},
                    "defect_candidates": sum(len(a.defects) for a in files),
                    "defect_issues": sum(len(a.defects) for a in files),
                    "file_level_issues": sum(len(a.defects) for a in files),
                    "group_level_issues": sum(len(g["issues"]) for g in programme_groups)},
        "defect_notice": DEFECT_NOTICE,
        "timecode_reporting": {"frame_rate": parse_frame_rate(config["timecode"]["frame_rate"]).as_dict(),
                               "requested_source": config["timecode"]["source"],
                               "manual_start": config["timecode"]["manual_start"]},
        "conventions": {"programme_groups": "validated multiple-mono view; exact source facts retained; virtual programme levels when eligible and enabled",
                        "programme_validation": "structural/alignment validity is separate from programme level compliance and defect coverage",
                        "group_positions": "group sample is aligned file sample; strict BWF validation requires identical origins; bounds inclusive on issues, exclusive on coverage",
                        "sample_index": "zero-based relative to decoded file start",
                        "defects": "operator-facing issues; defect_candidates is a legacy count alias for defect_issues",
                        "channel_events": "per-channel forensic events after intra-channel consolidation; raw detection counts retained",
                        "issue_representative": "earliest channel representative, then lowest channel; scalar channel/duration/measurements describe that representative",
                        "cluster_bounds": "inclusive sample bounds of all merged detections; cross-channel grouping uses earliest starts, never overlap alone",
                        "channel": "one-based source channel order",
                        "timestamp": "seconds relative to file start, not BWF timecode",
                        "timecode": "containing video frame; exact rational conversion from sample position; 24-hour wrap with separate day offset",
                        "offset": "file-relative HH:MM:SS.mmm, truncated to the containing millisecond",
                        "unavailable": "null in JSON, blank in CSV, em dash in HTML",
                        "hash": "SHA-256 file bytes and, when decoding succeeds, rate/channels + interleaved float64 PCM"},
        "configuration": config,
        "dependencies": versions,
        "group_checks": [asdict(c) for c in group_checks],
        "files": [file_timecode(a, config["timecode"]) for a in files],
    }


def write_reports(report, directory, *, cancel=None):
    write_json(report, directory / "QC_REPORT.json")
    write_csv(report, directory / "QC_REPORT.csv")
    write_html(report, directory / "QC_REPORT.html")
    write_defects_csv(report, directory / "QC_DEFECTS.csv")

    deliverables = ["QC_REPORT.json", "QC_REPORT.csv", "QC_REPORT.html", "QC_DEFECTS.csv"]
    if report.get("programme_group_configuration") is not None:
        write_group_csv(report, directory / "QC_GROUP_ISSUES.csv")
        deliverables.append("QC_GROUP_ISSUES.csv")

    if cancel:
        cancel.raise_if_cancelled()

    # A missing marker identifies interrupted/partial report delivery. Never
    # announce success merely because the first JSON or HTML file exists.
    write_json({"schema_version": report["schema_version"],
                "audio_compliance": report["audio_compliance"],
                "execution_status": report["execution_status"],
                "reports": deliverables},
               directory / ".QC_COMPLETE.json.tmp")
    (directory / ".QC_COMPLETE.json.tmp").replace(directory / "QC_COMPLETE.json")


def write_recovery(report, directory, error, *, diagnostic_code="report_export"):
    """Best effort snapshot of completed analysis when required export failed."""
    saved = deepcopy(report)
    saved["execution_status"] = "FAILED"
    saved["report_delivery"] = "FAILED; recovery data only, not a completed report set"
    saved["operational_diagnostics"].append(asdict(OperationalDiagnostic(diagnostic_code, str(error), required=True)))
    write_json(saved, directory / "QC_RECOVERY.json")
