#!/bin/zsh
qc_dir="${0:A:h}"
cd -- "$qc_dir" || exit 2
if [[ ! -x "$qc_dir/.venv/bin/python" ]]; then
  print 'First complete the installation steps in README.md.'
  read '?Press Return to close.'
  exit 2
fi
"$qc_dir/.venv/bin/python" -m audio_qc gui
qc_result=$?
if [[ $qc_result -ne 0 ]]; then
  read '?Press Return to close.'
fi
exit "$qc_result"
