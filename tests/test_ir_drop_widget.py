import os
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rishi.gui.irDropWidget import IRDropWidget
from rishi.gui.layoutViewer import LayoutViewer
from rishi.gui.mainWindow import MainWindow
from rishi.gui.renderThread import RenderThread
from rishi.irdrop.report import IR_DROP_PALETTE, IRDropBin, IRDropParser, IRDropReportData
from rishi.odb.geom import Point, Rect


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_ir_drop_parser_uses_ideal_minus_simulated_voltage(tmp_path):
    report = tmp_path / "ir_drop.rpt"
    report.write_text(
        """# min_pg_sim ideal_voltage instance
0.7935 0.8903 0.7935 0 10 20 0.93 vdd/gnd CELL_X1 top/u1
0.8000 0.8903 0.8000 0 10 20 0.93 vdd/gnd CELL_X1 top/u1
0.8500 0.9000 0.8500 0 10 20 0.92 vdd/gnd CELL_X2 top/u2
""",
        encoding="utf-8",
    )

    data = IRDropParser().parse_file(str(report))

    assert data.record_count == 3
    assert data.instance_count == 2
    assert data.values_by_instance["top/u1"] == 136.5
    assert data.values_by_instance["top/u2"] == 70.0
    assert data.ordered_instances == ["top/u1", "top/u2"]
    assert data.minimum_mv == 70.0
    assert data.maximum_mv == 136.5
    assert data.percentile_95_mv == 133.175


def test_ir_drop_widget_filters_and_emits_navigation(qapp, tmp_path):
    report = tmp_path / "ir_drop.rpt"
    report.write_text(
        """0.7935 0.8903 0.7935 0 10 20 0.93 vdd/gnd CELL_X1 top/u1
0.8500 0.9000 0.8500 0 10 20 0.92 vdd/gnd CELL_X2 top/u2
""",
        encoding="utf-8",
    )
    data = IRDropParser().parse_file(str(report))
    widget = IRDropWidget()
    widget.resize(1000, 600)
    widget.set_report_data(data)

    assert widget._instance_table.rowCount() == 2
    assert widget._cell_table.rowCount() == 2
    assert widget._metric_labels["count"].text() == "2"

    map_states = []
    selected_instances = []
    widget.map_visibility_changed.connect(map_states.append)
    widget.instance_selected.connect(selected_instances.append)
    widget._map_toggle.setChecked(True)
    assert map_states == [True]

    widget._search.setText("top/u1")
    assert widget._instance_table.rowCount() == 1
    assert widget._instance_table.item(0, 2).text() == "top/u1"
    widget._on_instance_row_clicked(0, 2)
    assert selected_instances == ["top/u1"]

    widget._search.clear()
    widget._threshold.setValue(100.0)
    widget._threshold_toggle.setChecked(True)
    assert widget._instance_table.rowCount() == 1
    assert widget._instance_table.item(0, 2).text() == "top/u1"

    widget._threshold_toggle.setChecked(False)
    low_bin = next(item for item in data.bins if item.count)
    widget._on_bin_selected(low_bin)
    assert widget._instance_table.rowCount() == 1
    assert widget._instance_table.item(0, 2).text() == "top/u2"
    widget.close()


def test_ir_drop_overlay_colors_standard_cells_only(qapp):
    report = IRDropReportData(
        records_by_instance={"top/cell": (100.0, "CELL_X1"), "top/macro": (100.0, "MACRO_X1")},
        minimum_mv=0.0,
        maximum_mv=100.0,
        bins=[IRDropBin(0.0, 100.0, 2)],
    )

    class FakeMaster:
        def __init__(self, macro):
            self._macro = macro

        def isMacro(self):
            return self._macro

    class FakeBox:
        def __init__(self, rect):
            self._rect = rect

        def getBox(self):
            return self._rect

    class FakeInstance:
        def __init__(self, name, macro, rect):
            self._name = name
            self._master = FakeMaster(macro)
            self._bbox = FakeBox(rect)

        def getName(self):
            return self._name

        def getMaster(self):
            return self._master

        def getBBox(self):
            return self._bbox

    image = QImage(40, 24, QImage.Format_ARGB32_Premultiplied)
    background = QColor("#101010")
    image.fill(background)
    painter = QPainter(image)
    renderer = RenderThread(type("Viewer", (), {"_ir_drop_data": report})())
    renderer.drawIRDropOverlay(
        painter,
        [
            FakeInstance("top/cell", False, Rect(2, 2, 14, 14)),
            FakeInstance("top/macro", True, Rect(20, 2, 34, 14)),
        ],
    )
    painter.end()

    assert image.pixelColor(8, 8) != background
    assert image.pixelColor(26, 8) == background


