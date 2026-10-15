#!/usr/bin/env python3
"""Create a new demo directory. Existing directories are never overwritten."""
import argparse
from pathlib import Path
from audio_qc.synthetic import generate_demo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("directory", type=Path, nargs="?", default=Path("test_audio/synthetic"))
args = parser.parse_args()
print(generate_demo(args.directory).resolve())
