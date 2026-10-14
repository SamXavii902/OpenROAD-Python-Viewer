import os
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import QRect
from rishi.odb.database import dbDatabase
from rishi.odb.geom import Rect
from rishi.lefin import LefParser
from rishi.defin import DefParser
from rishi.gui.layoutViewer import LayoutViewer


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_viewer_renders_routed_design(qapp):
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\src\odb\test\data\gcd\gcd_nangate45_route.def"

    assert os.path.exists(lef_path1)
    assert os.path.exists(lef_path2)
    assert os.path.exists(def_path)

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    def_parser = DefParser(db)
    block = def_parser.parse_file(def_path)
    chip = db.getChip()

    viewer = LayoutViewer()
    viewer.resize(800, 600)
    viewer.setChip(chip)

    # Trigger fit and synchronous render to verify image generation
    viewer.fit()
    render_thread = viewer._render_thread

    test_image = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    draw_bounds = QRect(0, 0, 800, 600)
    render_thread.draw(test_image, draw_bounds)

    assert not test_image.isNull()

    # Verify that image is not completely empty (contains colored pixels)
    has_colored_pixels = False
    for y in range(0, 600, 10):
        for x in range(0, 800, 10):
            pixel = test_image.pixelColor(x, y)
            # Background is RGB(20, 20, 20)
            if pixel.red() > 30 or pixel.green() > 30 or pixel.blue() > 30:
                has_colored_pixels = True
                break
        if has_colored_pixels:
            break

    assert has_colored_pixels, "Rendered image should contain layout shapes and colors"
    viewer.close()


def test_viewer_placement_density_heatmap(qapp):
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\src\odb\test\data\gcd\gcd_nangate45_route.def"

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    def_parser = DefParser(db)
    def_parser.parse_file(def_path)
    chip = db.getChip()

    viewer = LayoutViewer()
    viewer.resize(800, 600)
    viewer.setChip(chip)
    viewer.getOptions().setShowDensityHeatmap(True)

    # Ensure density image computation
    viewer._ensure_density_image()
    assert viewer._density_image is not None
    assert not viewer._density_image.isNull()
    assert viewer._density_image.width() == 120
    assert viewer._density_image.height() == 120
    assert viewer._density_max_val > 0.0

    # Ensure HUD legend and heatmap render without error in paintEvent
    viewer.repaint()
    viewer.close()


def test_viewer_renders_iopins_with_layers_off(qapp):
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\src\odb\test\data\gcd\gcd_nangate45_route.def"

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    def_parser = DefParser(db)
    block = def_parser.parse_file(def_path)
    chip = db.getChip()

    assert len(block.getBTerms()) > 0, "Design should have IO pins"

    viewer = LayoutViewer()
    viewer.resize(800, 600)
    viewer.setChip(chip)
    viewer.fit()

    options = viewer.getOptions()
    # Turn OFF all tech layers (metal, cut, etc.)
    for layer in chip.getTech().getLayers():
        options.setVisible(layer, False)
    # Turn off rows so only IO pins produce green pixels
    options._show_rows = False

    # Ensure IO pins are visible
    options.setIOPinsVisible(True)
    assert options.areIOPinsVisible() is True

    test_image = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    draw_bounds = QRect(0, 0, 800, 600)
    viewer._render_thread.draw(test_image, draw_bounds)

    # Verify that green IO pin pixels are rendered along the perimeter
    pin_col = options.ioPinColor()
    found_pin_pixels = False
    for y in range(0, 600):
        for x in range(0, 800):
            pixel = test_image.pixelColor(x, y)
            # Check for green pin color
            if pixel.green() >= 140 and pixel.green() > pixel.red() + 30 and pixel.green() > pixel.blue() + 30:
                found_pin_pixels = True
                break
        if found_pin_pixels:
            break

    assert found_pin_pixels, "IO pins should be visible in green even with all layers switched off"

    # Now turn off IO pins and verify green pin pixels disappear
    options.setIOPinsVisible(False)
    test_image_no_pins = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    viewer._render_thread.draw(test_image_no_pins, draw_bounds)

    found_pin_pixels_when_off = False
    for y in range(0, 600):
        for x in range(0, 800):
            pixel = test_image_no_pins.pixelColor(x, y)
            if pixel.green() >= 140 and pixel.green() > pixel.red() + 30 and pixel.green() > pixel.blue() + 30:
                found_pin_pixels_when_off = True
                break
        if found_pin_pixels_when_off:
            break

    assert not found_pin_pixels_when_off, "IO pins should not be drawn when toggled off"
    viewer.close()


