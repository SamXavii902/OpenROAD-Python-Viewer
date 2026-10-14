"""Headless GUI tests for TimingReportWidget and TimingReportDock."""

import os
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from openroad_py.gui.timingReportWidget import (
    CategorySummaryWidget,
    OptimizationFailureReasonTable,
    PathCategoryTable,
    PathHistogramWidget,
    PathListTable,
    TimingReportDock,
    TimingReportWidget,
)
from openroad_py.gui.layoutViewer import LayoutViewer
from openroad_py.timing.tarpt_parser import TarptParser, TimingPath

TARPT_PATH = r"C:\High-Speed-LLM-using-RAG\data\ActualLogFiles\route_reg2reg.tarpt"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = QApplication([])
    return app


def test_histogram_widget_standalone(qapp):
    w = PathHistogramWidget()
    w.resize(400, 200)
    parser = TarptParser()
    sample_text = """Path 1: VIOLATED (-0.0100 ns) Setup Check with Pin u1/D
View: v1
Group: g1
Startpoint: p1
Endpoint: p2
Clock: c1
Required Time:= 1.0
Arrival:= 1.01
Slack:= -0.0100
Timing Path:
   0.0 - R (arrival) c1
"""
    report = parser.parse_text(sample_text)
    w.set_bins(report.histogram_bins)
    assert len(w._bins) > 0
    assert w.get_selected_bin() is None


def test_category_summary_widget(qapp):
    w = CategorySummaryWidget()
    w.resize(300, 200)
    parser = TarptParser()
    report = parser.parse_text("""Path 1: VIOLATED (-0.0100 ns) Setup Check with Pin u1/D
View: v1
Group: g1
Startpoint: p1
Endpoint: p2
Clock: c1
Required Time:= 1.0
Arrival:= 1.01
Slack:= -0.0100
Timing Path:
   0.0 - R (arrival) c1
""")
    w.set_stats(report.categories.get("all"))
    assert w._table.item(0, 1).text() == "all"
    assert w._table.item(1, 1).text() == "1"
    assert w._table.item(3, 1).text() == "1"  # Failing path


def test_path_list_table_columns_and_pagination(qapp):
    w = PathListTable()
    w.resize(800, 400)
    assert w._table.columnCount() == 11
    headers = [w._table.horizontalHeaderItem(i).text() for i in range(11)]
    assert headers == [
        "H", "Path", "Clock", "ReqTime", "Slack",
        "Logic Level", "Sum of Wire Length", "Startpoint Pin",
        "Endpoint Pin", "View", "Failure Reason"
    ]

    # Generate synthetic 75 paths to verify pagination
    synthetic_paths = [
        TimingPath(
            id=i + 1,
            slack=float(i - 20) / 100.0,
            required_time=10.0 + i,
            startpoint=f"inst{i}/Q",
            endpoint=f"inst{i+1}/D",
            launch_clock="clk_core",
            logic_level=i % 10,
        )
        for i in range(75)
    ]

    w.set_paths(synthetic_paths)
    assert w._table.rowCount() == 50  # First page default 50
    assert w._page_index == 0

    # Flip to next page
    w._go_next_page()
    assert w._page_index == 1
    assert w._table.rowCount() == 25  # Second page remaining 25

    # Flip back to prev page
    w._go_prev_page()
    assert w._page_index == 0
    assert w._table.rowCount() == 50


@pytest.mark.skipif(not os.path.exists(TARPT_PATH), reason="route_reg2reg.tarpt not found")
def test_timing_report_widget_full_load(qapp):
    widget = TimingReportWidget()
    widget.resize(1000, 600)
    widget.load_file(TARPT_PATH)

    assert widget._report_data is not None
    assert len(widget._report_data.paths) == 200

    # Verify badge chips
    assert "200 Paths" in widget._badge_paths.text()
    assert "-0.0087" in widget._badge_wns.text()
    assert "-0.0168" in widget._badge_tns.text()

    # Verify Path List Table
    assert len(widget._path_list._paths) == 200
    assert widget._path_list._table.rowCount() == 50

    # Verify search filter
    widget._search_input.setText("LOCKUP")
    assert len(widget._path_list._paths) < 200
    assert len(widget._path_list._paths) > 0

    # Reset search filter
    widget.reset_all_filters()
    assert len(widget._path_list._paths) == 200

    # Test histogram filter
    failing_bin = next((b for b in widget._report_data.histogram_bins if b.is_failing and b.count > 0), None)
    if failing_bin:
        widget._on_histogram_bin_selected(failing_bin)
        assert len(widget._path_list._paths) == failing_bin.count


