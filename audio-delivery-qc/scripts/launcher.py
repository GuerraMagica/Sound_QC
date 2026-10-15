"""Small Terminal launcher for Finder users; no GUI toolkit or network needed."""
from pathlib import Path
import shlex

from audio_qc.cli import main


def launch():
    print("AUDIO DELIVERY QC INSPECTOR\nSources are read-only. Reports go into a new sibling folder.\n")
    raw = input("Drag a file/folder here, or paste its path, then press Return:\n> ").strip()
    if not Path(raw).expanduser().exists():
        try:
            tokens = shlex.split(raw)
            if len(tokens) == 1:
                raw = tokens[0]
        except ValueError:
            pass
    print("\n1. Film 48 kHz (no LUFS target)\n2. Broadcast EBU R128 (-23 LUFS)\n3. Custom (technical measurements only)")
    selected = input("Preset [1]: ").strip() or "1"
    presets = {"1": "FILM_48K", "2": "BROADCAST_EBU_R128", "3": "CUSTOM"}
    if selected not in presets:
        print("Choose 1, 2 or 3 on the next run.")
        return 2
    args = ["inspect", raw, "--preset", presets[selected]]
    if input("\nDetect possible clicks/dropouts and export evidence WAVs? [y/N]: ").strip().lower() in ("y", "yes", "s", "si", "sí"):
        args.append("--export-defect-snippets")
    print()
    return main(args)


if __name__ == "__main__":
    try:
        raise SystemExit(launch())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        raise SystemExit(130)
