# RISHI C++ to Python Porting Mapping

This document details the exact 1-to-1 mapping between the RISHI C++ codebase (`src/gui` and `src/odb`) and our native Python EDA viewer (`rishi`).

## 1. Database Model (`odb/`)

| RISHI C++ Source | Python Module | Key Classes & Functions Ported |
|--------------------|---------------|-------------------------------|
| `src/odb/include/odb/geom.h`, `geom.cpp` | `rishi/odb/geom.py` | `Point`, `Rect`, `Polygon` (dx, dy, area, center, intersects, intersect, merge) |
| `src/odb/include/odb/dbTypes.h` | `rishi/odb/types.py` | `dbOrientType` (R0, R90, R180, R270, MY, MYR90, MX, MXR90), `dbTechLayerType`, `dbTechLayerDir`, `dbSigType`, `dbMasterType`, `dbPlacementStatus` |
| `src/odb/include/odb/dbTransform.h`, `dbTransform.cpp` | `rishi/odb/transform.py` | `dbTransform` (apply, apply_to_point, invert) matching 2D affine reflection/rotation matrices |
| `src/odb/include/odb/db.h` (Technology) | `rishi/odb/tech.py` | `dbTech`, `dbTechLayer` (routing levels, upper/lower layer, width, pitch), `dbTechVia`, `dbSite` |
| `src/odb/include/odb/db.h` (Library & Cells) | `rishi/odb/lib.py` | `dbLib`, `dbMaster` (width, height, origin, placement boundary), `dbMTerm`, `dbMPin`, `dbBox` |
| `src/odb/include/odb/db.h` (Block & Physicals) | `rishi/odb/block.py` | `dbBlock` (dieArea, coreArea), `dbInst` (origin, orient, transform, halo), `dbNet`, `dbBTerm`, `dbBPin`, `dbRow`, `dbTrackGrid`, `dbObstruction`, `dbBlockage`, `dbFill` |
| `src/odb/include/odb/db.h` (Top-level) | `rishi/odb/database.py` | `dbDatabase`, `dbChip` |

## 2. Parsers (`lefin/` and `defin/`)

| RISHI C++ Source | Python Module | Key Features Ported |
|--------------------|---------------|---------------------|
| `src/odb/src/lefin/lefin.cpp`, `reader.cpp` | `rishi/lefin/lefin.py`, `tokenizer.py` | Streaming tokenizer, `UNITS`, `MANUFACTURINGGRID`, `LAYER`, `VIA`, `SITE`, `MACRO` (pins, ports, rects, polygons, vias, obs) |
| `src/odb/src/defin/defin*.cpp` | `rishi/defin/defin.py` | `DESIGN`, `UNITS`, `DIEAREA` (rect/polygon), `ROW`, `TRACKS`, `VIAS`, `COMPONENTS`, `PINS`, `NETS` (routed wires, via transitions, star repeats), `SPECIALNETS`, `BLOCKAGES`, `FILLS` |

## 3. GUI & Rendering Pipeline (`gui/`)

| RISHI C++ Source | Python Module | Key Functions & Logic Ported |
|--------------------|---------------|------------------------------|
| `src/gui/src/displayControls.cpp:2087-2175` | `rishi/gui/options.py`, `displayControls.py` | Exact 14-palette metal colors (`DEFAULT_METAL_COLORS`), 14-palette cut colors (`DEFAULT_CUT_COLORS`), PRNG fallback seeded with 1, alpha 180, layer & category checkboxes |
| `src/gui/src/search.cpp`, `search.h` | `rishi/gui/search.py` | `SpatialSearch` with vectorized NumPy bounding box overlap and level-of-detail size filtering (`searchInsts`, `searchBoxShapes`, `searchObstructions`, `searchBlockages`, `searchRows`) |
| `src/gui/src/painter.cpp` | `rishi/gui/painter.py` | `GuiPainter` DBU-space wrapper around `QPainter` |
| `src/gui/src/renderThread.cpp:125-259` | `rishi/gui/renderThread.py` | `RenderThread` background `QThread` rendering into `QImage(Format_ARGB32_Premultiplied)` with abort/restart semantics |
| `src/gui/src/renderThread.cpp:510-1299` | `rishi/gui/renderThread.py` | `drawChip`, `drawInstanceOutlines` (with orientation tag line), `drawInstanceShapes` (pins & obs), `drawObstructions`, `drawLayer`, `drawTracks`, `drawRows`, `drawIOPins`, `drawInstanceNames` |
| `src/gui/src/layoutViewer.cpp:258-480, 1434-1755` | `rishi/gui/layoutViewer.py` | `pixels_per_dbu`, `centering_shift`, `screenToDBU`, `dbuToScreen`, `zoom`, `fit`, `_draw_scale_bar`, per-master shape caching (`boxesByLayer`) |
| `src/gui/src/mainWindow.cpp:84-130` | `rishi/gui/mainWindow.py` | `MainWindow` with menus, left dock `DisplayControls`, central `LayoutViewer`, status bar with real-time micrometer coordinate tracker |