def test_layout_viewer_timing_path_highlight(qapp):
    viewer = LayoutViewer()
    viewer.resize(800, 600)

    # Highlight path when no design is loaded (graceful no-op, no crash)
    p = TimingPath(id=1, slack=-0.01, startpoint="reg1/Q", endpoint="reg2/D")
    viewer.highlightTimingPath(p, zoom=True)
    assert viewer._active_timing_path == p
    assert viewer._timing_path_points == []

    viewer.highlightTimingPaths([p])
    assert viewer._multi_path_points == []

    viewer.clearTimingPaths()
    assert viewer._active_timing_path is None


def test_clear_all_highlights_button_and_signal(qapp):
    """Verifies that Clear All Highlights resets table checkboxes, selection, and emits paths_cleared."""
    widget = TimingReportWidget()
    widget.resize(800, 500)

    p1 = TimingPath(id=1, slack=-0.01, startpoint="reg1/Q", endpoint="reg2/D")
    p2 = TimingPath(id=2, slack=0.05, startpoint="reg2/Q", endpoint="reg3/D")
    widget._path_list.set_paths([p1, p2])

    # Highlight p1 and p2
    widget._path_list._highlighted_ids.add(1)
    widget._path_list._highlighted_ids.add(2)
    widget._path_list._refresh_page()
    assert len(widget._path_list._highlighted_ids) == 2

    cleared_emitted = []
    widget.paths_cleared.connect(lambda: cleared_emitted.append(True))

    selected_paths = []
    widget.path_selected.connect(lambda p, z: selected_paths.append(p))

    # Trigger clear all highlights
    widget.clear_all_highlights()

    assert len(widget._path_list._highlighted_ids) == 0
    assert len(cleared_emitted) == 1
    assert len(selected_paths) > 0
    assert selected_paths[-1] is None  # Emitted None to clear canvas active path


def test_table_row_selection_triggers_path_selected(qapp):
    """Verifies that selecting a row in the table fires path_selected for responsive clicking."""
    table_widget = PathListTable()
    table_widget.resize(800, 400)

    p1 = TimingPath(id=1, slack=-0.01, startpoint="reg1/Q", endpoint="reg2/D")
    p2 = TimingPath(id=2, slack=0.05, startpoint="reg2/Q", endpoint="reg3/D")
    table_widget.set_paths([p1, p2])

    emitted = []
    table_widget.path_selected.connect(lambda p, z: emitted.append(p))

    # Select second row
    table_widget._table.selectRow(1)
    assert len(emitted) > 0
    assert emitted[-1].id == 2


def test_tarpt_parser_callback_with_progress_and_elapsed(tmp_path):
    """Verifies progress callback receives stage, current, total, and elapsed time."""
    report_file = tmp_path / "test.tarpt"
    content = """Path 1: VIOLATED (-0.0050 ns) Setup Check
View: func_max
Group: clk_main
Startpoint: reg1/CP
Endpoint: reg2/D
Clock: clk_main
Required Time:= 1.2000
Arrival:= 1.2050
Slack:= -0.0050
Timing Path:
   0.0000 - R clk_main
"""
    report_file.write_text(content, encoding="utf-8")

    callbacks = []
    def on_progress(stage, cur, total, detail):
        callbacks.append((stage, cur, total, detail))

    parser = TarptParser()
    rep = parser.parse_file(str(report_file), callback=on_progress)
    assert len(rep.paths) == 1
    assert len(callbacks) > 0
    # Last callback should indicate completion and elapsed time
    last_stage, last_cur, last_total, last_detail = callbacks[-1]
    assert "Complete" in last_stage
    assert "elapsed" in last_detail.lower() or "loaded" in last_detail.lower()


