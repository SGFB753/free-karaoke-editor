#!/bin/bash
# Drag a song and a lyrics file onto this script — or run it and answer the prompt.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3 python; do
  command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
[ -z "$PY" ] && { echo "Python is not installed — see https://python.org"; exit 1; }

"$PY" "$(dirname "$0")/tools/auto.py" "$@"
echo
read -r -p "Press Enter to close…" _
