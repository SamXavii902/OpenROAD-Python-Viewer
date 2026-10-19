"""MainWindow ported from RISHI gui/src/mainWindow.cpp with interactive controls, legend, and folder import."""

import sys
import os
import glob
from typing import Optional, List, Callable, Any
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
from PySide6.QtGui import QAction, QKeySequence, QColor
from PySide6.QtCore import Qt
import time
from rishi.odb.database import dbDatabase
from rishi.odb.geom import Rect, Point
from rishi.lefin import LefParser
from rishi.defin import DefParser
from rishi.gui.layoutViewer import LayoutViewer
from rishi.gui.displayControls import DisplayControls
from rishi.gui.legend import LegendDock
from rishi.gui.inspector import InspectorDock
from rishi.gui.searchWidget import SearchDock
from rishi.gui.timingReportWidget import TimingReportDock
from rishi.gui.irDropWidget import IRDropDock
from rishi.irdrop.report import IR_DROP_PALETTE
from rishi.timing.tarpt_parser import TarptParser
from rishi.gui.theme import apply_dark_theme


class MainWindow(QMainWindow):
    """Main application window matching RISHI GUI layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QApplication.instance()
        if app is not None and not getattr(app, "_rishi_dark_theme_applied", False):
            apply_dark_theme(app)
            app._rishi_dark_theme_applied = True
        self.setWindowTitle("RISHI Python EDA Viewer")
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

        # Bottom dock: Timing Report & Debugger (Cadence Innovus / Tempus UI)
        self._timing_dock = TimingReportDock(self)
        self._timing_dock.setLayoutViewer(self._viewer)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._timing_dock)
        self._timing_dock.hide()

        self._ir_drop_dock = IRDropDock(self)
        self._ir_drop_dock.setLayoutViewer(self._viewer)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._ir_drop_dock)
        self.tabifyDockWidget(self._timing_dock, self._ir_drop_dock)
        self._ir_drop_dock.hide()

        self._controls.option_toggled.connect(self._on_display_control_option_toggled)
        self._inspector.macro_selected.connect(self._on_macro_selected)
        self._search_dock.object_selected.connect(self._on_search_object_selected)
        self._search_dock.objects_selected.connect(self._on_search_objects_selected)
        self._viewer.instance_selected.connect(self._on_instance_selected)
        self._viewer.ruler_measured.connect(self._on_ruler_measured)
        self._viewer.ruler_mode_changed.connect(self._on_ruler_mode_changed)

        self._timing_dock.path_selected.connect(self._on_timing_path_selected)
        self._timing_dock.paths_highlighted.connect(self._on_timing_paths_highlighted)
        self._timing_dock.paths_cleared.connect(self._viewer.clearTimingPaths)
        self._ir_drop_dock.instance_selected.connect(self._on_ir_drop_instance_selected)
        self._ir_drop_dock.map_visibility_changed.connect(self._on_ir_drop_map_visibility_changed)

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

        open_timing_act = QAction("Open &Timing Report...", self)
        open_timing_act.setShortcut(QKeySequence("Ctrl+Shift+T"))
        open_timing_act.setStatusTip("Open Cadence Innovus / Tempus timing report (.tarpt, .btarpt, .rpt)")
        open_timing_act.triggered.connect(self._open_timing_report_dialog)
        file_menu.addAction(open_timing_act)

        open_ir_drop_act = QAction("Open &IR-Drop Report...", self)
        open_ir_drop_act.setShortcut(QKeySequence("Ctrl+Shift+I"))
        open_ir_drop_act.setStatusTip("Load a per-cell voltage-drop report for hotspot analysis")
        open_ir_drop_act.triggered.connect(self._open_ir_drop_report_dialog)
        file_menu.addAction(open_ir_drop_act)

        export_img_act = QAction("&Export Layout Image...", self)
        export_img_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        export_img_act.setStatusTip("Export current layout view as high-resolution PNG image")
        export_img_act.triggered.connect(self._export_layout_image)
        file_menu.addAction(export_img_act)

        close_design_act = QAction("&Close Design", self)
        close_design_act.setShortcut(QKeySequence("Ctrl+W"))
        close_design_act.setStatusTip("Close current design, free memory, and start fresh")
        close_design_act.triggered.connect(self.close_design)
        file_menu.addAction(close_design_act)

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

        self._ir_drop_map_act = QAction("IR-Drop Cell Map", self)
        self._ir_drop_map_act.setCheckable(True)
        self._ir_drop_map_act.setChecked(False)
        self._ir_drop_map_act.setStatusTip("Color standard cells by the loaded IR-drop report")
        self._ir_drop_map_act.toggled.connect(self._ir_drop_dock.get_widget().set_map_visible)
        view_menu.addAction(self._ir_drop_map_act)

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
        docks_menu.addAction(self._timing_dock.toggleViewAction())
        docks_menu.addAction(self._ir_drop_dock.toggleViewAction())
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

        timing_debugger_act = QAction("&Timing Report Debugger...", self)
        timing_debugger_act.setShortcut(QKeySequence("Ctrl+T"))
        timing_debugger_act.setStatusTip("Toggle Cadence timing report debugger dock (Ctrl+T)")
        timing_debugger_act.triggered.connect(self._toggle_timing_debugger)
        tools_menu.addAction(timing_debugger_act)

        ir_drop_act = QAction("IR-Drop Analysis...", self)
        ir_drop_act.triggered.connect(self._toggle_ir_drop_dock)
        tools_menu.addAction(ir_drop_act)

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
        self.close_design(silent=True)
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
                base = os.path.basename(lf)

                def on_lef_sub_progress(stage: str, cur: int, total: int, detail: str = "", sub_fraction: float = 0.0) -> None:
                    lef_pct = int(((step - 1) + sub_fraction) * 15 / max(n_lefs, 1))
                    progress.setValue(min(lef_pct, 15))
                    detail_str = f" ({detail})" if detail else ""
                    progress.setLabelText(f"Parsing LEF [{step}/{n_lefs}]: {base}{detail_str}")
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        raise KeyboardInterrupt("Cancelled")

                if progress.wasCanceled():
                    return
                lef_parser.parse_file(lf, callback=on_lef_sub_progress)
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

            last_def_ui_update = 0.0

            def on_def_progress(stage: str, cur: int, total: int, detail: str = "", sub_fraction: float = 0.0) -> None:
                nonlocal last_def_ui_update
                now = time.time()
                is_final = cur >= total and total > 0
                if not is_final and now - last_def_ui_update < 0.12:
                    return
                last_def_ui_update = now

                if stage == "Components":
                    ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                    mapped_pct = 15 + int(ratio * 28)  # 15% to 43%
                elif stage == "Pins":
                    ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                    mapped_pct = 43 + int(ratio * 3)   # 43% to 46%
                elif stage == "Special Nets":
                    effective_cur = max(cur - 1, 0) + sub_fraction if (cur > 0 or sub_fraction > 0) else float(cur)
                    ratio = min(max(effective_cur / max(total, 1), 0.0), 1.0)
                    mapped_pct = 46 + int(ratio * 7)   # 46% to 53%
                elif stage == "Signal Nets":
                    effective_cur = max(cur - 1, 0) + sub_fraction if sub_fraction > 0 else float(cur)
                    ratio = min(max(effective_cur / max(total, 1), 0.0), 1.0)
                    mapped_pct = 53 + int(ratio * 19)  # 53% to 72%
                else:
                    ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                    mapped_pct = 15 + int(ratio * 57)

                progress.setValue(mapped_pct)
                if detail:
                    progress.setLabelText(f"Parsing DEF: {def_base}\n{stage} [{cur:,}/{total:,}]: {detail}...")
                elif total > 0:
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

            # 72% - 88%: Spatial Index with sub-stage progress
            def on_spatial_progress(sub_stage: str, s_cur: int, s_tot: int) -> None:
                s_ratio = min(max(s_cur / max(s_tot, 1), 0.0), 1.0)
                if "Instance" in sub_stage:
                    s_pct = 72 + int(s_ratio * 5)
                elif "Routing" in sub_stage:
                    s_pct = 77 + int(s_ratio * 6)
                else:
                    s_pct = 83 + int(s_ratio * 5)
                progress.setValue(s_pct)
                progress.setLabelText(f"Building spatial index...\n{sub_stage}: {s_cur:,} / {s_tot:,} ({int(s_ratio * 100)}%)...")
                QApplication.processEvents()

            progress.setValue(72)
            progress.setLabelText(f"Building spatial index ({len(block.getInsts()):,} instances)...")
            QApplication.processEvents()
            self._viewer.setChip(chip, progress_callback=on_spatial_progress)
            progress.setValue(88)
            QApplication.processEvents()
            if progress.wasCanceled():
                return

            # 88% - 92%: Layer Display Controls
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

            # 95% - 99%: Search index & Timing Dock
            progress.setLabelText("Indexing searchable components & nets...")
            QApplication.processEvents()
            self._search_dock.setChip(chip)
            self._timing_dock.setChip(chip, layout_viewer=self._viewer)
            progress.setValue(97)
            QApplication.processEvents()

            # Auto-detect timing report in folder if present
            folder_path = os.path.dirname(os.path.abspath(def_path))
            tarpt_files = (
                glob.glob(os.path.join(folder_path, "*.tarpt"))
                + glob.glob(os.path.join(folder_path, "*.btarpt"))
                + glob.glob(os.path.join(folder_path, "**", "*.tarpt"), recursive=True)
                + glob.glob(os.path.join(folder_path, "**", "*.btarpt"), recursive=True)
            )
            if tarpt_files:
                tarpt_path = tarpt_files[0]
                tarpt_base = os.path.basename(tarpt_path)
                t_tarpt_start = time.time()

                def on_tarpt_progress(stage: str, cur: int, total: int, detail: str) -> None:
                    ratio = cur / max(total, 1) if total > 0 else 0.5
                    t_pct = 97 + int(ratio * 2)  # 97% to 99%
                    progress.setValue(min(t_pct, 99))
                    now_el = time.time() - t_tarpt_start
                    progress.setLabelText(f"Loading timing report: {tarpt_base}\n{detail} (Elapsed: {now_el:.2f}s)...")
                    QApplication.processEvents()

                try:
                    rep = TarptParser().parse_file(tarpt_path, callback=on_tarpt_progress)
                    self._timing_dock.get_widget()._file_edit.setText(tarpt_path)
                    self._timing_dock.get_widget().set_report_data(rep)
                    self._timing_dock.show()
                    t_el = time.time() - t_tarpt_start
                    self._status_bar.showMessage(
                        f"Loaded timing report: {tarpt_base} ({len(rep.paths):,} paths) in {t_el:.2f}s", 5000
                    )
                except Exception as ex:
                    print(f"Warning: failed to load timing report {tarpt_path}: {ex}")

            progress.setValue(100)
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

    def load_lef(
        self,
        filepath: str,
        progress: Optional[QProgressDialog] = None,
        callback: Optional[Callable] = None,
    ) -> None:
        base = os.path.basename(filepath)
        own_progress = False
        if progress is None:
            progress = QProgressDialog(f"Parsing LEF: {base}...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Loading LEF File")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            own_progress = True
            QApplication.processEvents()

        try:
            def on_lef_progress(stage: str, cur: int, total: int, detail: str = "", sub_fraction: float = 0.0) -> None:
                if callback:
                    callback(stage, cur, total, detail, sub_fraction)
                elif own_progress and progress:
                    pct = int(sub_fraction * 100)
                    progress.setValue(min(pct, 99))
                    detail_str = f" ({detail})" if detail else ""
                    progress.setLabelText(f"Parsing LEF: {base}{detail_str}")
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        raise KeyboardInterrupt("Cancelled")

            parser = LefParser(self._db)
            parser.parse_file(filepath, callback=on_lef_progress)
            self._lef_files.append(filepath)
            tech = self._db.getTech()
            if tech:
                self._viewer.getOptions().tech_init(tech)
            self._controls.refresh()
            self._status_bar.showMessage(f"Loaded LEF: {base}", 4000)
        except KeyboardInterrupt:
            self._status_bar.showMessage(f"LEF loading cancelled: {base}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "LEF Error", f"Failed to load LEF:\n{str(e)}")
        finally:
            if own_progress and progress:
                progress.setValue(100)

    def load_def(self, filepath: str) -> None:
        def_base = os.path.basename(filepath)
        progress = QProgressDialog(f"Initializing DEF parser for {def_base}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Loading DEF File")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        last_def_ui_update = 0.0

        def on_def_progress(stage: str, cur: int, total: int, detail: str = "", sub_fraction: float = 0.0) -> None:
            nonlocal last_def_ui_update
            now = time.time()
            is_final = cur >= total and total > 0
            if not is_final and now - last_def_ui_update < 0.12:
                return
            last_def_ui_update = now

            if stage == "Components":
                ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                mapped_pct = int(ratio * 35)  # 0% to 35%
            elif stage == "Pins":
                ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                mapped_pct = 35 + int(ratio * 3)  # 35% to 38%
            elif stage == "Special Nets":
                effective_cur = max(cur - 1, 0) + sub_fraction if (cur > 0 or sub_fraction > 0) else float(cur)
                ratio = min(max(effective_cur / max(total, 1), 0.0), 1.0)
                mapped_pct = 38 + int(ratio * 8)  # 38% to 46%
            elif stage == "Signal Nets":
                effective_cur = max(cur - 1, 0) + sub_fraction if sub_fraction > 0 else float(cur)
                ratio = min(max(effective_cur / max(total, 1), 0.0), 1.0)
                mapped_pct = 46 + int(ratio * 24)  # 46% to 70%
            else:
                ratio = min(max(cur / max(total, 1), 0.0), 1.0)
                mapped_pct = int(ratio * 70)

            progress.setValue(mapped_pct)
            if detail:
                progress.setLabelText(f"Parsing DEF: {def_base}\n{stage} [{cur:,}/{total:,}]: {detail}...")
            elif total > 0:
                pct = int(ratio * 100)
                progress.setLabelText(f"Parsing DEF: {def_base}\n{stage}: {cur:,} / {total:,} ({pct}%)...")
            else:
                progress.setLabelText(f"Parsing DEF: {def_base}\n{stage}: {cur:,}...")
            QApplication.processEvents()

        try:
            if self._def_file is not None or (self._db and self._db.getChip() and self._db.getChip().getBlock()):
                if hasattr(self, "_viewer") and self._viewer is not None:
                    self._viewer.setChip(None)
                if hasattr(self, "_timing_dock") and self._timing_dock is not None:
                    self._timing_dock.clear()
                if hasattr(self, "_search_dock") and self._search_dock is not None:
                    self._search_dock.clear()
                if hasattr(self, "_inspector") and self._inspector is not None:
                    self._inspector.clear()

            progress.setValue(1)
            progress.setLabelText(f"Parsing layout from {def_base}...")
            QApplication.processEvents()

            parser = DefParser(self._db)
            block = parser.parse_file(filepath, callback=on_def_progress)
            if progress.wasCanceled():
                return
            self._def_file = filepath
            chip = self._db.getChip()

            # 70% - 88%: Spatial Index with live sub-stage feedback
            def on_spatial_progress(sub_stage: str, s_cur: int, s_tot: int) -> None:
                s_ratio = min(max(s_cur / max(s_tot, 1), 0.0), 1.0)
                if "Instance" in sub_stage:
                    s_pct = 70 + int(s_ratio * 6)
                elif "Routing" in sub_stage:
                    s_pct = 76 + int(s_ratio * 7)
                else:
                    s_pct = 83 + int(s_ratio * 5)
                progress.setValue(s_pct)
                progress.setLabelText(f"Building spatial index...\n{sub_stage}: {s_cur:,} / {s_tot:,} ({int(s_ratio * 100)}%)...")
                QApplication.processEvents()

            inst_count = len(block.getInsts())
            progress.setValue(70)
            progress.setLabelText(f"Building spatial index ({inst_count:,} instances)...")
            QApplication.processEvents()
            self._viewer.setChip(chip, progress_callback=on_spatial_progress)
            progress.setValue(88)
            QApplication.processEvents()
            if progress.wasCanceled():
                return

            # 88% - 92%: Layer Controls
            progress.setLabelText("Configuring layer display controls...")
            QApplication.processEvents()
            self._controls.refresh()
            progress.setValue(92)
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
            self._timing_dock.setChip(chip, layout_viewer=self._viewer)
            progress.setValue(97)
            QApplication.processEvents()

            # Auto-detect timing report in folder if present
            folder_path = os.path.dirname(os.path.abspath(filepath))
            tarpt_files = (
                glob.glob(os.path.join(folder_path, "*.tarpt"))
                + glob.glob(os.path.join(folder_path, "*.btarpt"))
                + glob.glob(os.path.join(folder_path, "**", "*.tarpt"), recursive=True)
                + glob.glob(os.path.join(folder_path, "**", "*.btarpt"), recursive=True)
            )
            if tarpt_files:
                tarpt_path = tarpt_files[0]
                tarpt_base = os.path.basename(tarpt_path)
                t_tarpt_start = time.time()

                def on_def_tarpt_progress(stage: str, cur: int, total: int, detail: str) -> None:
                    ratio = cur / max(total, 1) if total > 0 else 0.5
                    t_pct = 97 + int(ratio * 2)
                    progress.setValue(min(t_pct, 99))
                    now_el = time.time() - t_tarpt_start
                    progress.setLabelText(f"Loading timing report: {tarpt_base}\n{detail} (Elapsed: {now_el:.2f}s)...")
                    QApplication.processEvents()

                try:
                    rep = TarptParser().parse_file(tarpt_path, callback=on_def_tarpt_progress)
                    self._timing_dock.get_widget()._file_edit.setText(tarpt_path)
                    self._timing_dock.get_widget().set_report_data(rep)
                    self._timing_dock.show()
                    t_el = time.time() - t_tarpt_start
                    self._status_bar.showMessage(
                        f"Loaded timing report: {tarpt_base} ({len(rep.paths):,} paths) in {t_el:.2f}s", 5000
                    )
                except Exception as ex:
                    print(f"Warning: failed to load timing report {tarpt_path}: {ex}")

            progress.setValue(100)
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
        progress = QProgressDialog("Loading LEF file(s)...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Loading LEF Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        try:
            for idx, f in enumerate(files):
                base = os.path.basename(f)

                def on_sub_progress(stage: str, cur: int, total_b: int, detail: str = "", sub_fraction: float = 0.0) -> None:
                    pct = int(((idx + sub_fraction) / total) * 100)
                    progress.setValue(min(pct, 99))
                    detail_str = f" ({detail})" if detail else ""
                    progress.setLabelText(f"Parsing LEF [{idx + 1}/{total}]: {base}{detail_str}")
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        raise KeyboardInterrupt("Cancelled")

                if progress.wasCanceled():
                    break
                self.load_lef(f, progress=progress, callback=on_sub_progress)
        except KeyboardInterrupt:
            self._status_bar.showMessage("LEF loading cancelled by user", 3000)
        finally:
            progress.setValue(100)

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
        text = f"X: {x_um:8.3f} µm  Y: {y_um:8.3f} µm"
        if self._viewer.getOptions().showDensityHeatmap() and self._viewer.hasDesign():
            dbu_per_um = self._viewer._chip.getTech().getDbuPerMicron() if self._viewer._chip and self._viewer._chip.getTech() else 1000
            pt = Point(int(round(x_um * dbu_per_um)), int(round(y_um * dbu_per_um)))
            d = self._viewer.getDensityAt(pt)
            if d is not None:
                text += f"  |  Density: {d * 100:5.1f}%"
        if self._viewer.isIRDropMapVisible() and self._viewer.hasDesign():
            dbu_per_um = self._viewer._chip.getTech().getDbuPerMicron() if self._viewer._chip and self._viewer._chip.getTech() else 1000
            pt = Point(int(round(x_um * dbu_per_um)), int(round(y_um * dbu_per_um)))
            ir_info = self._viewer.getIRDropAt(pt)
            if ir_info is not None:
                drop_mv, inst_name = ir_info
                inst_str = f" ({inst_name})" if inst_name else ""
                text += f"  |  IR Drop: {drop_mv:.1f} mV{inst_str}"
        self._coords_label.setText(text)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About RISHI Layout Viewer",
            "<h3>RISHI Native Python LEF/DEF Layout Viewer</h3>"
            "<p>A high-performance EDA viewer directly ported from RISHI source code "
            "(<code>src/gui</code> and <code>src/odb</code>).</p>"
            "<p>Supports full LEF/DEF parsing, routing layers, vias, macro pins, "
            "obstructions, and interactive zooming/panning.</p>",
        )

    def _on_macro_selected(self, inst_or_name, *args) -> None:
        """Zooms layout viewer smoothly to the bounding box of the selected macro with sonar ping."""
        if args and len(args) == 4:
            inst_name = str(inst_or_name)
            x, y, w, h = args
            box = Rect(x, y, x + w, y + h)
            self._viewer.zoomTo(box, animate=self._viewer.isVisible())
            self._viewer.highlightObject(box, f"[MACRO] {inst_name}")
            self._viewer.pingLocation(box.center(), QColor(255, 215, 0))
            self._status_bar.showMessage(f"Focused on macro: {inst_name} ({w:,} x {h:,} DBU)", 4000)
        else:
            inst = inst_or_name
            if hasattr(inst, "getBBox"):
                box = inst.getBBox().getBox()
                self._viewer.zoomTo(box, animate=self._viewer.isVisible())
                self._viewer.selectInstance(inst)
                self._viewer.pingLocation(box.center(), QColor(255, 215, 0))
                self._inspector.inspect_instance(inst)
                self._status_bar.showMessage(f"Focused on macro: {inst.getName()}", 4000)

    def _on_search_object_selected(self, rect: Rect, label: str) -> None:
        """Navigates viewport smoothly to the object selected in the search widget with sonar ping."""
        self._viewer.zoomTo(rect, animate=self._viewer.isVisible())
        self._viewer.highlightObject(rect, label)
        self._viewer.pingLocation(rect.center(), QColor(0, 229, 255))
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

    def _on_ir_drop_map_visibility_changed(self, checked: bool) -> None:
        self._ir_drop_map_act.blockSignals(True)
        self._ir_drop_map_act.setChecked(checked)
        self._ir_drop_map_act.blockSignals(False)
        self._viewer.setIRDropMapVisible(checked)
        self._status_bar.showMessage(f"IR-Drop Cell Map {'Enabled' if checked else 'Disabled'}", 2500)

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

    def _toggle_timing_debugger(self) -> None:
        """Toggles visibility of the Timing Report Debugger dock."""
        if self._timing_dock.isVisible():
            self._timing_dock.hide()
        else:
            self._timing_dock.show()
            self._timing_dock.raise_()

    def _toggle_ir_drop_dock(self) -> None:
        if self._ir_drop_dock.isVisible():
            self._ir_drop_dock.hide()
        else:
            self._ir_drop_dock.show()
            self._ir_drop_dock.raise_()

    def _open_timing_report_dialog(self) -> None:
        """Opens file dialog to select and display a Cadence timing report."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Timing Report",
            "",
            "Timing Reports (*.tarpt *.btarpt *.rpt *.tarpt.gz);;All Files (*.*)",
        )
        if filepath:
            self._timing_dock.show()
            self._timing_dock.raise_()
            self._timing_dock.load_file(filepath)
            self._status_bar.showMessage(f"Loaded timing report: {os.path.basename(filepath)}", 4000)

    def _open_ir_drop_report_dialog(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open IR-Drop Report",
            "",
            "IR-Drop Reports (*.rpt *.ir *.txt);;All Files (*.*)",
        )
        if filepath:
            self._ir_drop_dock.show()
            self._ir_drop_dock.raise_()
            self._ir_drop_dock.load_file(filepath)

    def _on_ir_drop_instance_selected(self, instance_name: str) -> None:
        if not self._viewer.hasDesign():
            self._status_bar.showMessage("Load a DEF design to navigate to an IR-drop hotspot", 4000)
            return
        inst = self._viewer.resolve_instance(instance_name)
        if inst is None:
            self._status_bar.showMessage(f"No DEF instance matches {instance_name}", 5000)
            return
        box = inst.getBBox().getBox()
        self._viewer.zoomTo(box, animate=self._viewer.isVisible())
        self._viewer.selectInstance(inst, emit_signal=False)

        # Highlight cell with its exact IR-drop bin color and ping
        report = getattr(self._viewer, "_ir_drop_data", None)
        rec = None
        if report:
            rec = report.records_by_instance.get(instance_name)
            if rec is None:
                rec = report.records_by_instance.get(inst.getName())
            if rec is None:
                leaf = inst.getName().rsplit("/", 1)[-1]
                rec = report.records_by_instance.get(leaf)

        if rec is not None and report:
            drop_mv, cell_type = rec
            color_idx = report.color_index(drop_mv)
            bin_color = QColor(IR_DROP_PALETTE[color_idx])
            self._viewer.highlightObject(box, label=f"{inst.getName()} ({drop_mv:.1f} mV)", color=bin_color)
            self._viewer.pingLocation(box.center(), color=bin_color)
            self._status_bar.showMessage(
                f"IR-Drop Hotspot: {inst.getName()} | Drop: {drop_mv:.2f} mV | Cell: {cell_type} | Range: Bin {color_idx + 1}/5",
                6000,
            )
        else:
            self._viewer.highlightObject(box, label=f"{inst.getName()}")
            self._viewer.pingLocation(box.center(), color=QColor("#D8588A"))
            self._status_bar.showMessage(f"IR-drop hotspot: {inst.getName()}", 5000)

        # Ensure IR Drop dock remains raised and active
        if hasattr(self, "_ir_drop_dock") and self._ir_drop_dock is not None:
            self._ir_drop_dock.raise_()

    def _on_timing_path_selected(self, path: Any, zoom: bool) -> None:
        """Highlights selected timing path on chip layout canvas and optionally zooms."""
        self._viewer.highlightTimingPath(path, zoom=zoom)

    def _on_timing_paths_highlighted(self, paths: list) -> None:
        """Highlights multiple timing paths simultaneously on chip layout canvas."""
        self._viewer.highlightTimingPaths(paths)

    def _reset_dock_layout(self) -> None:
        """Restores the initial clean dock arrangement."""
        self.addDockWidget(Qt.LeftDockWidgetArea, self._controls)
        self.addDockWidget(Qt.RightDockWidgetArea, self._search_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, self._legend)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._timing_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._ir_drop_dock)
        self.tabifyDockWidget(self._timing_dock, self._ir_drop_dock)
        self.tabifyDockWidget(self._search_dock, self._inspector)
        self.tabifyDockWidget(self._inspector, self._legend)
        self._controls.setFloating(False)
        self._search_dock.setFloating(False)
        self._inspector.setFloating(False)
        self._legend.setFloating(False)
        self._timing_dock.setFloating(False)
        self._ir_drop_dock.setFloating(False)
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
        self._timing_dock.setFeatures(features)
        self._ir_drop_dock.setFeatures(features)
        state_str = "locked" if locked else "unlocked (movable & floatable)"
        self._status_bar.showMessage(f"Docks {state_str}", 3000)

    def close_design(self, silent: bool = False) -> None:
        """Closes the current design, halts render threads, clears spatial index and UI docks, and forces RAM release."""
        # 1. Stop background rendering thread and clear viewer
        if hasattr(self, "_viewer") and self._viewer is not None:
            if hasattr(self._viewer, "_render_thread") and self._viewer._render_thread is not None:
                self._viewer._render_thread.stop_render()
            self._viewer.setChip(None)

        # 2. Reset Docks
        if hasattr(self, "_timing_dock") and self._timing_dock is not None:
            self._timing_dock.clear()

        if hasattr(self, "_ir_drop_dock") and self._ir_drop_dock is not None:
            self._ir_drop_dock.clear()

        if hasattr(self, "_search_dock") and self._search_dock is not None:
            self._search_dock.clear()

        if hasattr(self, "_inspector") and self._inspector is not None:
            self._inspector.clear()

        if hasattr(self, "_controls") and self._controls is not None:
            self._controls.refresh()

        # 3. Reset internal files and DB
        self._lef_files = []
        self._def_file = None
        self._db = dbDatabase()

        # 4. Trigger garbage collection to immediately reclaim RAM
        import gc
        gc.collect()

        # 5. Reset UI title and status bar
        self.setWindowTitle("RISHI - Silicon Layout Viewer")
        if not silent:
            self._status_bar.showMessage("Design closed. Memory cleared. Ready to start fresh.", 5000)

    def closeEvent(self, event) -> None:
        """Safely terminates background rendering threads when window closes."""
        if hasattr(self, "_ir_drop_dock") and self._ir_drop_dock is not None:
            self._ir_drop_dock.get_widget().stop_loading()
        if hasattr(self, "_viewer") and self._viewer is not None:
            if hasattr(self._viewer, "_render_thread") and self._viewer._render_thread is not None:
                self._viewer._render_thread.exit_thread()
        super().closeEvent(event)

