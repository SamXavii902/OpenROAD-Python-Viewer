#!/bin/csh -f
# ==============================================================================
# RISHI Layout Viewer - High Performance LSF Compute Farm Launcher (CSH/TCSH)
# Auto-submits to LSF: bsub -q reg -P FX88_2024 -R "rusage[mem=150000]" -n 16 -Is
# ==============================================================================
set script_dir = `dirname $0`
cd "$script_dir"
set script_dir = `pwd`

# Check if direct execution is requested or already running inside LSF job
set use_bsub = 1
if ( $?LSB_JOBID || $?LSF_JOBID ) then
    set use_bsub = 0
endif

set filtered_args = ()
foreach arg ( $argv:q )
    if ( "$arg" == "--direct" || "$arg" == "--local" || "$arg" == "--no-bsub" ) then
        set use_bsub = 0
    else
        set filtered_args = ( $filtered_args:q "$arg" )
    endif
end

# Auto-dispatch to LSF cluster if bsub is present
if ( $use_bsub == 1 ) then
    which bsub >& /dev/null
    if ( $status == 0 ) then
        echo "=========================================================================="
        echo " [LSF] Submitting RISHI GUI to compute farm (16 Cores, 150 GB RAM)..."
        echo " Queue: reg | Project: FX88_2024 | Mem: 150,000 MB | Cores: 16 | Mode: -Is"
        echo " Command: bsub -q reg -P FX88_2024 -R rusage[mem=150000] -n 16 -Is"
        echo "=========================================================================="
        exec bsub -q reg -P FX88_2024 -R "rusage[mem=150000]" -n 16 -Is "$script_dir/run.csh" --direct $filtered_args:q
    endif
endif

# 1. Dynamic linker path for ST centralized Python 3.10.4
if ( -d "/sw/freetools/python/3.10.4/rh80_64/lib" ) then
    if ( $?LD_LIBRARY_PATH ) then
        setenv LD_LIBRARY_PATH /sw/freetools/python/3.10.4/rh80_64/lib:${LD_LIBRARY_PATH}
    else
        setenv LD_LIBRARY_PATH /sw/freetools/python/3.10.4/rh80_64/lib
    endif
endif

# 2. Multi-threaded performance tuning to leverage all 16 allocated cores
setenv OMP_NUM_THREADS 16
setenv MKL_NUM_THREADS 16
setenv OPENBLAS_NUM_THREADS 16
setenv NUMEXPR_NUM_THREADS 16

# 3. Modern Dark EDA UI styling
setenv QT_STYLE_OVERRIDE "Fusion"

# 4. Launch RISHI GUI
if ( -f ".venv/bin/python" ) then
    exec .venv/bin/python run_gui.py $filtered_args:q
else
    exec python3 run_gui.py $filtered_args:q
endif
