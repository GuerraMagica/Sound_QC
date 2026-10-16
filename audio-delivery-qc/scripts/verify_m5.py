"""Reproducible M5 CLI acceptance with generated, read-only-after-creation WAVs."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys

from audio_qc.programme import LAYOUTS
from audio_qc.synthetic import defect_signals, sine, write_wav


def fingerprint(paths):
    return {str(p): {"sha256": sha256(p.read_bytes()).hexdigest(), "size": p.stat().st_size,
                     "mtime_ns": p.stat().st_mtime_ns} for p in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="New directory only")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "sources"
    source.mkdir()
    signal = defect_signals()["zero_dropout"]
    for layout, name in (("stereo", "Stereo 日本語"), ("5.1", "Programme 51")):
        for role in LAYOUTS[layout]:
            samples = signal.copy()
            if role == "L":
                samples[96000:96960] = 0
                # Two clicks inside one 25fps frame, well outside the 1ms gap.
                samples[120000, 0] += 0.8
                samples[120377, 0] += 0.8
            write_wav(source/f"{name}_{role}.wav", samples, bext=True, time_reference=172800000)
    write_wav(source/"Incomplete_L.wav", signal, bext=True)
    write_wav(source/"Mismatch_L.wav", signal, bext=True, time_reference=1000)
    write_wav(source/"Mismatch_R.wav", signal, bext=True, time_reference=1001)
    write_wav(source/"Interleaved.wav", sine(channels=6), bext=True, mask=0x3f)
    paths = sorted(source.glob("*.wav"))
    before = fingerprint(paths)
    results = {}
    commands = []
    for label, options in (("grouped", ["--detect-groups"]), ("individual", [])):
        command = [sys.executable, "-m", "audio_qc", "inspect", str(source), "--export-defect-snippets",
                   "--output", str(output/label), *options]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        (output/f"{label}-console.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        assert completed.returncode in (0, 1), completed.stderr
        commands.append({"argv": command, "exit_code": completed.returncode})
        results[label] = json.loads((output/label/"QC_REPORT.json").read_text())
    grouped = results["grouped"]
    groups = grouped["programme_groups"]
    valid = [g for g in groups if g["validation_status"] == "VALID"]
    assert {g["layout"] for g in valid} == {"stereo", "5.1"}
    for group in valid:
        shared = [i for i in group["issues"] if i["sample_index"] == 48000]
        assert len(shared) == 1 and shared[0]["channels"] == list(LAYOUTS[group["layout"]])
        assert any(i["sample_index"] == 96000 and i["channels"] == ["L"] for i in group["issues"])
        clicks = [i for i in group["issues"] if 120000 <= i["sample_index"] <= 120377]
        assert len(clicks) == 2 and clicks[0]["timecode"] == clicks[1]["timecode"]
        assert group["combined_programme_loudness"] == "Not measured in M5."
    assert sorted(g["validation_status"] for g in groups) == ["INCOMPLETE", "TECHNICALLY_INCONSISTENT", "VALID", "VALID"]
    # Entire authoritative file view must be unchanged when grouping is enabled.
    assert grouped["files"] == results["individual"]["files"]
    assert fingerprint(paths) == before
    html = (output/"grouped"/"QC_REPORT.html").read_text()
    for group in groups:
        for issue in group["issues"]:
            assert html.count('data-group-issue="' + issue["id"] + '"') == 1
            for e in issue["channel_events"]:
                assert (output/"grouped"/e["snippet"]).is_file()
    evidence = {"python": sys.version, "platform": platform.platform(), "dependencies": grouped["dependencies"],
                "commands": commands, "source_integrity_unchanged": True, "file_results_identical_with_grouping": True,
                "synthetic_only": True, "groups": [{k: g[k] for k in ("name", "layout", "validation_status", "defect_coverage")}
                                                  | {"issues": len(g["issues"])} for g in groups],
                "summary": grouped["summary"], "sources": before}
    (output/"acceptance.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
