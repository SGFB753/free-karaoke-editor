#!/bin/bash
# Karaoke Studio — the app window. macOS opens this file by double-click.
# Close this Terminal window to stop the program.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3 python; do
  command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
if [ -z "$PY" ]; then
  echo
  echo "  Python is not installed."
  echo "  Get it from https://python.org — or run:  brew install python"
  echo
  read -r -p "Press Enter to close…" _
  exit 1
fi

exec "$PY" app/studio.py "$@"