def test_ir_drop_precomputed_bins_and_instant_filtering(tmp_path):
    report_file = tmp_path / "test_report.rpt"
    report_file.write_text(
        """0.8000 0.9000 0.8000 0 10 20 0.90 vdd/gnd INV_X1 top/u_inv
0.7500 0.9000 0.7500 0 10 20 0.90 vdd/gnd BUF_X2 top/u_buf
0.8800 0.9000 0.8800 0 10 20 0.90 vdd/gnd NAND2_X1 top/u_nand
""",
        encoding="utf-8",
    )
    data = IRDropParser().parse_file(str(report_file))
    assert hasattr(data, "bin_instances")
    assert len(data.bin_instances) == IRDropParser.HISTOGRAM_BIN_COUNT
    assert hasattr(data, "palette_bin_instances")
    assert len(data.palette_bin_instances) == len(IR_DROP_PALETTE)
    assert "INV_X1" in data.instances_by_cell_type
    assert "top/u_inv" in data.instances_by_cell_type["INV_X1"]

    widget = IRDropWidget()
    widget.set_report_data(data)
    # Fast path: instant bin selection
    high_bin = next(b for b in data.bins if b.count > 0)
    widget._on_bin_selected(high_bin)
    assert len(widget._filtered_instances) == high_bin.count
    widget.close()


def test_ir_drop_heatmap_raster_and_probe(qapp):
    report = IRDropReportData(
        records_by_instance={"top/cell_a": (120.0, "BUF_X1"), "top/cell_b": (30.0, "INV_X1")},
        ordered_instances=["top/cell_a", "top/cell_b"],
        minimum_mv=30.0,
        maximum_mv=120.0,
        bins=[IRDropBin(30.0, 120.0, 2)],
    )

    viewer = LayoutViewer()
    block = MagicMock()
    core = Rect(0, 0, 100000, 100000)
    block.getCoreArea.return_value = core
    block.getDieArea.return_value = core
    block.getRows.return_value = []

    inst_a = MagicMock()
    inst_a.getName.return_value = "top/cell_a"
    inst_a.isPlaced.return_value = True
    bbox_a = MagicMock()
    bbox_a.getBox.return_value = Rect(20000, 20000, 30000, 30000)
    inst_a.getBBox.return_value = bbox_a

    block.getInsts.return_value = [inst_a]

    chip = MagicMock()
    chip.getBlock.return_value = block
    block.findInst.side_effect = lambda name: inst_a if name in ("top/cell_a", "cell_a") else None
    viewer._chip = chip
    viewer.setIRDropData(report)
    viewer.setIRDropMapVisible(True)

    # Ensure heatmap image is rasterized
    viewer._ensure_ir_drop_heatmap()
    assert viewer._ir_drop_heatmap_image is not None
    assert not viewer._ir_drop_heatmap_image.isNull()

    # Test coordinate probe
    probe_hit = viewer.getIRDropAt(Point(25000, 25000))
    assert probe_hit is not None
    drop_val, inst_name = probe_hit
    assert drop_val > 0

    viewer.close()


def test_ir_drop_parser_sanitizes_pin_suffixes(tmp_path):
    report = tmp_path / "ir_pins.rpt"
    report.write_text(
        """0.7935 0.8903 0.7935 0 10 20 0.93 vdd/gnd CELL_X1 u_core/inst_a:VDD
0.8000 0.8903 0.8000 0 10 20 0.93 vdd/gnd CELL_X1 u_core/inst_b/VSS
0.8500 0.9000 0.8500 0 10 20 0.92 vdd/gnd CELL_X2 u_core/inst_c
""",
        encoding="utf-8",
    )
    data = IRDropParser().parse_file(str(report))
    assert "u_core/inst_a" in data.records_by_instance
    assert "u_core/inst_b" in data.records_by_instance
    assert "u_core/inst_c" in data.records_by_instance


