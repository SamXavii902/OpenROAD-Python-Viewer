# OpenROAD Native Python EDA Layout Viewer (`openroad_py`)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![GUI Framework](https://img.shields.io/badge/GUI-PySide6%20%28Qt6%29-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](https://github.com/SamXavii902)
[![License](https://img.shields.io/badge/License-BSD--3--Clause-orange.svg)](LICENSE)

A high-performance, native Python EDA layout viewer for physical design **LEF** and **DEF** files, ported directly from the official **OpenROAD** source code (`src/gui` and `src/odb`).

Designed to run seamlessly across **Windows**, **Linux**, and **macOS** with zero C++ compilation dependencies.

---

## Key Features

* **Pure Python & Qt6 (PySide6)**: Runs out-of-the-box on corporate laptops, workstation Unix environments, and macOS without requiring native toolchains or WSL.
* **Full LEF/DEF 5.8 Compatibility**:
  * Technology LEF rules (metal routing layers, cuts/vias, pitches, default widths).
  * Standard Cell libraries & Hard Macro blocks (SRAMs, PLLs, IO pads, keepouts).
  * DEF physical layouts (die boundaries, placement rows, routing tracks, components, IO pins, special nets, routed wire paths).
* **Industrial-Grade EDA Visualizations**:
  * **Placement Density Heatmap**: 2D standard cell placement utilization overlay using the Google Turbo colormap, dynamic peak percentage statistics, and HUD gradient card.
  * **Ratsnest Flightlines**: Dynamic yellow pin-to-pin vector lines connecting selected instances/macros to all signal sinks and primary chip IOs.
  * **Interactive Measurement Ruler (`K`)**: Caliper ruler mode measuring Euclidean distances ($\mu\text{m}$), $\Delta X$, $\Delta Y$, and orthogonal caliper caps.
  * **Intelligent Fuzzy Search & Inspector (`Ctrl+F`)**: Multi-select (`Ctrl` / `Shift`) search panel with bounding-box highlights and instant camera centering.
  * **Layer & Object Display Controls**: Independent visibility and color toggles for individual routing layers, standard cells, macros, rows, blockages, and tracks.
* **C++ Grade Performance**:
  * **Multi-Threaded Rendering (`RenderThread`)**: Offloads geometry rasterization to a background worker, keeping the Qt UI fully responsive.
  * **Level-of-Detail (LoD) Adaptive Filtering**: Subpixel standard cells are culled during wide zooms, while macro blocks and boundaries remain crisp. Viewport spatial queries on 312k+ cell designs execute in **~2 ms**.
  * **Vectorized NumPy Acceleration**: Bounding-box slicing and density binning (`np.bincount`) execute in milliseconds.

---

## Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/SamXavii902/OpenROAD-Python-Viewer.git
cd OpenROAD-Python-Viewer
```

### 2. Set Up Virtual Environment

#### On Windows (PowerShell / Command Prompt):
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

#### On Linux / Unix:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note for Linux / Corporate Servers:**
> If running on a headless or minimal Linux server, ensure Qt display packages are present:
> ```bash
> sudo apt-get update && sudo apt-get install -y libgl1 libegl1 libxkbcommon-x11-0
> ```

---

## Running the Application

### 1. Launch with One-Click Design Folder
Simply pass any design directory containing LEF and DEF files:
```bash
python run_gui.py designs/gcd
python run_gui.py designs/swerv_wrapper
python run_gui.py designs/cell_on_block
```

### 2. Launch Interactive GUI
```bash
python run_gui.py
```
* **Import Folder:** Press **`Ctrl+Shift+O`** (or go to **File → Import Design Folder...**) and select any design folder. The viewer auto-discovers and orders all LEFs and DEFs automatically.
* **Sample Designs:** Go to **File → Load Sample Design** to instantly explore pre-configured benchmarks.

### 3. Command Line Arguments
```bash
# Explicit files:
python run_gui.py \
    --lef designs/Nangate45/Nangate45_tech.lef \
    --lef designs/Nangate45/Nangate45_stdcell.lef \
    --def designs/gcd/gcd_nangate45_route.def

# SweRV RISC-V with 28 SRAM Cache Macros (131k cells, 144k nets):
python run_gui.py \
    --lef designs/Nangate45/Nangate45_tech.lef \
    --lef designs/Nangate45/Nangate45_stdcell.lef \
    --lef designs/swerv_wrapper/swerv_wrapper_macro.lef \
    --def designs/swerv_wrapper/swerv_wrapper.def
```

---

## Keyboard Shortcuts

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| **`F`** | Fit Chip | Centers and auto-fits entire die within viewport |
| **`Z`** / **`Shift+Z`** | Zoom In / Out | Discrete zoom steps centered at viewport |
| **`Mouse Wheel`** | Smooth Zoom | Cursor-centered continuous zooming |
| **`Left/Middle Drag`** | Pan Viewport | Smooth canvas dragging |
| **`Ctrl+F`** | Find Object | Focuses search bar in the Inspector panel |
| **`K`** | Ruler Tool | Activates point-to-point caliper distance measurement |
| **`Shift+K`** | Clear Rulers | Removes all active measurement calipers |
| **`Ctrl+Shift+O`** | Import Folder | One-click import for directory containing LEF/DEF |
| **`Ctrl+R`** | Redraw | Forces full layer repaint |

---

## Included Benchmark Designs (`designs/`)

* **`gcd`**: Nangate 45nm arithmetic core (1,877 cells, fully routed).
* **`aes`**: AES-128 cryptography engine (18,883 cells).
* **`ibex`**: Low-power 32-bit RISC-V CPU core (29,301 cells).
* **`cell_on_block2`**: SkyWater 130nm Embedded FPGA (11,904 cells, 138 FPGA/BlockRAM macros).
* **`swerv_wrapper`**: SweRV RISC-V Core with 28 `fakeram45_2048x39` SRAM cache banks (131,271 cells).
* **`large02` (Leon3 MP)**: SparcV8 Multi-Processor SoC benchmark (312,529 cells, 406k nets).

---

## Running Automated Tests

Run the complete regression test suite:
```bash
pytest -v tests/
```
All 17 automated unit and integration tests verify:
* Coordinate geometry and orientation matrix transformations (`R0` through `MXR90`).
* LEF 5.8 parser (layer rules, vias, macro pins, and obstructions).
* DEF 5.8 parser (die area, components, special nets, routed paths).
* Multi-selection, fuzzy search indexing, and inspector properties.
* Placement density heatmap calculation and HUD legend rendering.
* Multi-threaded background canvas rendering into off-screen buffers.

---

## License

BSD 3-Clause License. See [LICENSE](LICENSE) for details. Ported from the [OpenROAD Project](https://github.com/The-OpenROAD-Project/OpenROAD).
