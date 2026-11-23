#!/usr/bin/env bash
# Makes ccd.sh (the one file people run) from ccd.sh.in and the program in ./ccd. Run after changing either.
set -euo pipefail
cd "$(dirname "$0")"
if grep -qx 'CCD_PROGRAM_END' ccd; then echo "build: the program contains the end marker" >&2; exit 1; fi
python3 -I - <<'PY'
src = open('ccd.sh.in').read()
prog = open('ccd').read().split('\n', 1)[1].rstrip('\n')  # without its first line: the installer writes its own
assert src.count('@@PROGRAM@@') == 1
open('ccd.sh', 'w').write(src.replace('@@PROGRAM@@', prog))
PY
chmod 755 ccd.sh
bash -n ccd.sh
echo "built ccd.sh ($(wc -c < ccd.sh | tr -d ' ') bytes)"