def test_layout_viewer_resolve_instance(qapp):
    viewer = LayoutViewer()
    block = MagicMock()

    inst1 = MagicMock()
    inst1.getName.return_value = r"u_cpu/reg\[0\]"
    inst2 = MagicMock()
    inst2.getName.return_value = "u_cpu/alu"

    inst_map = {
        r"u_cpu/reg\[0\]": inst1,
        "u_cpu/alu": inst2,
    }
    block.findInst.side_effect = lambda n: inst_map.get(n)
    block.getInsts.return_value = [inst1, inst2]

    chip = MagicMock()
    chip.getBlock.return_value = block
    viewer._chip = chip

    # Escaped bracket resolution
    assert viewer.resolve_instance("u_cpu/reg[0]") is inst1
    # Pin suffix resolution
    assert viewer.resolve_instance("u_cpu/alu:VDD") is inst2
    # Slash pin suffix resolution
    assert viewer.resolve_instance("u_cpu/alu/VDD") is inst2
    # Prefix stripping resolution
    assert viewer.resolve_instance("top/u_cpu/alu") is inst2
    # Escaped prefix stripping resolution
    assert viewer.resolve_instance("top/u_cpu/reg[0]") is inst1
    # Cached resolution
    assert viewer.resolve_instance("u_cpu/reg[0]") is inst1

    viewer.close()


def test_ir_drop_heatmap_empty_guard(qapp):
    viewer = LayoutViewer()
    block = MagicMock()
    core = Rect(0, 0, 100000, 100000)
    block.getCoreArea.return_value = core
    block.getDieArea.return_value = core
    block.findInst.return_value = None
    block.getInsts.return_value = []

    chip = MagicMock()
    chip.getBlock.return_value = block
    viewer._chip = chip

    report = IRDropReportData(
        records_by_instance={"missing_inst": (120.0, "BUF_X1")},
        minimum_mv=0.0,
        maximum_mv=120.0,
    )
    viewer.setIRDropData(report)

    # First attempt: should detect no placed matching instances and set guard
    viewer._ensure_ir_drop_heatmap()
    assert viewer._ir_drop_heatmap_attempted is True
    assert viewer._ir_drop_heatmap_image is not None
    assert viewer._ir_drop_heatmap_image.isNull()

    # Second call should immediately return without reprocessing
    viewer._ensure_ir_drop_heatmap()
    assert viewer._ir_drop_heatmap_attempted is True

    viewer.close()


def test_ir_drop_navigation_keeps_dock_raised(qapp):
    win = MainWindow()
    mock_inst = MagicMock()
    mock_inst.getName.return_value = "u_cpu/hotspot"
    bbox = MagicMock()
    bbox.getBox.return_value = Rect(100, 100, 200, 200)
    mock_inst.getBBox.return_value = bbox

    win._viewer.resolve_instance = MagicMock(return_value=mock_inst)
    win._viewer.hasDesign = MagicMock(return_value=True)
    win._viewer.selectInstance = MagicMock()
    win._viewer.zoomTo = MagicMock()
    win._inspector.inspect_instance = MagicMock()
    win._inspector.raise_ = MagicMock()
    win._ir_drop_dock.raise_ = MagicMock()

    win._on_ir_drop_instance_selected("u_cpu/hotspot")

    # Inspector must NOT be inspected or raised
    win._inspector.inspect_instance.assert_not_called()
    win._inspector.raise_.assert_not_called()

    # selectInstance called with emit_signal=False so inspector is not raised via signal
    win._viewer.selectInstance.assert_called_with(mock_inst, emit_signal=False)

    # IR Drop dock must be raised
    win._ir_drop_dock.raise_.assert_called()

    win.close()