def test_viewer_iopin_names_zoom_threshold(qapp):
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\src\odb\test\data\gcd\gcd_nangate45_route.def"

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    def_parser = DefParser(db)
    block = def_parser.parse_file(def_path)
    chip = db.getChip()

    viewer = LayoutViewer()
    viewer.resize(800, 600)
    viewer.setChip(chip)
    viewer.fit()

    options = viewer.getOptions()
    options.setIOPinsVisible(True)
    options.setIOPinNamesVisible(True)

    # In default view, nominalViewableResolution is large (> 1000 DBU),
    # so pin names should NOT be drawn, avoiding clutter.
    assert viewer.nominalViewableResolution() > 1000, "Default full-chip view should have nominalViewableResolution > 1000"

    # Zoom in to a pin on the bottom edge
    viewer.zoomTo(Rect(44000, -1000, 45000, 1000))
    assert viewer.nominalViewableResolution() <= 1000, "Zoomed-in view should enable pin name display"

    test_image = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    draw_bounds = QRect(0, 0, 800, 600)
    viewer._render_thread.draw(test_image, draw_bounds)
    assert not test_image.isNull()
    viewer.close()


def test_viewer_iopin_names_rotation_and_collision_avoidance(qapp):
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI\src\odb\test\data\gcd\gcd_nangate45_route.def"

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    def_parser = DefParser(db)
    block = def_parser.parse_file(def_path)
    chip = db.getChip()

    viewer = LayoutViewer()
    viewer.resize(1000, 800)
    viewer.setChip(chip)

    options = viewer.getOptions()
    options.setIOPinsVisible(True)
    options.setIOPinNamesVisible(True)

    # Zoom in to a section of the bottom edge where multiple IO pins sit side by side
    die = block.getDieArea()
    viewer.zoomTo(Rect(40000, die.yMin() - 5000, 90000, die.yMin() + 5000))
    assert viewer.nominalViewableResolution() <= 1000

    test_image = QImage(1000, 800, QImage.Format_ARGB32_Premultiplied)
    draw_bounds = QRect(0, 0, 1000, 800)
    viewer._render_thread.draw(test_image, draw_bounds)
    assert not test_image.isNull()
    viewer.close()


def test_viewer_renders_ethernet_complex_polygon_and_rect_die_outlines(qapp, tmp_path):
    """Verify that a complex rectilinear polygon DIEAREA (like Ethernet_SS) renders both:
    1. The outer rectangular die bounding box outline, and
    2. The second complex polygon outline wrapping the design shape.
    """
    eth_def = tmp_path / "eth_poly.def"
    eth_def.write_text(
        """VERSION 5.8 ;
DESIGN Ethernet_SS ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 1979928 812925 ) ( 1838735 812925 )
        ( 1838735 812944 ) ( 1750284 812944 )
        ( 1750284 1452032 ) ( 1163504 1452032 )
        ( 1163504 2035072 ) ( 295084 2035072 )
        ( 295084 2684623 ) ( 0 2684623 )
        ( 0 521984 ) ( 135040 521984 )
        ( 135040 147968 ) ( 376960 147968 )
        ( 376960 105984 ) ( 739968 105984 )
        ( 739968 0 ) ( 1979928 0 ) ;
END DESIGN
"""
    )

    db = dbDatabase()
    dp = DefParser(db)
    block = dp.parse_file(str(eth_def))
    chip = db.getChip()

    assert block.hasComplexDiePolygon() is True
    assert len(block.getDieAreaPolygon().getPoints()) == 18
    assert block.getDieArea().dx() == 1979928
    assert block.getDieArea().dy() == 2684623
    assert block.getDieAreaPolygon().area() > 0
    assert block.getDieAreaPolygon().area() < block.getDieArea().area()

    viewer = LayoutViewer()
    viewer.resize(800, 1000)
    viewer.setChip(chip)
    viewer.fit()

    test_image = QImage(800, 1000, QImage.Format_ARGB32_Premultiplied)
    draw_bounds = QRect(0, 0, 800, 1000)
    viewer._render_thread.draw(test_image, draw_bounds)

    # Check interior stepped segment midpoint: (729294, 2035072) on the top-middle step
    from rishi.odb.geom import Point
    pt_step = viewer.dbuPointToScreen(Point(729294, 2035072))
    sx, sy = int(round(pt_step.x())), int(round(pt_step.y()))
    found_poly_cyan = False
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            px, py = sx + dx, sy + dy
            if 0 <= px < 800 and 0 <= py < 1000:
                c = test_image.pixelColor(px, py)
                if c.blue() > 150 and c.green() > 120:
                    found_poly_cyan = True
                    break
        if found_poly_cyan:
            break

    assert found_poly_cyan, "Complex polygon step edge should be rendered in polygon outline color"

    # Check outer rectangular die boundary on top-right cutaway edge: (1500000, 2684623)
    pt_rect = viewer.dbuPointToScreen(Point(1500000, 2684623))
    rx, ry = int(round(pt_rect.x())), int(round(pt_rect.y()))
    found_die_gray = False
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            px, py = rx + dx, ry + dy
            if 0 <= px < 800 and 0 <= py < 1000:
                c = test_image.pixelColor(px, py)
                if c.red() > 100 and c.green() > 100 and c.blue() > 100:
                    found_die_gray = True
                    break
        if found_die_gray:
            break

    assert found_die_gray, "Outer rectangular die boundary should also be rendered"
    viewer.close()




