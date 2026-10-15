#!/bin/zsh
qc_dir="${0:A:h}"
cd -- "$qc_dir" || exit 2
if [[ ! -x "$qc_dir/.venv/bin/python" ]]; then
  print 'First complete the installation steps in README.md.'
  read '?Press Return to close.'
  exit 2
fi
"$qc_dir/.venv/bin/python" "$qc_dir/scripts/launcher.py"
qc_result=$?
print
read '?Press Return to close.'
exit "$qc_result"
