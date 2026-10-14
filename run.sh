#!/bin/bash
# ==============================================================================
# RISHI Layout Viewer - High Performance LSF Compute Farm Launcher (Bash)
# Auto-submits to LSF: bsub -q reg -P FX88_2024 -R "rusage[mem=150000]" -n 16 -Is
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if direct execution is requested or already running inside LSF job
USE_BSUB=true
FILTERED_ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--direct" ] || [ "$arg" = "--local" ] || [ "$arg" = "--no-bsub" ]; then
        USE_BSUB=false
    else
        FILTERED_ARGS+=("$arg")
    fi
done

if [ -n "$LSB_JOBID" ] || [ -n "$LSF_JOBID" ]; then
    USE_BSUB=false
fi

# Auto-dispatch to LSF cluster if bsub is present
if [ "$USE_BSUB" = true ] && command -v bsub &> /dev/null; then
    echo "=========================================================================="
    echo " [LSF] Submitting RISHI GUI to compute farm (16 Cores, 150 GB RAM)..."
    echo " Queue: reg | Project: FX88_2024 | Mem: 150,000 MB | Cores: 16 | Mode: -Is"
    echo " Command: bsub -q reg -P FX88_2024 -R \"rusage[mem=150000]\" -n 16 -Is"
    echo "=========================================================================="
    exec bsub -q reg -P FX88_2024 -R "rusage[mem=150000]" -n 16 -Is "$SCRIPT_DIR/run.sh" --direct "${FILTERED_ARGS[@]}"
fi

# 1. Dynamic linker path for ST centralized Python 3.10.4
if [ -d "/sw/freetools/python/3.10.4/rh80_64/lib" ]; then
    export LD_LIBRARY_PATH="/sw/freetools/python/3.10.4/rh80_64/lib:${LD_LIBRARY_PATH:-}"
fi

# 2. Multi-threaded performance tuning to leverage all 16 allocated cores
export OMP_NUM_THREADS=16
export MKL_NUM_THREADS=16
export OPENBLAS_NUM_THREADS=16
export NUMEXPR_NUM_THREADS=16

# 3. Modern Dark EDA UI styling
export QT_STYLE_OVERRIDE="Fusion"

# 4. Launch RISHI GUI
if [ -f ".venv/bin/python" ]; then
    exec .venv/bin/python run_gui.py "${FILTERED_ARGS[@]}"
elif command -v python3 &> /dev/null; then
    exec python3 run_gui.py "${FILTERED_ARGS[@]}"
else
    exec python run_gui.py "${FILTERED_ARGS[@]}"
fi
