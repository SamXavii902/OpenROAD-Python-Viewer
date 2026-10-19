"""Tests for MainWindow timing dock integration."""

import os
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QApplication

from rishi.gui.mainWindow import MainWindow
from rishi.timing.tarpt_parser import TimingPath
from rishi.odb.geom import Rect

TARPT_PATH = r"C:\High-Speed-LLM-using-RAG\data\ActualLogFiles\route_reg2reg.tarpt"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = QApplication([])
    return app


def test_mainwindow_timing_dock_integration(qapp):
    win = MainWindow()
    win.resize(1200, 800)
    win.show()

    # Timing dock exists
    assert hasattr(win, "_timing_dock")
    assert win._timing_dock is not None
    assert hasattr(win, "_ir_drop_dock")
    assert not win._ir_drop_dock.isVisible()

    win._toggle_ir_drop_dock()
    assert win._ir_drop_dock.isVisible()
    win._toggle_ir_drop_dock()
    assert not win._ir_drop_dock.isVisible()

    win._ir_drop_dock.get_widget().set_map_visible(True)
    assert win._ir_drop_map_act.isChecked()
    win._ir_drop_dock.get_widget().set_map_visible(False)
    assert not win._ir_drop_map_act.isChecked()

    # Toggle debugger method
    assert not win._timing_dock.isVisible()
    win._toggle_timing_debugger()
    assert win._timing_dock.isVisible()
    win._toggle_timing_debugger()
    assert not win._timing_dock.isVisible()

    # Reset dock layout includes timing dock
    win._reset_dock_layout()
    assert win._timing_dock is not None

    # Load synthetic report into dock
    dock = win._timing_dock
    w = dock.get_widget()
    sample_text = """Path 1: VIOLATED (-0.0100 ns) Setup Check with Pin reg1/D
View: v1
Group: reg2reg
Startpoint: reg0/CP
Endpoint: reg1/D
Clock: clk
Required Time:= 10.0
Arrival:= 10.01
Slack:= -0.0100
Timing Path:
   0.0 - R (arrival) clk
"""
    report = w._parser.parse_text(sample_text)
    w.set_report_data(report)
    assert len(w._report_data.paths) == 1

    # Simulate path selection signal to layout viewer
    p = report.paths[0]
    win._on_timing_path_selected(p, zoom=False)
    assert win._viewer._active_timing_path == p

    # Clean up
    win.close()


def test_ir_drop_hotspot_uses_animated_layout_navigation(qapp):
    win = MainWindow()
    win.show()
    box = Rect(100, 200, 300, 500)
    instance = MagicMock()
    instance.getBBox.return_value.getBox.return_value = box
    block = MagicMock()
    block.findInst.return_value = instance
    chip = MagicMock()
    chip.getBlock.return_value = block

    with (
        patch.object(win._viewer, "hasDesign", return_value=True),
        patch.object(win._viewer, "getChip", return_value=chip),
        patch.object(win._viewer, "zoomTo") as zoom_to,
        patch.object(win._viewer, "selectInstance") as select_instance,
        patch.object(win._inspector, "inspect_instance") as inspect_instance,
    ):
        win._on_ir_drop_instance_selected("top/u_hotspot")

    zoom_to.assert_called_once_with(box, animate=True)
    select_instance.assert_called_once_with(instance)
    inspect_instance.assert_called_once_with(instance)
    win.close()