def test_ir_drop_standard_cells_colored_when_map_active(qapp):
    report = IRDropReportData(
        records_by_instance={"top/cell_hotspot": (140.0, "BUF_X4")},
        ordered_instances=["top/cell_hotspot"],
        minimum_mv=0.0,
        maximum_mv=140.0,
        bins=[IRDropBin(0.0, 140.0, 1)],
    )

    class FakeMaster:
        def isMacro(self):
            return False
        def getHeight(self):
            return 1000
        def getWidth(self):
            return 1000
        def getPlacementBoundary(self):
            return Rect(0, 0, 1000, 1000)

    class FakeInst:
        def __init__(self, name, rect):
            self._name = name
            self._rect = rect
            self._master = FakeMaster()
        def getName(self):
            return self._name
        def getMaster(self):
            return self._master
        def getBBox(self):
            class BBoxWrapper:
                def __init__(self, r): self._r = r
                def getBox(self): return self._r
            return BBoxWrapper(self._rect)
        def getTransform(self):
            return None

    inst_hotspot = FakeInst("top/cell_hotspot", Rect(2, 2, 10, 10))
    inst_other = FakeInst("top/cell_other", Rect(12, 2, 20, 10))

    class FakeOptions:
        def areStandardCellsVisible(self): return True
        def areMacrosVisible(self): return True
        def cellColor(self): return QColor(120, 120, 120)
        def macroBorderColor(self): return QColor(200, 200, 200)
        def macroColor(self): return QColor(50, 50, 50)

    class FakeViewer:
        def __init__(self):
            self._options = FakeOptions()
            self._ir_drop_data = report
            self._ir_drop_map_visible = False
            self.pixels_per_dbu = 1.0
            self._restart = False
            self._ir_drop_name_to_bin = {"top/cell_hotspot": 4}
            self._ir_drop_leaf_to_bin = {"cell_hotspot": 4}
        def getOptions(self): return self._options
        def nominalViewableResolution(self): return 100

    viewer = FakeViewer()
    renderer = RenderThread(viewer)

    # 1. Default mode: IR drop map OFF -> standard cells drawn with normal grey cell_pen and Qt.NoBrush
    image_default = QImage(30, 20, QImage.Format_ARGB32_Premultiplied)
    image_default.fill(QColor(0, 0, 0))
    p_default = QPainter(image_default)
    renderer.drawInstanceOutlines(p_default, [inst_hotspot, inst_other])
    p_default.end()

    # The interior of the cell (at 5, 5) must be empty (Qt.NoBrush)
    assert image_default.pixelColor(5, 5) == QColor(0, 0, 0)
    # The outline of the cell must be greyish options.cellColor()
    assert image_default.pixelColor(2, 2) == QColor(120, 120, 120)

    # 2. IR drop map ON -> cell_hotspot must be filled with IR drop bin 4 palette color (#D8588A)
    viewer._ir_drop_map_visible = True
    image_ir = QImage(30, 20, QImage.Format_ARGB32_Premultiplied)
    image_ir.fill(QColor(0, 0, 0))
    p_ir = QPainter(image_ir)
    renderer.drawInstanceOutlines(p_ir, [inst_hotspot, inst_other])
    p_ir.end()

    expected_color = QColor(IR_DROP_PALETTE[4])
    # The interior of cell_hotspot must now be filled with IR drop color!
    assert image_ir.pixelColor(5, 5) == expected_color

    # Meanwhile cell_other without IR drop data remains un-filled
    assert image_ir.pixelColor(15, 5) == QColor(0, 0, 0)
    assert image_ir.pixelColor(12, 2) == QColor(120, 120, 120)