def test_layout_viewer_mbit_alias_resolution(qapp):
    """Verifies LayoutViewer maps multi-bit CDN_MBIT_ register names to physical instances."""
    from openroad_py.odb.database import dbDatabase, dbChip
    from openroad_py.odb.block import dbBlock, dbInst
    from openroad_py.odb.lib import dbMaster
    from openroad_py.odb.tech import dbTech
    from openroad_py.odb.geom import Rect, Point
    from openroad_py.odb.types import dbPlacementStatus

    db = dbDatabase()
    tech = dbTech(1000)
    db.setTech(tech)
    block = dbBlock(tech, "mockBlock")
    block.setDieArea(Rect(0, 0, 100000, 100000))
    chip = dbChip(db, block)

    master = dbMaster("DFF_X1")
    master.setWidth(2000)
    master.setHeight(3000)
    # Multi-bit instance combining regA and regB
    mbit_inst = dbInst(block, master, "top/cpu/CDN_MBIT_regA_MB_regB")
    mbit_inst.setOrigin(25000, 35000)
    mbit_inst.setPlacementStatus(dbPlacementStatus.PLACED)
    block.addInst(mbit_inst)

    viewer = LayoutViewer()
    viewer.resize(600, 600)
    viewer.setChip(chip)

    # Path referencing logical register names
    path = TimingPath(id=1, slack=-0.02, startpoint="top/cpu/regA/CP", endpoint="top/cpu/regB/D")
    pts = viewer._resolve_timing_path_points(path)

    # Should resolve via MBIT alias!
    assert len(pts) >= 1
    # Center of [25000, 35000] to [27000, 38000] is (26000, 36500)
    assert pts[0].x == 26000
    assert pts[0].y == 36500


