import os
import pytest
from PySide6.QtWidgets import QApplication, QDockWidget
from rishi.gui.mainWindow import MainWindow


@pytest.fixture(scope="module")
def main_win():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()


def test_mainwindow_docks_and_customization(main_win):
    assert main_win.isDockNestingEnabled()
    assert main_win._controls is not None
    assert main_win._inspector is not None
    assert main_win._legend is not None

    # Verify dock titles
    assert "Display Control" in main_win._controls.windowTitle()
    assert "Design Inspector" in main_win._inspector.windowTitle()
    assert "Legend" in main_win._legend.windowTitle()

    # Verify features: movable, floatable, closable
    features = main_win._controls.features()
    assert features & QDockWidget.DockWidgetMovable
    assert features & QDockWidget.DockWidgetFloatable
    assert features & QDockWidget.DockWidgetClosable

    # Verify reset layout
    main_win._reset_dock_layout()

    # Verify lock/unlock
    main_win._toggle_lock_docks(True)
    assert main_win._controls.features() == QDockWidget.NoDockWidgetFeatures
    main_win._toggle_lock_docks(False)
    assert main_win._controls.features() & QDockWidget.DockWidgetMovable

    # Verify Search dock
    assert main_win._search_dock is not None
    assert "Search" in main_win._search_dock.windowTitle()

    # Verify Ruler measurement mode
    viewer = main_win._viewer
    assert not viewer.isRulerMode()
    viewer.toggleRulerMode()
    assert viewer.isRulerMode()
    viewer.clearRulers()
    viewer.setRulerMode(False)
    assert not viewer.isRulerMode()


def test_inspector_and_search_indexing(main_win):
    """Verifies that loading a design populates inspector and search index without errors."""
    from rishi.odb.database import dbDatabase
    from rishi.lefin import LefParser
    from rishi.defin import DefParser

    db = dbDatabase()
    lp = LefParser(db)
    lp.parse_file("designs/Nangate45/Nangate45_tech.lef")
    lp.parse_file("designs/Nangate45/Nangate45_stdcell.lef")
    dp = DefParser(db)
    dp.parse_file("designs/gcd/gcd_nangate45_route.def")
    chip = db.getChip()

    # Test InspectorDock update_design - must not throw AttributeError on dbTech
    main_win._viewer.setChip(chip)
    main_win._inspector.update_design(chip)
    assert main_win._inspector._tree.topLevelItemCount() >= 4

    # Test SearchDock indexing
    main_win._search_dock.setChip(chip)
    assert len(main_win._search_dock._cached_items) > 0

    # Test search query execution
    main_win._search_dock._search_input.setText("clk")
    main_win._search_dock._execute_search()
    assert main_win._search_dock._results_list.count() > 0


def test_search_multiselect_and_toggle_deselect(main_win):
    """Verifies that search results can be multi-selected and toggled off on click."""
    search_dock = main_win._search_dock
    search_dock._search_input.setText("_")
    search_dock._execute_search()
    list_w = search_dock._results_list
    assert list_w.count() >= 2

    # First click selects item0
    item0 = list_w.item(0)
    item1 = list_w.item(1)
    item0.setSelected(True)
    search_dock._on_item_clicked(item0)
    assert item0.isSelected()
    assert len(search_dock.get_selected_items()) >= 1

    # Second click on item0 deselects it and clears highlight
    search_dock._on_item_clicked(item0)
    assert not item0.isSelected()

    # Multi-selection test
    item0.setSelected(True)
    item1.setSelected(True)
    items = search_dock.get_selected_items()
    assert len(items) == 2
    main_win._on_search_objects_selected(items)
    assert len(main_win._viewer._highlight_items) == 2


def test_instance_selection_and_inspector_details(main_win):
    """Verifies viewport instance selection, flightlines generation, and inspector property card."""
    viewer = main_win._viewer
    chip = viewer.getChip()
    assert chip is not None
    block = chip.getBlock()
    insts = block.getInsts()
    assert len(insts) > 0

    first_inst = insts[0]
    viewer.selectInstance(first_inst)
    assert viewer._selected_inst == first_inst
    assert len(viewer._highlight_items) == 1

    # Inspector shows Selected Instance group
    main_win._on_instance_selected(first_inst)
    assert main_win._inspector._selected_item_grp is not None
    assert main_win._inspector._selected_item_grp.text(0) == "Selected Instance"
    assert main_win._inspector._selected_item_grp.text(1) == first_inst.getName()

    # Deselect instance
    viewer.selectInstance(None)
    main_win._on_instance_selected(None)
    assert viewer._selected_inst is None
    assert main_win._inspector._selected_item_grp is None


