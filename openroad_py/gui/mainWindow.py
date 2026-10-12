"""MainWindow ported from OpenROAD gui/src/mainWindow.cpp with interactive controls, legend, and folder import."""

import sys
import os
import glob
from typing import Optional, List
from PySide6.QtWidgets import (
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QLabel,
    QStatusBar,
    QApplication,
    QProgressDialog,
    QTabWidget,
    QDockWidget,
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Qt
from openroad_py.odb.database import dbDatabase
from openroad_py.odb.geom import Rect
from openroad_py.lefin import LefParser
from openroad_py.defin import DefParser
from openroad_py.gui.layoutViewer import LayoutViewer
from openroad_py.gui.displayControls import DisplayControls
from openroad_py.gui.legend import LegendDock
from openroad_py.gui.inspector import InspectorDock
from openroad_py.gui.searchWidget import SearchDock


class MainWindow(QMainWindow):
    """Main application window matching OpenROAD GUI layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenROAD Python EDA Viewer")
        self.resize(1400, 880)

        # Enable dock nesting & free customization across any area or corner
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.AnimatedDocks
            | QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.GroupedDragging
        )
        self.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        self._db = dbDatabase()
        self._lef_files: List[str] = []
        self._def_file: Optional[str] = None

        # Center viewer
        self._viewer = LayoutViewer(self)
        self.setCentralWidget(self._viewer)

        # Left dock: DisplayControls (Layers & Display toggles)
        self._controls = DisplayControls(self._viewer, self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._controls)

        # Right dock: Search (Similarity fuzzy search & quick-jump)
        self._search_dock = SearchDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._search_dock)

        # Right dock: Inspector (Design hierarchy & metrics)
        self._inspector = InspectorDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._inspector)

        # Right dock: Legend (Layout representation guide with color wheels)
        self._legend = LegendDock(self._viewer, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._legend)

        self.tabifyDockWidget(self._search_dock, self._inspector)
        self.tabifyDockWidget(self._inspector, self._legend)
        self._inspector.raise_()

        self._controls.option_toggled.connect(self._on_display_control_option_toggled)
        self._inspector.macro_selected.connect(self._on_macro_selected)
        self._search_dock.object_selected.connect(self._on_search_object_selected)
        self._search_dock.objects_selected.connect(self._on_search_objects_selected)
        self._viewer.instance_selected.connect(self._on_instance_selected)
        self._viewer.ruler_measured.connect(self._on_ruler_measured)
        self._viewer.ruler_mode_changed.connect(self._on_ruler_mode_changed)

        # Status Bar
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)

        self._coords_label = QLabel("X: 0.000 µm  Y: 0.000 µm")
        self._coords_label.setStyleSheet("padding: 0 10px; font-weight: bold;")
        self._status_bar.addPermanentWidget(self._coords_label)

        self._info_label = QLabel("No design loaded")
        self._status_bar.addWidget(self._info_label)

        self._viewer.cursor_moved.connect(self._on_cursor_moved)

        self._create_menus()

    def _create_menus(self) -> None:
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&File")

        import_dir_act = QAction("&Import Design Folder...", self)
        import_dir_act.setShortcut(QKeySequence("Ctrl+Shift+O"))
        import_dir_act.setStatusTip("Select a folder containing LEF and DEF files to load in one click")
        import_dir_act.triggered.connect(self._import_folder_dialog)
        file_menu.addAction(import_dir_act)

        file_menu.addSeparator()

        open_lef_act = QAction("&Open LEF...", self)
        open_lef_act.setShortcut(QKeySequence("Ctrl+L"))
        open_lef_act.triggered.connect(self._open_lef_dialog)
        file_menu.addAction(open_lef_act)

        open_def_act = QAction("&Open DEF...", self)
        open_def_act.setShortcut(QKeySequence("Ctrl+O"))
        open_def_act.triggered.connect(self._open_def_dialog)
        file_menu.addAction(open_def_act)

        export_img_act = QAction("&Export Layout Image...", self)
        export_img_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        export_img_act.setStatusTip("Export current layout view as high-resolution PNG image")
        export_img_act.triggered.connect(self._export_layout_image)
        file_menu.addAction(export_img_act)

        # Sample Designs Submenu
        samples_menu = file_menu.addMenu("&Load Sample Design")
        self._add_sample_actions(samples_menu)

        file_menu.addSeparator()

        exit_act = QAction("E&xit", self)
        exit_act.setShortcut(QKeySequence("Ctrl+Q"))
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # View Menu
        view_menu = menubar.addMenu("&View")

        fit_act = QAction("&Fit Chip", self)
        fit_act.setShortcut(QKeySequence("F"))
        fit_act.triggered.connect(self._viewer.fit)
        view_menu.addAction(fit_act)

        zoom_in_act = QAction("Zoom &In", self)
        zoom_in_act.setShortcut(QKeySequence("Z"))
        zoom_in_act.triggered.connect(self._viewer.zoomIn)
        view_menu.addAction(zoom_in_act)

        zoom_out_act = QAction("Zoom &Out", self)
        zoom_out_act.setShortcut(QKeySequence("Shift+Z"))
        zoom_out_act.triggered.connect(self._viewer.zoomOut)
        view_menu.addAction(zoom_out_act)

        redraw_act = QAction("&Redraw", self)
        redraw_act.setShortcut(QKeySequence("Ctrl+R"))
        redraw_act.triggered.connect(self._viewer.fullRepaint)
        view_menu.addAction(redraw_act)

        view_menu.addSeparator()

        self._heatmap_act = QAction("Placement Density &Heatmap", self)
        self._heatmap_act.setCheckable(True)
        self._heatmap_act.setChecked(False)
        self._heatmap_act.setStatusTip("Toggle placement density congestion heatmap overlay")
        self._heatmap_act.toggled.connect(self._toggle_heatmap)
        view_menu.addAction(self._heatmap_act)

        self._flightlines_act = QAction("&Ratsnest Flightlines", self)
        self._flightlines_act.setCheckable(True)
        self._flightlines_act.setChecked(True)
        self._flightlines_act.setStatusTip("Toggle connectivity flightlines for selected instance/nets")
        self._flightlines_act.toggled.connect(self._toggle_flightlines)
        view_menu.addAction(self._flightlines_act)

        view_menu.addSeparator()
        docks_menu = view_menu.addMenu("&Panels && Docks")
        docks_menu.addAction(self._controls.toggleViewAction())
        docks_menu.addAction(self._search_dock.toggleViewAction())
        docks_menu.addAction(self._inspector.toggleViewAction())
        docks_menu.addAction(self._legend.toggleViewAction())
        docks_menu.addSeparator()

        reset_layout_act = QAction("&Reset Dock Layout", self)
        reset_layout_act.setStatusTip("Restore default side dock arrangement")
        reset_layout_act.triggered.connect(self._reset_dock_layout)
        docks_menu.addAction(reset_layout_act)

        self._lock_docks_act = QAction("&Lock Docks in Place", self)
        self._lock_docks_act.setCheckable(True)
        self._lock_docks_act.setChecked(False)
        self._lock_docks_act.setStatusTip("Lock dock positions to prevent accidental undocking")
        self._lock_docks_act.toggled.connect(self._toggle_lock_docks)
        docks_menu.addAction(self._lock_docks_act)

        # Tools Menu
        tools_menu = menubar.addMenu("&Tools")
        self._ruler_act = QAction("&Ruler / Measure", self)
        self._ruler_act.setShortcut(QKeySequence("K"))
        self._ruler_act.setCheckable(True)
        self._ruler_act.setStatusTip("Interactive measurement ruler between any two points (K)")
        self._ruler_act.triggered.connect(self._viewer.toggleRulerMode)
        tools_menu.addAction(self._ruler_act)

        clear_rulers_act = QAction("&Clear All Rulers", self)
        clear_rulers_act.setShortcut(QKeySequence("Shift+K"))
        clear_rulers_act.setStatusTip("Remove all measurement rulers (Shift+K)")
        clear_rulers_act.triggered.connect(self._viewer.clearRulers)
        tools_menu.addAction(clear_rulers_act)

        tools_menu.addSeparator()

        find_act = QAction("&Find Object...", self)
        find_act.setShortcut(QKeySequence("Ctrl+F"))
        find_act.setStatusTip("Focus intelligent fuzzy search and quick-jump panel (Ctrl+F)")
        find_act.triggered.connect(self._focus_search)
        tools_menu.addAction(find_act)

        # Help Menu
        help_menu = menubar.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _add_sample_actions(self, menu) -> None:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        designs_dir = os.path.join(base_dir, "designs")

        n45_tech = os.path.join(designs_dir, "Nangate45", "Nangate45_tech.lef")
        n45_cell = os.path.join(designs_dir, "Nangate45", "Nangate45_stdcell.lef")

        sky_tech = os.path.join(designs_dir, "sky130hd", "sky130hd.tlef")
        sky_cell = os.path.join(designs_dir, "sky130hd", "sky130_fd_sc_hd_merged.lef")

        samples = [
            (
                "Leon3 MP SoC Benchmark #2 (312k Cells, 406k Nets)",
                [n45_tech, n45_cell],
                os.path.join(designs_dir, "large", "large02.def"),
            ),
            (
                "Leon3 MP SoC Benchmark #1 (220k Cells, 300k Nets)",
                [n45_tech, n45_cell],
                os.path.join(designs_dir, "large", "large01.def"),
            ),
            (
                "SweRV RISC-V Placed Core (28 SRAM Macros, 131k Cells)",
                [n45_tech, n45_cell, os.path.join(designs_dir, "swerv_wrapper", "swerv_wrapper_macro.lef")],
                os.path.join(designs_dir, "swerv_wrapper", "swerv_wrapper.def"),
            ),
            (
                "SweRV Medium SoC Benchmark (135k Cells, 140k Nets)",
                [n45_tech, n45_cell],
                os.path.join(designs_dir, "medium", "medium04.def"),
            ),
            (
                "BlackParrot SoC Back-End (10 Cache Macros, 76k Cells)",
                [n45_tech, n45_cell, os.path.join(designs_dir, "blackparrot", "bp_be_top_macro.lef")],
                os.path.join(designs_dir, "blackparrot", "bp_be_top.def"),
            ),
            (
                "Sky130 Multi-Power-Domain AES (45k Cells, UPF Multi-VDD)",
                [sky_tech, sky_cell],
                os.path.join(designs_dir, "upf_aes", "upf_aes.def"),
            ),
            (
                "Sky130 eFPGA Siteless Placement (12k Cells, Embedded Block)",
                [sky_tech, sky_cell, os.path.join(designs_dir, "cell_on_block", "cell_on_block2.lef")],
                os.path.join(designs_dir, "cell_on_block", "cell_on_block2.def"),
            ),
            (
                "Caravel Sky130 Padframe & IO Ring (818 Pads/Macros)",
                [sky_tech, sky_cell, os.path.join(designs_dir, "caravel", "chip_io.lef")],
                os.path.join(designs_dir, "caravel", "chip_io.def"),
            ),
            (
                "Ibex 32-bit RISC-V Core (34k Cells, 33k Nets)",
                [n45_tech, n45_cell],
                os.path.join(designs_dir, "ibex", "ibex_core.def"),
            ),
            (
                "AES-128 Crypto Engine (21k Cells, 19k Nets)",
                [n45_tech, n45_cell],
                os.path.join(designs_dir, "aes", "aes_cipher_top.def"),
            ),
            (
                "GCD Arithmetic Core (Fully Routed, 1.8k Cells)",
                [n45_tech, n45_cell],
                os.path.join(designs_dir, "gcd", "gcd_nangate45_route.def"),
            ),
        ]

        for label, lefs, def_file in samples:
            act = QAction(label, self)
            act.triggered.connect(lambda checked=False, l=lefs, d=def_file: self.load_design_files(l, d))
            menu.addAction(act)

    def load_design_files(self, lef_paths: List[str], def_path: str) -> None:
        """Loads a complete design (LEF + DEF) with smooth progress dialog feedback."""
        progress = QProgressDialog("Initializing design database...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Loading Physical Design")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        try:
            self._db = dbDatabase()
            self._lef_files = []
            lef_parser = LefParser(self._db)

            # LEF parsing occupies 0% - 15%
            valid_lefs = [lf for lf in lef_paths if os.path.exists(lf)]
            n_lefs = len(valid_lefs)
            step = 0
            for lf in valid_lefs:
                step += 1
                lef_pct = int(step * 15 / max(n_lefs, 1))
                progress.setValue(lef_pct)
                base = os.path.basename(lf)
                progress.setLabelText(f"Parsing LEF [{step}/{n_lefs}]: {base}...")
                QApplication.processEvents()
                if progress.wasCanceled():
                    return
                lef_parser.parse_file(lf)
                self._lef_files.append(lf)

            tech = self._db.getTech()
            if tech:
                self._viewer.getOptions().tech_init(tech)

            progress.setValue(15)
            def_base = os.path.basename(def_path)
            progress.setLabelText(f"Initializing DEF parser for {def_base}...")
            QApplication.processEvents()
            if progress.wasCanceled():
                return

            def on_def_progress(stage: str, cur: int, total: int) -> None:
                ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                if stage == "Components":
                    mapped_pct = 15 + int(ratio * 30)
                elif stage == "Pins":
                    mapped_pct = 45 + int(ratio * 3)
                elif stage == "Special Nets":
                    mapped_pct = 48 + int(ratio * 4)
                elif stage == "Signal Nets":
                    mapped_pct = 52 + int(ratio * 23)
                else:
                    mapped_pct = 15 + int(ratio * 60)

                progress.setValue(mapped_pct)
                if total > 0:
                    pct = int(ratio * 100)
                    progress.setLabelText(f"Parsing DEF: {def_base}\n{stage}: {cur:,} / {total:,} ({pct}%)...")
                else:
                    progress.setLabelText(f"Parsing DEF: {def_base}\n{stage}: {cur:,}...")
                QApplication.processEvents()

            def_parser = DefParser(self._db)
            block = def_parser.parse_file(def_path, callback=on_def_progress)
            self._def_file = def_path

            if progress.wasCanceled():
                return

            chip = self._db.getChip()

            # 75% - 87%: Spatial Index
            progress.setValue(76)
            progress.setLabelText(f"Building spatial index ({len(block.getInsts()):,} instances)...")
            QApplication.processEvents()
            self._viewer.setChip(chip)
            progress.setValue(87)
            QApplication.processEvents()
            if progress.wasCanceled():
                return

            # 87% - 92%: Layer Display Controls
            progress.setLabelText("Configuring layer display controls...")
            QApplication.processEvents()
            self._controls.refresh()
            progress.setValue(92)
            QApplication.processEvents()

            # 92% - 95%: Design Inspector
            progress.setLabelText("Populating Design Inspector metrics...")
            QApplication.processEvents()
            self._inspector.update_design(chip)
            progress.setValue(95)
            QApplication.processEvents()

            # 95% - 99%: Search index
            progress.setLabelText("Indexing searchable components & nets...")
            QApplication.processEvents()
            self._search_dock.setChip(chip)
            progress.setValue(99)
            QApplication.processEvents()

            inst_count = len(block.getInsts())
            net_count = len(block.getNets())
            self._info_label.setText(f"Design: {block.getName()} | {inst_count:,} Insts | {net_count:,} Nets")
            self._status_bar.showMessage(f"Successfully loaded {block.getName()} ({inst_count:,} insts)", 5000)

            # Fit into view
            self._viewer.fit()

        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load design:\n{str(e)}")
        finally:
            progress.setValue(100)

    def load_lef(self, filepath: str, progress: Optional[QProgressDialog] = None) -> None:
        base = os.path.basename(filepath)
        own_progress = False
        if progress is None:
            progress = QProgressDialog(f"Parsing LEF: {base}...", None, 0, 1, self)
            progress.setWindowTitle("Loading LEF File")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            own_progress = True
            QApplication.processEvents()

        try:
            parser = LefParser(self._db)
            parser.parse_file(filepath)
            self._lef_files.append(filepath)
            tech = self._db.getTech()
            if tech:
                self._viewer.getOptions().tech_init(tech)
            self._controls.refresh()
            self._status_bar.showMessage(f"Loaded LEF: {base}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "LEF Error", f"Failed to load LEF:\n{str(e)}")
        finally:
            if own_progress and progress:
                progress.setValue(1)

    def load_def(self, filepath: str) -> None:
        def_base = os.path.basename(filepath)
        progress = QProgressDialog(f"Initializing DEF parser for {def_base}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Loading DEF File")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        def on_def_progress(stage: str, cur: int, total: int) -> None:
            ratio = min(max(cur / max(total, 1), 0.0), 1.0)
            if stage == "Components":
                mapped_pct = int(ratio * 35)
            elif stage == "Pins":
                mapped_pct = 35 + int(ratio * 3)
            elif stage == "Special Nets":
                mapped_pct = 38 + int(ratio * 4)
            elif stage == "Signal Nets":
                mapped_pct = 42 + int(ratio * 28)
            else:
                mapped_pct = int(ratio * 70)

            progress.setValue(mapped_pct)
            if total > 0:
                pct = int(ratio * 100)
                progress.setLabelText(f"Parsing DEF: {def_base}\n{stage}: {cur:,} / {total:,} ({pct}%)...")
            else:
                progress.setLabelText(f"Parsing DEF: {def_base}\n{stage}: {cur:,}...")
            QApplication.processEvents()

        try:
            progress.setValue(1)
            progress.setLabelText(f"Parsing layout from {def_base}...")
            QApplication.processEvents()

            parser = DefParser(self._db)
            block = parser.parse_file(filepath, callback=on_def_progress)
            if progress.wasCanceled():
                return
            self._def_file = filepath
            chip = self._db.getChip()

            # 70% - 85%: Spatial Index
            progress.setValue(72)
            inst_count = len(block.getInsts())
            progress.setLabelText(f"Building spatial index ({inst_count:,} instances)...")
            QApplication.processEvents()
            self._viewer.setChip(chip)
            progress.setValue(85)
            QApplication.processEvents()
            if progress.wasCanceled():
                return

            # 85% - 90%: Layer Controls
            progress.setLabelText("Configuring layer display controls...")
            QApplication.processEvents()
            self._controls.refresh()
            progress.setValue(90)
            QApplication.processEvents()

            # 90% - 93%: Design Inspector
            progress.setLabelText("Updating design inspector...")
            QApplication.processEvents()
            self._inspector.update_design(chip)
            progress.setValue(93)
            QApplication.processEvents()

            # 93% - 99%: Search Index
            progress.setLabelText("Indexing objects for fast search...")
            QApplication.processEvents()
            self._search_dock.setChip(chip)
            progress.setValue(99)
            QApplication.processEvents()

            net_count = len(block.getNets())
            self._info_label.setText(f"Design: {block.getName()} | {inst_count:,} Insts | {net_count:,} Nets")
            self._status_bar.showMessage(f"Loaded DEF: {def_base} ({inst_count:,} insts, {net_count:,} nets)", 5000)

            self._viewer.fit()

        except Exception as e:
            QMessageBox.critical(self, "DEF Error", f"Failed to load DEF:\n{str(e)}")
        finally:
            progress.setValue(100)

    def _open_lef_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Open LEF File(s)",
            "",
            "LEF Files (*.lef *.tlef);;All Files (*)",
        )
        if not files:
            return

        total = len(files)
        progress = QProgressDialog("Loading LEF file(s)...", "Cancel", 0, total, self)
        progress.setWindowTitle("Loading LEF Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        try:
            for idx, f in enumerate(files):
                base = os.path.basename(f)
                progress.setValue(idx)
                progress.setLabelText(f"Parsing LEF [{idx + 1}/{total}]: {base}...")
                QApplication.processEvents()
                if progress.wasCanceled():
                    break
                self.load_lef(f, progress=progress)
        finally:
            progress.setValue(total)

    def _open_def_dialog(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Open DEF File",
            "",
            "DEF Files (*.def);;All Files (*)",
        )
        if file:
            self.load_def(file)

    def _import_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Design Directory Containing LEF & DEF Files")
        if not folder:
            return

        # Find all LEF and DEF files in folder and subfolders
        all_lefs = glob.glob(os.path.join(folder, "**", "*.lef"), recursive=True) + glob.glob(
            os.path.join(folder, "**", "*.tlef"), recursive=True
        )
        all_defs = glob.glob(os.path.join(folder, "**", "*.def"), recursive=True)

        # Fallback: check parent directory if tech LEFs are in a sibling folder (e.g., designs/Nangate45)
        if not all_lefs:
            parent = os.path.dirname(folder)
            all_lefs = glob.glob(os.path.join(parent, "**", "*.lef"), recursive=True) + glob.glob(
                os.path.join(parent, "**", "*.tlef"), recursive=True
            )

        if not all_defs:
            QMessageBox.warning(self, "Import Failed", f"No .def file found in:\n{folder}")
            return

        # Sort LEFs so tech LEF is parsed first, then cell LEF, then macro LEF
        def lef_sort_key(p: str) -> int:
            b = os.path.basename(p).lower()
            if "tech" in b or p.endswith(".tlef"):
                return 0
            if "stdcell" in b or "cell" in b:
                return 1
            if "macro" in b or "ram" in b:
                return 2
            return 3

        sorted_lefs = sorted(list(set(all_lefs)), key=lef_sort_key)

        # Pick routed DEF if multiple
        target_def = all_defs[0]
        for d in all_defs:
            if "route" in os.path.basename(d).lower():
                target_def = d
                break

        self.load_design_files(sorted_lefs, target_def)

    def _on_cursor_moved(self, x_um: float, y_um: float) -> None:
        self._coords_label.setText(f"X: {x_um:8.3f} µm  Y: {y_um:8.3f} µm")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About OpenROAD Python Viewer",
            "<h3>OpenROAD Native Python LEF/DEF Layout Viewer</h3>"
            "<p>A high-performance EDA viewer directly ported from OpenROAD source code "
            "(<code>src/gui</code> and <code>src/odb</code>).</p>"
            "<p>Supports full LEF/DEF parsing, routing layers, vias, macro pins, "
            "obstructions, and interactive zooming/panning.</p>",
        )

    def _on_macro_selected(self, inst_or_name, *args) -> None:
        """Zooms layout viewer directly to the bounding box of the selected macro."""
        if args and len(args) == 4:
            inst_name = str(inst_or_name)
            x, y, w, h = args
            box = Rect(x, y, x + w, y + h)
            self._viewer.zoomTo(box)
            self._viewer.highlightObject(box, f"[MACRO] {inst_name}")
            self._status_bar.showMessage(f"Focused on macro: {inst_name} ({w:,} x {h:,} DBU)", 4000)
        else:
            inst = inst_or_name
            if hasattr(inst, "getBBox"):
                box = inst.getBBox().getBox()
                self._viewer.zoomTo(box)
                self._viewer.selectInstance(inst)
                self._inspector.inspect_instance(inst)
                self._status_bar.showMessage(f"Focused on macro: {inst.getName()}", 4000)

    def _on_search_object_selected(self, rect: Rect, label: str) -> None:
        """Navigates viewport directly to the object selected in the search widget."""
        self._viewer.zoomTo(rect)
        self._viewer.highlightObject(rect, label)
        self._status_bar.showMessage(f"Navigated to {label}", 4000)

    def _on_search_objects_selected(self, items: List[tuple]) -> None:
        """Navigates viewport to multiple objects selected in search widget."""
        if not items:
            self._viewer.highlightObjects([])
            self._status_bar.showMessage("Cleared search selection", 2000)
            return
        self._viewer.highlightObjects(items, zoom=True)
        self._status_bar.showMessage(f"Selected {len(items)} objects in layout", 4000)

    def _on_instance_selected(self, inst: Optional[object]) -> None:
        """Updates Inspector dock when user clicks an instance in the viewport."""
        self._inspector.inspect_instance(inst)
        if inst is not None:
            self._inspector.show()
            self._inspector.raise_()
            self._status_bar.showMessage(f"Selected: {inst.getName()} ({inst.getMaster().getName()})", 4000)

    def _on_display_control_option_toggled(self, attr: str, checked: bool) -> None:
        """Keeps View menu actions synchronized when options are toggled in DisplayControls dock."""
        if attr == "_show_density_heatmap" and hasattr(self, "_heatmap_act"):
            self._heatmap_act.blockSignals(True)
            self._heatmap_act.setChecked(checked)
            self._heatmap_act.blockSignals(False)
        elif attr == "_show_flightlines" and hasattr(self, "_flightlines_act"):
            self._flightlines_act.blockSignals(True)
            self._flightlines_act.setChecked(checked)
            self._flightlines_act.blockSignals(False)

    def _toggle_heatmap(self, checked: bool) -> None:
        """Toggles placement density congestion heatmap overlay."""
        self._viewer.getOptions().setShowDensityHeatmap(checked)
        self._controls.sync_option("_show_density_heatmap", checked)
        self._viewer.update()
        state_str = "Enabled" if checked else "Disabled"
        self._status_bar.showMessage(f"Placement Density Heatmap {state_str}", 2500)

    def _toggle_flightlines(self, checked: bool) -> None:
        """Toggles connectivity ratsnest flightlines."""
        self._viewer.getOptions().setShowFlightlines(checked)
        self._controls.sync_option("_show_flightlines", checked)
        self._viewer.update()
        state_str = "Enabled" if checked else "Disabled"
        self._status_bar.showMessage(f"Ratsnest Flightlines {state_str}", 2500)

    def _export_layout_image(self) -> None:
        """Exports the current layout view to a high-resolution image file."""
        if not self._viewer.hasDesign():
            QMessageBox.information(self, "Export Image", "No design loaded to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Layout Image",
            "layout_render.png",
            "PNG Image (*.png);;JPEG Image (*.jpg);;BMP Image (*.bmp)",
        )
        if not file_path:
            return

        pix = self._viewer.grab()
        if pix.save(file_path):
            self._status_bar.showMessage(f"Layout image saved to {os.path.basename(file_path)}", 5000)
            QMessageBox.information(self, "Export Image", f"Layout successfully exported to:\n{file_path}")
        else:
            QMessageBox.warning(self, "Export Error", f"Failed to save image to:\n{file_path}")

    def _on_ruler_measured(self, dist_um: float, dx_um: float, dy_um: float) -> None:
        """Displays completed ruler measurement in the status bar."""
        self._status_bar.showMessage(
            f"Measurement: {dist_um:,.3f} µm (dx: {dx_um:,.3f} µm, dy: {dy_um:,.3f} µm)", 6000
        )

    def _on_ruler_mode_changed(self, active: bool) -> None:
        """Synchronizes menu action and provides user prompt for ruler measurement."""
        if hasattr(self, "_ruler_act"):
            self._ruler_act.setChecked(active)
        if active:
            self._status_bar.showMessage(
                "Ruler Mode: Click Point A, then click Point B to measure distance (Esc to cancel, Shift+K to clear)",
                8000,
            )
        else:
            self._status_bar.showMessage("Exited Ruler Mode", 2000)

    def _focus_search(self) -> None:
        """Opens/raises the search dock and focuses the search input line."""
        self._search_dock.show()
        self._search_dock.raise_()
        self._search_dock._search_input.setFocus()
        self._search_dock._search_input.selectAll()

    def _reset_dock_layout(self) -> None:
        """Restores the initial clean dock arrangement."""
        self.addDockWidget(Qt.LeftDockWidgetArea, self._controls)
        self.addDockWidget(Qt.RightDockWidgetArea, self._search_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, self._legend)
        self.tabifyDockWidget(self._search_dock, self._inspector)
        self.tabifyDockWidget(self._inspector, self._legend)
        self._controls.setFloating(False)
        self._search_dock.setFloating(False)
        self._inspector.setFloating(False)
        self._legend.setFloating(False)
        self._controls.show()
        self._search_dock.show()
        self._inspector.show()
        self._legend.show()
        self._inspector.raise_()
        self._status_bar.showMessage("Dock layout restored to default", 3000)

    def _toggle_lock_docks(self, locked: bool) -> None:
        """Locks or unlocks docks to prevent or allow moving and floating."""
        features = QDockWidget.NoDockWidgetFeatures if locked else (
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self._controls.setFeatures(features)
        self._search_dock.setFeatures(features)
        self._inspector.setFeatures(features)
        self._legend.setFeatures(features)
        state_str = "locked" if locked else "unlocked (movable & floatable)"
        self._status_bar.showMessage(f"Docks {state_str}", 3000)

    def closeEvent(self, event) -> None:
        """Safely terminates background rendering threads when window closes."""
        if hasattr(self, "_viewer") and self._viewer is not None:
            if hasattr(self._viewer, "_render_thread") and self._viewer._render_thread is not None:
                self._viewer._render_thread.exit_thread()
        super().closeEvent(event)

