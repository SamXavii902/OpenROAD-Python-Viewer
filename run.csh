#!/bin/csh -f
# One-click launcher for CSH/TCSH users
set script_dir = `dirname $0`
cd "$script_dir"

if ( -d "/sw/freetools/python/3.10.4/rh80_64/lib" ) then
    if ( $?LD_LIBRARY_PATH ) then
        setenv LD_LIBRARY_PATH /sw/freetools/python/3.10.4/rh80_64/lib:${LD_LIBRARY_PATH}
    else
        setenv LD_LIBRARY_PATH /sw/freetools/python/3.10.4/rh80_64/lib
    endif
endif

setenv QT_STYLE_OVERRIDE "Fusion"

if ( -f ".venv/bin/python" ) then
    exec .venv/bin/python run_gui.py $argv:q
else
    exec python3 run_gui.py $argv:q
endif
