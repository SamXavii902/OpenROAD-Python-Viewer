#!/bin/bash
# One-click launcher for Bash users
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d "/sw/freetools/python/3.10.4/rh80_64/lib" ]; then
    export LD_LIBRARY_PATH="/sw/freetools/python/3.10.4/rh80_64/lib:${LD_LIBRARY_PATH:-}"
fi

export QT_STYLE_OVERRIDE="Fusion"

if [ -f ".venv/bin/python" ]; then
    exec .venv/bin/python run_gui.py "$@"
else
    exec python3 run_gui.py "$@"
fi
