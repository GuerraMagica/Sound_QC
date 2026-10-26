import argparse
import os
from threading import Thread
from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from . import __version__
from .config import ConfigError, PRESETS, load_config
from .consistency import group_checks
from .diagnostics import RunLog
from .models import AudioFile, Check, Status, OperationalDiagnostic, overall_status
from .process import ToolError, check_tools, CancellationToken
from .reports import build_report, build_partial_report, write_reports, write_recovery
from .scanner import discover, inspect_file, FileScanCancelled
from .snippets import export_snippets
from .timecode import SOURCES
from .rules import measurement_requirements, assess_programme
from .programme_measurement import (programme_eligibility, measure_programme, ProgrammeMeasurement, source_signature)
from .programme import load_group_settings, default_group_settings, discover_programmes, build_programmes


def parser():
    root = argparse.ArgumentParser(prog="audio-qc", description="AUDIO DELIVERY QC INSPECTOR — local, read-only audio QC")
    root.add_argument("--version", action="version", version=f"audio-qc {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="Open the local desktop interface")
    inspect = commands.add_parser("inspect", help="Recursively inspect a folder, or one audio file")
    inspect.add_argument("source", type=Path, help="Source file or directory")
    inspect.add_argument("--preset", choices=PRESETS)
    inspect.add_argument("--config", type=Path, help="YAML overrides; validated before scanning")
    groups = inspect.add_mutually_exclusive_group()
    groups.add_argument("--groups", type=Path, help="Strict YAML programme definitions / naming conventions")
    groups.add_argument("--detect-groups", action="store_true", help="Opt in to exact _L/_R/.L/.R etc. programme naming")
    inspect.add_argument("--frame-rate", help='Reporting fps: 23.976, 24, 25, "29.97 NDF", "29.97 DF", 30')
    inspect.add_argument("--timecode-source", choices=SOURCES, type=str.upper, help="AUTO (default), FILE_RELATIVE or MANUAL")
    inspect.add_argument("--start-timecode", help="Manual start HH:MM:SS:FF (semicolon for DF); implies MANUAL unless source is explicitly set")
    inspect.add_argument("--gui-control-stdin", action="store_true", help=argparse.SUPPRESS)
    inspect.add_argument("--output", type=Path, help="New report directory, outside a scanned source folder")
    inspect.add_argument("--hash", action="store_true", help="SHA-256 of files and decoded audio (default off)")
    toggle = inspect.add_mutually_exclusive_group()
    toggle.add_argument("--defects", action="store_true", help="Enable deterministic click/dropout candidates")
    toggle.add_argument("--no-defects", action="store_true", help="Disable click/short-drop candidates; independent signal_loss check remains configured")
    inspect.add_argument("--export-defect-snippets", action="store_true", help="Enable defects and export evidence WAVs")
    verbosity = inspect.add_mutually_exclusive_group()
    verbosity.add_argument("--quiet", action="store_true", help="Summary and errors only (also the default)")
    verbosity.add_argument("--verbose", action="store_true", help="Show per-file measurement progress and diagnostics")
    return root


def create_output(source, requested):
    if requested:
        output = requested.expanduser().resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        output = source.parent / f"{source.stem}_QC_{stamp}"
    if source.is_dir() and (output == source or source in output.parents):
        raise ValueError("The report folder must be outside the scanned source folder. Choose a sibling folder with --output.")
    if output == source or output.exists():
        raise ValueError(f"Report destination already exists; choose a NEW folder: {output}")
    output.mkdir(parents=True, exist_ok=False)
    return output


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Also accept the short workflow: audio-qc /path/to/folder.
    if argv and argv[0] not in ("inspect", "gui") and not argv[0].startswith("-"):
        argv.insert(0, "inspect")
    args = parser().parse_args(argv)
    logs = RunLog(verbose=getattr(args, "verbose", False))
    log = logs.logger
    output = None
    report = None
    files = []
    programmes = []
    definitions = ()
    programme_settings = None
    checks = []
    cancel = CancellationToken() if getattr(args, 'gui_control_stdin', False) else None
    cancellation = {'cancel': cancel} if cancel else {}
    if cancel:
        def control():
            # Raw bounded reads avoid a daemon holding Python stdin's buffered lock at shutdown.
            pending = b''
            dropping = False
            while True:
                try:
                    data = os.read(sys.stdin.fileno(), 64)
                except OSError:
                    return
                if not data:
                    return
                for byte in data:
                    if byte == 10:
                        if not dropping and pending == b'CANCEL':
                            cancel.cancel()
                        pending, dropping = b'', False
                    elif len(pending) < 32 and not dropping:
                        pending += bytes([byte])
                    else:
                        dropping = True
        Thread(target=control, daemon=True).start()

    def recovery_snapshot():
        if report is not None:
            return deepcopy(report)
        return build_partial_report(source, files, checks, config, versions, time.monotonic()-started,
                                    programmes, programme_settings, definitions)

    def recover(error):
        if output is not None and (files or report is not None):
            try:
                write_recovery(recovery_snapshot(), output, error,
                               diagnostic_code='report_export' if report is not None else 'scan_interrupted')
                log.error("Available analysis saved as recovery data: %s", output / "QC_RECOVERY.json")
            except Exception:
                logs.console_warning("Recovery data could not be saved; report delivery failed.")

    def cancelled(error=None):
        if cancel:
            cancel.cancel()
        if output is not None and (files or report is not None):
            try:
                partial = recovery_snapshot()
                if error is not None:
                    partial['operational_diagnostics'].append(asdict(OperationalDiagnostic(
                        'concurrent_operation_error', str(error), True)))
                write_recovery(partial, output, 'Scan cancelled; partial results only', diagnostic_code='cancelled')
            except Exception:
                logs.console_warning('Cancelled scan recovery could not be saved.')
        log.warning('audio-qc: Scan cancelled; source files were opened read-only. Partial evidence may remain in the new report folder.')
        return 130

    try:
        if args.command == "gui":
            from .gui import main as gui_main
            return gui_main()
        tc_overrides = {}
        if args.frame_rate is not None:
            tc_overrides["frame_rate"] = args.frame_rate
        if args.timecode_source is not None:
            tc_overrides["source"] = args.timecode_source
            if args.timecode_source != "MANUAL":
                tc_overrides["manual_start"] = None
        if args.start_timecode is not None:
            tc_overrides["manual_start"] = args.start_timecode
            tc_overrides["source"] = args.timecode_source or "MANUAL"
        config = load_config(args.config, args.preset, tc_overrides)
        programme_settings = (load_group_settings(args.groups) if args.groups else
                              default_group_settings() if args.detect_groups else None)
        if args.no_defects and args.export_defect_snippets:
            raise ConfigError("--no-defects conflicts with --export-defect-snippets")
        if args.defects or args.export_defect_snippets:
            config["defects"]["enabled"] = True
        if args.no_defects:
            config["defects"]["enabled"] = False
        source = args.source.expanduser().absolute()
        if source.is_symlink():
            raise ValueError("Choose the real source file/folder rather than a symlink")
        source = source.resolve()
        if not source.exists() or not (source.is_file() or source.is_dir()):
            raise ValueError(f"Source is not a readable file or folder: {source}")
        versions = check_tools()
        paths, notices = discover(source)
        definitions = discover_programmes(paths, programme_settings) if programme_settings is not None else ()
        # Explicit definitions may include media outside the discovery root. Each
        # canonical source is measured exactly once, including missing members.
        if programme_settings is not None:
            # Preserve discovery order (and existing evidence numbering).
            paths = list(dict.fromkeys([p.resolve() for p in paths] +
                                       [Path(m.file) for g in definitions for m in g.members]))
        if args.output:
            destination = args.output.expanduser().resolve()
            if any(destination == p or destination in p.parents for p in paths):
                raise ValueError("Report folder must not contain programme source members")
        output = create_output(source, args.output)
        logs.attach(output)
        started = time.monotonic()
        files = []
        log.debug("AUDIO DELIVERY QC INSPECTOR %s · %s files · %s · Reports: %s",
                  __version__, len(paths), config["preset"], output)
        if not paths:
            notices.append(Check("empty_scan", Status.WARNING, "No supported audio files found in the source folder"))
        member_paths = {m.file for g in definitions for m in g.members}
        signatures = {}
        for i, path in enumerate(paths, 1):
            if cancel:
                cancel.raise_if_cancelled()
            last = [0.0, ""]

            def progress(phase, fraction):
                now = time.monotonic()
                if phase != last[1] or now-last[0] >= 2:
                    log.debug("[%s/%s] %s · %s · %.0f%%", i, len(paths), path.name, phase,
                              max(0, min(100, fraction*100)))
                    last[:] = [now, phase]

            audio = None
            try:
                try:
                    signatures[str(path)] = source_signature(path)
                except OSError:
                    pass  # Inspection records the actual unreadable-source diagnostic.
                scope = {"level_scope": "PROGRAMME_MEMBER"} if str(path) in member_paths else {}
                audio = inspect_file(path, config, args.hash, progress, **scope, **cancellation)
            except FileScanCancelled as exc:
                files.append(exc.audio)
                raise
            except Exception as exc:
                # Unexpected errors remain visible but cannot abort the delivery.
                log.error("Unexpected inspection error for %s", path, exc_info=True)
                if audio is None:
                    audio = AudioFile(str(path), path.name)
                audio.operational("unexpected_inspection_error", f"{type(exc).__name__}: {exc}",
                                  required=True, affects_analysis=True)
            files.append(audio)  # Preserve completed facts even if evidence export is cancelled.
            if args.export_defect_snippets:
                try:
                    progress("Exporting evidence", 0)
                    export_snippets(audio, output, config, i, **cancellation)
                except Exception as exc:
                    log.error("Evidence export failed for %s", path, exc_info=True)
                    audio.operational("snippet_export", f"{type(exc).__name__}: {exc}", required=True)
            log.debug("[%s/%s] %s · %s", i, len(paths), audio.status, path.name)
            for check in audio.checks:
                log.debug("%s · %s · %s · %s", path.name, check.status, check.code, check.message)
            for diagnostic in audio.operational_diagnostics:
                (log.error if diagnostic.required else log.warning)("%s · %s · %s", path.name, diagnostic.code, diagnostic.message)
            logs.warnings()
        checks = notices + group_checks(files, config)
        diagnostics = []
        for check in list(checks):
            if check.code == "directory_read":
                checks.remove(check)
                diagnostics.append(OperationalDiagnostic(check.code, check.message, required=True, affects_analysis=True))
        programmes = build_programmes(definitions, files, detection_enabled=config["defects"]["enabled"],
                                      cross_channel_merge_ms=config["defects"]["issues"]["cross_channel_merge_ms"],
                                      max_issues=config["defects"]["max_candidates"])
        requirements = measurement_requirements(config)
        for group in programmes:
            if cancel:
                cancel.raise_if_cancelled()
            eligibility = programme_eligibility(group, files, signatures)
            if not requirements.ebur128:
                measured = ProgrammeMeasurement('DISABLED')
            elif not eligibility.eligible:
                measured = ProgrammeMeasurement('NOT_EVALUATED', operational_diagnostics=[
                    OperationalDiagnostic('programme_eligibility', reason, True, True) for reason in eligibility.reasons])
            else:
                log.debug('Programme %s · virtual multichannel EBU R128 · %s', group['name'], eligibility.input.ordered_members)
                last_programme_progress = [0.0]
                def programme_progress(fraction):
                    now = time.monotonic()
                    if now - last_programme_progress[0] >= 2:
                        log.debug('Programme %s · EBU R128 · %.0f%%', group['name'], max(0, min(100, fraction*100)))
                        last_programme_progress[0] = now
                measured = measure_programme(eligibility.input, requirements, programme_progress, **cancellation)
            # Retain completed measurement even if the following assessment fails.
            group.update(programme_measurement=asdict(measured),
                         measurement_eligibility={'eligible': eligibility.eligible, 'reasons': eligibility.reasons,
                                                  'warnings': eligibility.warnings},
                         combined_programme_loudness=measured.state, combined_true_peak=measured.state)
            level_checks = assess_programme(measured, config)
            group.update(level_checks=[asdict(c) for c in level_checks],
                         programme_compliance=('NOT_EVALUATED' if measured.state in ('NOT_EVALUATED', 'DISABLED')
                                               else overall_status(level_checks).value),
                         level_scope='PROGRAMME', level_policy=deepcopy({k: config[k] for k in ('loudness', 'true_peak')}))
            for diagnostic in measured.operational_diagnostics:
                (log.error if diagnostic.required else log.warning)('Programme %s · %s', group['name'], diagnostic.message)
            log.info('Programme %s · Levels %s · %s', group['name'], group['programme_compliance'], measured.state)
            log.info("Programme %s · %s · %s · Channels: %s", group["name"], group["validation_status"],
                     group["alignment_mode"], ", ".join(m["channel"] for m in group["members"]))
            for reason in group["reasons"] + group["warnings"]:
                log.warning("Programme %s · %s · %s", group["name"], reason["code"], reason["message"])
            for limitation in group["coverage_limitations"]:
                log.warning("Programme %s · %s", group["name"], limitation)
        diagnostics.extend(OperationalDiagnostic("diagnostic_log", message) for message in logs.warnings())
        report = build_report(source, files, checks, config, versions, time.monotonic()-started, diagnostics,
                              programmes, programme_settings)
        if cancel:
            cancel.raise_if_cancelled()
        write_reports(report, output, **cancellation)
        if programmes:
            log.info("Programme compliance: %s. Mono levels are diagnostic; physical technical checks remain active.", report["programme_compliance"])
        log.info("Execution %s · Audio QC %s · %s files · %s PASS · %s WARNING · %s FAIL", report["execution_status"], report["status"], len(files),
                 report["summary"]["PASS"], report["summary"]["WARNING"], report["summary"]["FAIL"])
        log.info("HTML report: %s", output / "QC_REPORT.html")
        if report["execution_status"] in ("PARTIAL", "FAILED") or report["status"] == "INCOMPLETE":
            return 2
        return 1 if report["status"] == "FAIL" else 0
    except (ConfigError, ToolError, ValueError, OSError) as exc:
        if cancel and cancel.cancelled:
            return cancelled(exc)
        log.error("audio-qc: %s", exc, exc_info=output is not None)
        recover(exc)
        logs.warnings()
        return 2
    except KeyboardInterrupt as exc:
        # The interruption wrapped with preserved file facts is not a second error.
        return cancelled(None if isinstance(exc, FileScanCancelled) else exc.__context__)
    except Exception as exc:
        if cancel and cancel.cancelled:
            return cancelled(exc)
        log.error("❌ An unexpected error occurred.", exc_info=True)
        recover(exc)
        logs.warnings()
        if logs.error_saved():
            log.error("Check error.log for more details: %s", output / "error.log")
        else:
            log.error("Error details could not be saved (report folder unavailable or log write failed).")
        return 2
    finally:
        logs.warnings()
        logs.close()


if __name__ == "__main__":
    raise SystemExit(main())