def test_layout_viewer_hud_badge_and_single_point_render(qapp):
    """Verifies that _draw_timing_paths renders cleanly for both 1-point and 2-point paths."""
    from PySide6.QtGui import QPainter, QImage
    from openroad_py.odb.geom import Point

    viewer = LayoutViewer()
    viewer.resize(800, 600)
    p = TimingPath(id=1, slack=-0.0087, startpoint="reg1/CP", endpoint="reg2/D")

    # 1-point path
    viewer._active_timing_path = p
    viewer._timing_path_points = [Point(1000, 2000)]
    img = QImage(800, 600, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    try:
        viewer._draw_timing_paths(painter)
    finally:
        painter.end()

    # 2-point path
    viewer._timing_path_points = [Point(1000, 2000), Point(5000, 8000)]
    painter2 = QPainter(img)
    try:
        viewer._draw_timing_paths(painter2)
    finally:
        painter2.end()


def test_manhattan_wirelength_computation(qapp):
    """Verifies Manhattan wire length fallback is computed in microns when nets are unrouted."""
    from openroad_py.odb.database import dbDatabase, dbChip
    from openroad_py.odb.block import dbBlock, dbInst
    from openroad_py.odb.lib import dbMaster
    from openroad_py.odb.tech import dbTech
    from openroad_py.odb.geom import Rect
    from openroad_py.odb.types import dbPlacementStatus
    from openroad_py.timing.tarpt_parser import TimingReportData

    db = dbDatabase()
    tech = dbTech(1000)  # 1000 dbu per micron
    db.setTech(tech)
    block = dbBlock(tech, "mockBlock")
    block.setDieArea(Rect(0, 0, 1000000, 1000000))
    chip = dbChip(db, block)

    master = dbMaster("BUF_X1")
    master.setWidth(1000)
    master.setHeight(2000)

    # Place 3 cells: i1 at (0, 0), i2 at (30000, 40000), i3 at (70000, 70000)
    i1 = dbInst(block, master, "u1")
    i1.setOrigin(0, 0)
    i1.setPlacementStatus(dbPlacementStatus.PLACED)
    block.addInst(i1)

    i2 = dbInst(block, master, "u2")
    i2.setOrigin(30000, 40000)
    i2.setPlacementStatus(dbPlacementStatus.PLACED)
    block.addInst(i2)

    i3 = dbInst(block, master, "u3")
    i3.setOrigin(70000, 70000)
    i3.setPlacementStatus(dbPlacementStatus.PLACED)
    block.addInst(i3)

    path = TimingPath(
        id=1,
        slack=-0.05,
        startpoint="u1/Q",
        endpoint="u3/D",
        cells=[("BUF_X1", "u2/A"), ("BUF_X1", "u2/Y")],
    )

    report_data = TimingReportData()
    report_data.paths = [path]
    report_data.compute_wire_lengths(chip)

    # Distance: |30000-0| + |40000-0| = 70000 dbu = 70 µm
    # Plus: |70000-30000| + |70000-40000| = 70000 dbu = 70 µm
    # Total = 140 µm
    assert path.sum_wire_length is not None
    assert abs(path.sum_wire_length - 140.0) < 5.0


def test_tables_resizable_headers_and_widths(qapp):
    """Verifies that all tables use QHeaderView.Interactive and have wide columns."""
    from PySide6.QtWidgets import QHeaderView

    # PathListTable
    plt = PathListTable()
    h = plt._table.horizontalHeader()
    for col in range(11):
        assert h.sectionResizeMode(col) == QHeaderView.Interactive
    # Startpoint Pin (col 7) and Endpoint Pin (col 8) should default to >= 250px
    assert plt._table.columnWidth(7) >= 250
    assert plt._table.columnWidth(8) >= 250

    # PathCategoryTable
    pct = PathCategoryTable()
    h_pct = pct._table.horizontalHeader()
    for col in range(pct._table.columnCount()):
        assert h_pct.sectionResizeMode(col) == QHeaderView.Interactive

    # OptimizationFailureReasonTable
    ofr = OptimizationFailureReasonTable()
    h_ofr = ofr._table.horizontalHeader()
    for col in range(ofr._table.columnCount()):
        assert h_ofr.sectionResizeMode(col) == QHeaderView.Interactive

    # CategorySummaryWidget
    csw = CategorySummaryWidget()
    h_csw = csw._table.horizontalHeader()
    assert h_csw.sectionResizeMode(0) == QHeaderView.Interactive


def test_clipboard_copy_and_tooltips(qapp):
    """Verifies Ctrl+C copying from CopyableTableWidget and cell tooltips."""
    from PySide6.QtGui import QKeySequence, QKeyEvent
    from PySide6.QtCore import QEvent

    plt = PathListTable()
    p = TimingPath(
        id=42,
        slack=-0.015,
        required_time=2.5,
        arrival_time=2.515,
        startpoint="long/hierarchical/name/regA/CP",
        endpoint="long/hierarchical/name/regB/D",
        launch_clock="clk_core",
        capture_clock="clk_core",
        logic_level=4,
        sum_wire_length=123.45,
        failure_reason="Setup Check",
    )
    plt.set_paths([p])

    # Check tooltips
    item_start = plt._table.item(0, 7)
    assert item_start.toolTip() == "long/hierarchical/name/regA/CP"
    item_end = plt._table.item(0, 8)
    assert item_end.toolTip() == "long/hierarchical/name/regB/D"
    item_slack = plt._table.item(0, 4)
    assert "-0.0150" in item_slack.toolTip()

    # Check copy selection to clipboard
    plt._table.clearSelection()
    item_start.setSelected(True)
    plt._table.copy_selection_to_clipboard()
    cb_text = QApplication.clipboard().text()
    assert cb_text == "long/hierarchical/name/regA/CP"


def test_timing_report_upper_splitter(qapp):
    """Verifies that Histogram and Category Summary are placed in a resizable QSplitter."""
    from PySide6.QtWidgets import QSplitter

    trw = TimingReportWidget()
    trw.resize(900, 600)
    # Find child splitters
    splitters = trw.findChildren(QSplitter)
    # Should have main vertical splitter and upper horizontal splitter
    assert len(splitters) >= 2
    horizontal_splitters = [s for s in splitters if s.orientation() == Qt.Horizontal]
    assert len(horizontal_splitters) >= 1
    # Check that children of horizontal splitter are hist_box and summary_box
    upper = horizontal_splitters[0]
    assert upper.count() == 2


