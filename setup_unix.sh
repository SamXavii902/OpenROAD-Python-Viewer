#!/bin/bash
# ==============================================================================
# RISHI Layout Viewer - Unix/Linux Setup & Launcher (ST Enterprise Edition)
# No sudo required - Auto-detects centralized Python, Zscaler proxy & trusted pip
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================"
echo " Setting up RISHI Layout Viewer on Unix/Linux..."
echo " Directory: $SCRIPT_DIR"
echo "======================================================"

# 1. Clean host Python environment variables to avoid version conflicts
unset PYTHONPATH
unset PYTHONHOME

# 2. Auto-detect centralized Python 3.10+ (No sudo needed)
ST_PYTHON="/sw/freetools/python/3.10.4/rh80_64/bin/python3"
if [ -f "$ST_PYTHON" ]; then
    echo "[INFO] Found ST centralized Python 3.10.4: $ST_PYTHON"
    PYTHON_CMD="$ST_PYTHON"
    export LD_LIBRARY_PATH="/sw/freetools/python/3.10.4/rh80_64/lib:${LD_LIBRARY_PATH:-}"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    echo "[INFO] Using system python3: $(which python3)"
else
    PYTHON_CMD="python"
    echo "[INFO] Using system python: $(which python)"
fi

# 3. Apply standard proxy settings for ST / Enterprise network
export no_proxy="localhost,127.0.0.1,.st.com,st.com"
export NO_PROXY="localhost,127.0.0.1,.st.com,st.com"

if [ -n "$http_proxy" ]; then
    echo "[INFO] Using existing proxy: $http_proxy"
elif curl -s --connect-timeout 2 http://gateway.zscaler.net:80 &> /dev/null; then
    echo "[INFO] ST Zscaler proxy detected, configuring proxy environment..."
    export http_proxy="http://gateway.zscaler.net:80"
    export https_proxy="http://gateway.zscaler.net:80"
fi

# 4. Route all cache away from limited $HOME disk quota to local workspace
mkdir -p "$SCRIPT_DIR/.cache/pip"
mkdir -p "$SCRIPT_DIR/.cache/tmp"
export PIP_CACHE_DIR="$SCRIPT_DIR/.cache/pip"
export TMPDIR="$SCRIPT_DIR/.cache/tmp"

# 5. Headless Display Defaults for headless servers / SSH sessions without X11
if [ -z "$DISPLAY" ]; then
    echo "[WARN] No DISPLAY detected. Using headless mode (QT_QPA_PLATFORM=offscreen)."
    export QT_QPA_PLATFORM=offscreen
fi

# 6. Create virtual environment if not already present
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[INFO] Creating virtual environment with $PYTHON_CMD..."
    $PYTHON_CMD -m venv $VENV_DIR
fi

echo "[INFO] Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 7. Install dependencies using trusted hosts and Artifactory fallback
echo "[INFO] Upgrading pip with SSL trusted hosts..."
python -m pip install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org 2>/dev/null || true

echo "[INFO] Installing dependencies from requirements.txt..."
pip install -i https://pypi.org/simple --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt || \
pip install --extra-index-url https://pypi.org/simple --trusted-host artifactory.st.com --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

echo "======================================================"
echo " Setup complete! Ready to run."
echo "======================================================"

# If arguments were provided, execute run_gui.py with them; otherwise launch interactive viewer
if [ $# -gt 0 ]; then
    python run_gui.py "$@"
else
    python run_gui.py
fi
