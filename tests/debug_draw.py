import sys
import os
import traceback

sys.path.insert(0, ".")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from rishi.odb.database import dbDatabase
    from rishi.lefin import LefParser
    from rishi.defin import DefParser
    from rishi.gui.layoutViewer import LayoutViewer
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QRect

    db = dbDatabase()
    LefParser(db).parse_file("designs/Nangate45/Nangate45_tech.lef")
    LefParser(db).parse_file("designs/Nangate45/Nangate45_stdcell.lef")
    DefParser(db).parse_file("designs/gcd/gcd_nangate45_route.def")

    viewer = LayoutViewer()
    viewer.resize(1920, 1080)
    viewer.setChip(db.getChip())
    viewer.fit()
    print("Fit done, ppd:", viewer.pixels_per_dbu, "shift:", viewer.centering_shift)

    bounds = viewer.screenToDBU(QRect(0, 0, 1920, 1080))
    print("dbu_bounds:", bounds)
    insts = viewer.getSearch().searchInsts(db.getChip().getBlock(), bounds.xMin(), bounds.yMin(), bounds.xMax(), bounds.yMax())
    print("Found insts:", len(insts))

    shape_limit = viewer.shapeSizeLimit()
    print("Shape limit:", shape_limit)
    total_drawn = 0
    for layer in db.getTech().getLayers():
        routes = viewer.getSearch().searchBoxShapes(db.getChip().getBlock(), layer, bounds.xMin(), bounds.yMin(), bounds.xMax(), bounds.yMax(), shape_limit)
        if routes:
            print(f"{layer.getName()}: {len(routes)} routes, color={viewer.getOptions().color(layer).name()}")
            total_drawn += len(routes)
    print("Total routes to draw:", total_drawn)

    colors = set()
    for y in range(0, 1080, 5):
        for x in range(0, 1920, 5):
            c = image.pixelColor(x, y)
            if c.red() > 25 or c.green() > 25 or c.blue() > 25:
                colors.add((c.red(), c.green(), c.blue()))
    print("Non-background colors found:", len(colors))
    for c in list(colors)[:10]:
        print("Color:", c)

except Exception as e:
    traceback.print_exc()
