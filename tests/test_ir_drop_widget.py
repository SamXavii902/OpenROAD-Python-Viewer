"""Tests for IR-drop report parsing and interactive visualization."""

import os

import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rishi.gui.irDropWidget import IRDropWidget
from rishi.gui.renderThread import RenderThread
from rishi.irdrop.report import IR_DROP_PALETTE, IRDropBin, IRDropParser, IRDropReportData
from rishi.odb.geom import Rect


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
    from unittest.mock import MagicMock
    from rishi.gui.layoutViewer import LayoutViewer
    from rishi.odb.geom import Point, Rect

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