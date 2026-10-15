import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from . import __version__
from .config import ConfigError, PRESETS, load_config
from .consistency import group_checks
from .models import AudioFile, Check, Status
from .process import ToolError, check_tools
from .reports import build_report, write_reports
from .scanner import discover, inspect_file
from .snippets import export_snippets
from .timecode import SOURCES


def parser():
    root = argparse.ArgumentParser(prog="audio-qc", description="AUDIO DELIVERY QC INSPECTOR — local, read-only audio QC")
    root.add_argument("--version", action="version", version=f"audio-qc {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="Open the local desktop interface")
    inspect = commands.add_parser("inspect", help="Recursively inspect a folder, or one audio file")
    inspect.add_argument("source", type=Path, help="Source file or directory")
    inspect.add_argument("--preset", choices=PRESETS)
    inspect.add_argument("--config", type=Path, help="YAML overrides; validated before scanning")
    inspect.add_argument("--frame-rate", help='Reporting fps: 23.976, 24, 25, "29.97 NDF", "29.97 DF", 30')
    inspect.add_argument("--timecode-source", choices=SOURCES, type=str.upper, help="AUTO (default), FILE_RELATIVE or MANUAL")
    inspect.add_argument("--start-timecode", help="Manual start HH:MM:SS:FF (semicolon for DF); implies MANUAL unless source is explicitly set")
    inspect.add_argument("--output", type=Path, help="New report directory, outside a scanned source folder")
    inspect.add_argument("--hash", action="store_true", help="SHA-256 of files and decoded audio (default off)")
    toggle = inspect.add_mutually_exclusive_group()
    toggle.add_argument("--defects", action="store_true", help="Enable deterministic click/dropout candidates")
    toggle.add_argument("--no-defects", action="store_true", help="Disable candidate detection")
    inspect.add_argument("--export-defect-snippets", action="store_true", help="Enable defects and export evidence WAVs")
    inspect.add_argument("--quiet", action="store_true", help="Hide progress; retain summary and errors")
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
    if args.command == "gui":
        from .gui import main as gui_main
        return gui_main()
    try:
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
        output = create_output(source, args.output)
        started = time.monotonic()
        files = []
        if not args.quiet:
            print(f"AUDIO DELIVERY QC INSPECTOR {__version__}\n{len(paths)} audio file(s) · {config['preset']}\nReports: {output}", flush=True)
        if not paths:
            notices.append(Check("empty_scan", Status.WARNING, "No supported audio files found in the source folder"))
        for i, path in enumerate(paths, 1):
            last = [0.0, ""]

            def progress(phase, fraction):
                now = time.monotonic()
                if not args.quiet and (phase != last[1] or now-last[0] >= 2):
                    print(f"[{i}/{len(paths)}] {path.name} · {phase} · {max(0, min(100, fraction*100)):.0f}%", flush=True)
                    last[:] = [now, phase]

            try:
                audio = inspect_file(path, config, args.hash, progress)
                if args.export_defect_snippets:
                    progress("Exporting evidence", 0)
                    export_snippets(audio, output, config, i)
            except Exception as exc:
                # Unexpected errors remain visible but cannot abort the delivery.
                audio = AudioFile(str(path), path.name)
                audio.add("unexpected_inspection_error", Status.FAIL, f"{type(exc).__name__}: {exc}")
            files.append(audio)
            if not args.quiet:
                print(f"[{i}/{len(paths)}] {audio.status} · {path.name}", flush=True)
        checks = notices + group_checks(files, config)
        report = build_report(source, files, checks, config, versions, time.monotonic()-started)
        write_reports(report, output)
        print(f"{report['status']} · {len(files)} files · {report['summary']['PASS']} PASS · {report['summary']['WARNING']} WARNING · {report['summary']['FAIL']} FAIL")
        print(f"HTML report: {output / 'QC_REPORT.html'}")
        return 1 if report["status"] == "FAIL" else 0
    except (ConfigError, ToolError, ValueError, OSError) as exc:
        print(f"audio-qc: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\naudio-qc: Scan cancelled; source files were opened read-only. Partial evidence may remain in the new report folder.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
