"""Universal EDA Dark Theme configuration for RISHI Layout Viewer."""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt


def apply_dark_theme(app: QApplication) -> None:
    """Applies a professional, consistent EDA dark palette and stylesheet across all platforms (Windows, Unix, macOS)."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(20, 24, 32))
    palette.setColor(QPalette.WindowText, QColor(220, 225, 235))
    palette.setColor(QPalette.Base, QColor(15, 18, 24))
    palette.setColor(QPalette.AlternateBase, QColor(24, 28, 38))
    palette.setColor(QPalette.ToolTipBase, QColor(15, 18, 24))
    palette.setColor(QPalette.ToolTipText, QColor(220, 225, 235))
    palette.setColor(QPalette.Text, QColor(220, 225, 235))
    palette.setColor(QPalette.Button, QColor(28, 33, 44))
    palette.setColor(QPalette.ButtonText, QColor(220, 225, 235))
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(0, 229, 255))
    palette.setColor(QPalette.Highlight, QColor(0, 180, 216))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(95, 105, 120))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(95, 105, 120))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(95, 105, 120))
    app.setPalette(palette)

    stylesheet = """
        QMainWindow {
            background-color: #12141A;
        }
        QMenuBar {
            background-color: #181C24;
            color: #CBD5E1;
            border-bottom: 1px solid #282E3E;
        }
        QMenuBar::item {
            background-color: transparent;
            padding: 4px 8px;
        }
        QMenuBar::item:selected {
            background-color: #262B37;
            color: #00E5FF;
            border-radius: 2px;
        }
        QMenu {
            background-color: #1A1E27;
            color: #E2E8F0;
            border: 1px solid #2D3446;
        }
        QMenu::item {
            padding: 5px 24px 5px 20px;
        }
        QMenu::item:selected {
            background-color: #00E5FF;
            color: #000000;
        }
        QMenu::separator {
            height: 1px;
            background: #2D3446;
            margin: 4px 6px;
        }
        QStatusBar {
            background-color: #141720;
            color: #94A3B8;
            border-top: 1px solid #232732;
        }
        QDockWidget {
            color: #E2E8F0;
        }
        QDockWidget::title {
            background-color: #1C202B;
            color: #CBD5E1;
            font-weight: bold;
            font-size: 8pt;
            padding: 6px;
            border-bottom: 1px solid #282E3E;
        }
        QTabBar::tab {
            background-color: #1E222D;
            color: #94A3B8;
            padding: 5px 12px;
            border-top-left-radius: 3px;
            border-top-right-radius: 3px;
            border: 1px solid #282E3E;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #12141A;
            color: #00E5FF;
            font-weight: bold;
            border-bottom: 2px solid #00E5FF;
        }
        QTabBar::tab:hover:!selected {
            background-color: #262B37;
            color: #E2E8F0;
        }
        QTreeWidget {
            background-color: #151821;
            color: #E2E8F0;
            border: 1px solid #232732;
        }
        QTreeWidget::item {
            padding: 2px 4px;
        }
        QTreeWidget::item:hover {
            background-color: #232836;
        }
        QTreeWidget::item:selected {
            background-color: #00E5FF;
            color: #000000;
        }
        QHeaderView::section {
            background-color: #1A1E28;
            color: #A0A8B8;
            border: 1px solid #262B38;
            padding: 3px 6px;
            font-weight: bold;
            font-size: 8pt;
        }
        QPushButton {
            background-color: #262B38;
            color: #E2E8F0;
            border: 1px solid #3B4356;
            border-radius: 3px;
            padding: 3px 8px;
            font-size: 8pt;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #333B4D;
            color: #00E5FF;
            border: 1px solid #00E5FF;
        }
        QPushButton:pressed {
            background-color: #1A1E27;
        }
        QPushButton:disabled {
            background-color: #1A1D24;
            color: #64748B;
            border: 1px solid #282C37;
        }
        QScrollBar:vertical {
            background: #141720;
            width: 10px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #2D3446;
            min-height: 20px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover {
            background: #00E5FF;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QScrollBar:horizontal {
            background: #141720;
            height: 10px;
            margin: 0px;
        }
        QScrollBar::handle:horizontal {
            background: #2D3446;
            min-width: 20px;
            border-radius: 4px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #00E5FF;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
    """
    app.setStyleSheet(stylesheet)

