"""Renders layout designs to PNG images for preview and verification."""

import os
import sys

# Add repo root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import QRect
from rishi.odb.database import dbDatabase
from rishi.lefin import LefParser
from rishi.defin import DefParser
from rishi.gui.layoutViewer import LayoutViewer


def export_design_png(lef_files, def_file, out_png, width=1920, height=1080):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    db = dbDatabase()
    lef_parser = LefParser(db)
    for lf in lef_files:
        lef_parser.parse_file(lf)

    def_parser = DefParser(db)
    block = def_parser.parse_file(def_file)
    chip = db.getChip()

    viewer = LayoutViewer()
    viewer.resize(width, height)
    viewer.setChip(chip)
    viewer.fit()

    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    viewer._render_thread.draw(image, QRect(0, 0, width, height))

    image.save(out_png)
    print(f"Exported {block.getName()} ({len(block.getInsts()):,} insts) -> {out_png}")
    sys.stdout.flush()


if __name__ == "__main__":
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tech_lef = os.path.join(base, "designs", "Nangate45", "Nangate45_tech.lef")
    cell_lef = os.path.join(base, "designs", "Nangate45", "Nangate45_stdcell.lef")

    # 1. Export GCD
    gcd_def = os.path.join(base, "designs", "gcd", "gcd_nangate45_route.def")
    gcd_png = os.path.join(base, "designs", "gcd_preview.png")
    export_design_png([tech_lef, cell_lef], gcd_def, gcd_png)

    # 2. Export Ibex RISC-V Core
    ibex_def = os.path.join(base, "designs", "ibex", "ibex_core.def")
    ibex_png = os.path.join(base, "designs", "ibex_preview.png")
    export_design_png([tech_lef, cell_lef], ibex_def, ibex_png)

    # 3. Export AES Cipher Top
    aes_def = os.path.join(base, "designs", "aes", "aes_cipher_top.def")
    aes_png = os.path.join(base, "designs", "aes_preview.png")
    export_design_png([tech_lef, cell_lef], aes_def, aes_png)

    # 4. Export SweRV RISC-V Core with 28 SRAM Macros (131k cells, 144k nets)
    swerv_macro_lef = os.path.join(base, "designs", "swerv_wrapper", "swerv_wrapper_macro.lef")
    swerv_def = os.path.join(base, "designs", "swerv_wrapper", "swerv_wrapper.def")
    swerv_png = os.path.join(base, "designs", "swerv_preview.png")
    export_design_png([tech_lef, cell_lef, swerv_macro_lef], swerv_def, swerv_png)

    # 5. Export BlackParrot RISC-V Back-End with 10 SRAM Macros (76k cells, 86k nets)
    bp_macro_lef = os.path.join(base, "designs", "blackparrot", "bp_be_top_macro.lef")
    bp_def = os.path.join(base, "designs", "blackparrot", "bp_be_top.def")
    bp_png = os.path.join(base, "designs", "bp_be_preview.png")
    export_design_png([tech_lef, cell_lef, bp_macro_lef], bp_def, bp_png)

    os._exit(0)
