import os
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import QRect
from openroad_py.odb.database import dbDatabase
from openroad_py.lefin import LefParser
from openroad_py.defin import DefParser
from openroad_py.gui.layoutViewer import LayoutViewer


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_viewer_renders_routed_design(qapp):
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\src\odb\test\data\gcd\gcd_nangate45_route.def"

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
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\src\odb\test\data\gcd\gcd_nangate45_route.def"

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