def test_ir_drop_drawchip_queries_standard_cells(qapp):
    report = IRDropReportData(
        records_by_instance={"top/u_cell": (100.0, "INV_X1")},
        ordered_instances=["top/u_cell"],
        minimum_mv=0.0,
        maximum_mv=100.0,
        bins=[IRDropBin(0.0, 100.0, 1)],
    )

    class FakeOptions:
        def areStandardCellsVisible(self): return False  # Intentionally toggled off in options
        def areMacrosVisible(self): return True
        def areInstancesVisible(self): return False  # Intentionally toggled off in options
        def areInstanceOutlinesVisible(self): return False
        def areBlockagesVisible(self): return False
        def areRowsVisible(self): return False
        def areInstanceNamesVisible(self): return False
        def areIOPinsVisible(self): return False
        def isDieBoundaryVisible(self): return False
        def isCoreBoundaryVisible(self): return False
        def isPolygonBoundaryVisible(self): return False
        def cellColor(self): return QColor(120, 120, 120)
        def macroBorderColor(self): return QColor(200, 200, 200)
        def macroColor(self): return QColor(50, 50, 50)

    class FakeSearch:
        def __init__(self):
            self.last_query = {}
        def searchInsts(self, block, xMin, yMin, xMax, yMax, min_size=0, show_std_cells=True, show_macros=True):
            self.last_query = {
                "min_size": min_size,
                "show_std_cells": show_std_cells,
                "show_macros": show_macros,
            }
            return []

    class FakeBlock:
        def getDieArea(self): return Rect(0, 0, 1000, 1000)
        def getCoreArea(self): return Rect(0, 0, 1000, 1000)
        def getRows(self): return []
        def getTech(self): return None

    class FakeViewer:
        def __init__(self):
            self._options = FakeOptions()
            self._search = FakeSearch()
            self._ir_drop_data = report
            self._ir_drop_map_visible = True
            self.pixels_per_dbu = 0.002
            self._restart = False
            self._ir_drop_name_to_bin = {"top/u_cell": 2}
            self._ir_drop_leaf_to_bin = {"u_cell": 2}
        def getOptions(self): return self._options
        def getSearch(self): return self._search
        def instanceSizeLimit(self): return 5000
        def nominalViewableResolution(self): return 100

    viewer = FakeViewer()
    renderer = RenderThread(viewer)
    renderer.drawInstanceOutlines = MagicMock()

    dummy_img = QImage(10, 10, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(dummy_img)
    gui_painter = MagicMock()
    renderer.drawChip(painter, FakeBlock(), Rect(0, 0, 1000, 1000), gui_painter)
    painter.end()

    # Verify searchInsts was called with standard cells forced visible while preserving instanceSizeLimit
    # so zoomed-out views do not flood drawLayer with hundreds of thousands of sub-5px standard cells.
    assert viewer._search.last_query["show_std_cells"] is True
    assert viewer._search.last_query["min_size"] == 5000
    # drawInstanceOutlines must have been invoked
    renderer.drawInstanceOutlines.assert_called_once()


def test_ir_drop_progressive_lod_overlay_scales_from_zoom_out_to_zoom_in(qapp):
    import numpy as np

    report = IRDropReportData(
        records_by_instance={"top/u_0": (20.0, "INV_X1"), "top/u_1": (120.0, "BUF_X4")},
        ordered_instances=["top/u_1", "top/u_0"],
        minimum_mv=0.0,
        maximum_mv=140.0,
        bins=[IRDropBin(0.0, 140.0, 2)],
    )

    class FakeInst:
        def __init__(self, name):
            self._name = name
        def getName(self):
            return self._name

    class FakeSearch:
        def __init__(self):
            self._insts = [FakeInst("top/u_0"), FakeInst("top/u_1")]
            self._inst_boxes = np.array([[2, 2, 10, 10], [14, 2, 22, 10]], dtype=np.int32)
            self._inst_is_macro = np.array([False, False], dtype=bool)
            self._inst_is_filler = np.array([False, False], dtype=bool)

    viewer = LayoutViewer()
    viewer._search = FakeSearch()
    viewer.setIRDropData(report)
    viewer.setIRDropMapVisible(True)
    viewer.pixels_per_dbu = 1.0

    renderer = RenderThread(viewer)
    img = QImage(30, 20, QImage.Format_ARGB32_Premultiplied)
    bg = QColor("#101010")
    img.fill(bg)
    painter = QPainter(img)
    renderer.drawIRDropOverlay(painter, [], bounds=Rect(0, 0, 30, 20))
    painter.end()

    # Both standard cells in bounds are colored via the fast vectorized LOD path
    assert img.pixelColor(6, 6) != bg
    assert img.pixelColor(18, 6) != bg
    # Instance bin cache array was populated
    assert viewer._ir_drop_inst_bins is not None
    assert int(viewer._ir_drop_inst_bins[0]) >= 0
    assert int(viewer._ir_drop_inst_bins[1]) >= 0
    viewer.close()