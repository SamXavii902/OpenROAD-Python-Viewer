"""CLI entry point for openroad_py."""

import sys
import os
import glob
import argparse
from PySide6.QtWidgets import QApplication
from openroad_py.gui.mainWindow import MainWindow


def main():
    parser = argparse.ArgumentParser(description="OpenROAD Native Python LEF/DEF Layout Viewer")
    parser.add_argument("--lef", action="append", default=[], help="Path to LEF/TLEF file (can be repeated)")
    parser.add_argument("--def", dest="def_file", help="Path to DEF file")
    parser.add_argument("--timing", "-t", dest="timing_file", help="Path to timing report (.tarpt, .btarpt, .rpt)")
    parser.add_argument("--dir", "-d", dest="folder", help="Path to design directory containing LEF and DEF files")
    parser.add_argument("design_folder", nargs="?", default=None, help="Optional design folder to open directly")

    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()

    folder = args.folder or args.design_folder
    if folder and os.path.isdir(folder):
        all_lefs = glob.glob(os.path.join(folder, "**", "*.lef"), recursive=True) + glob.glob(
            os.path.join(folder, "**", "*.tlef"), recursive=True
        )
        all_defs = glob.glob(os.path.join(folder, "**", "*.def"), recursive=True)
        if not all_lefs:
            parent = os.path.dirname(folder)
            all_lefs = glob.glob(os.path.join(parent, "**", "*.lef"), recursive=True) + glob.glob(
                os.path.join(parent, "**", "*.tlef"), recursive=True
            )

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
        target_def = all_defs[0] if all_defs else None
        for d in all_defs:
            if "route" in os.path.basename(d).lower():
                target_def = d
                break

        if target_def and sorted_lefs:
            window.load_design_files(sorted_lefs, target_def)
    else:
        for lef_path in args.lef:
            window.load_lef(lef_path)
        if args.def_file:
            window.load_def(args.def_file)

    if args.timing_file and os.path.exists(args.timing_file):
        window._timing_dock.load_file(args.timing_file)
        window._timing_dock.show()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