def test_display_controls_and_options(main_win):
    """Verifies toggling of density heatmap, flightlines, and rulers."""
    viewer = main_win._viewer
    options = viewer.getOptions()

    # Heatmap toggle
    main_win._toggle_heatmap(True)
    assert options.showDensityHeatmap() is True
    main_win._toggle_heatmap(False)
    assert options.showDensityHeatmap() is False

    # Flightlines toggle
    main_win._toggle_flightlines(False)
    assert options.showFlightlines() is False
    main_win._toggle_flightlines(True)
    assert options.showFlightlines() is True

    # Ruler measurement
    from rishi.odb.geom import Point
    viewer.setRulerMode(True)
    assert viewer.isRulerMode()
    p1 = Point(0, 0)
    p2 = Point(10000, 20000)
    viewer._rulers.append((p1, p2))
    assert len(viewer._rulers) == 1
    viewer.clearRulers()
    assert len(viewer._rulers) == 0
    viewer.setRulerMode(False)

    # Standard Cells & Macros visibility options
    assert options.areStandardCellsVisible() is True
    assert options.areMacrosVisible() is True
    options.setStandardCellsVisible(False)
    assert options.areStandardCellsVisible() is False
    options.setStandardCellsVisible(True)
    options.setMacrosVisible(False)
    assert options.areMacrosVisible() is False
    options.setMacrosVisible(True)

    # Verify flightlines generation on connected instance
    chip = viewer.getChip()
    if chip and chip.getBlock():
        inst = chip.getBlock().findInst("_350_")
        if inst:
            viewer.selectInstance(inst)
            assert len(viewer._flightlines) > 0


def test_legend_and_controls_polygon_boundary(main_win):
    """Verifies that LegendDock and DisplayControls expose both rectangular die boundary and polygon boundary."""
    from rishi.gui.legend import LegendItem
    from PySide6.QtGui import QColor

    legend_items = main_win._legend.findChildren(LegendItem)
    titles = [it._title for it in legend_items]
    assert any("Die Boundary" in t for t in titles)
    assert any("Polygon" in t for t in titles)

    poly_item = next(it for it in legend_items if "Polygon" in it._title)
    assert poly_item._swatch._is_polygon is True
    # Trigger swatch paintEvent to ensure polygon swatch renders cleanly
    poly_item._swatch.grab()

    # Changing polygon color via callback updates viewer options
    new_col = QColor(255, 120, 0)
    poly_item._on_color_changed(new_col)
    assert main_win._viewer.getOptions().polygonColor() == new_col


def test_legend_and_controls_blockages(main_win):
    """Verifies that LegendDock and DisplayControls expose Placement Blockages with color customization."""
    from rishi.gui.legend import LegendItem
    from PySide6.QtGui import QColor

    legend_items = main_win._legend.findChildren(LegendItem)
    titles = [it._title for it in legend_items]
    assert any("Blockage" in t for t in titles)

    blk_item = next(it for it in legend_items if "Blockage" in it._title)
    assert blk_item._swatch._is_hatch is True

    # Trigger swatch paintEvent to ensure hatch pattern swatch renders cleanly
    pixmap = blk_item._swatch.grab()
    assert not pixmap.isNull()

    # Altering blockage color via callback updates viewer options
    custom_color = QColor(220, 80, 80, 190)
    blk_item._on_color_changed(custom_color)
    assert main_win._viewer.getOptions().placementBlockageColor() == custom_color
    assert main_win._viewer.getOptions().blockageColor() == custom_color

    # Verify DisplayControls has blockage in object items with icon
    assert "_show_blockages" in main_win._controls._object_items
    item = main_win._controls._object_items["_show_blockages"]
    assert not item.icon(1).isNull()


def test_close_design_resets_state_and_memory(main_win):
    """Verifies that close_design resets viewer, docks, database, and status cleanly to start fresh."""
    from rishi.odb.database import dbDatabase, dbChip
    from rishi.odb.block import dbBlock
    from rishi.odb.tech import dbTech
    from rishi.odb.geom import Rect

    db = dbDatabase()
    tech = dbTech(1000)
    db.setTech(tech)
    block = dbBlock(tech, "testResetBlock")
    block.setDieArea(Rect(0, 0, 100000, 100000))
    chip = dbChip(db, block)

    main_win._db = db
    main_win._viewer.setChip(chip)
    main_win._search_dock.setChip(chip)
    main_win._inspector.update_design(chip)

    assert main_win._viewer.hasDesign()
    assert main_win._viewer.getChip() is not None

    # Call close_design
    main_win.close_design()

    assert not main_win._viewer.hasDesign()
    assert main_win._viewer.getChip() is None
    assert main_win._viewer._pixmap is None
    assert main_win._viewer.getSearch()._inst_boxes is None
    assert len(main_win._viewer._flightlines) == 0
    assert main_win._def_file is None
    assert len(main_win._lef_files) == 0
    assert "Silicon Layout Viewer" in main_win.windowTitle()





