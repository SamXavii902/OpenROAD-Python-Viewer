"""Design Legend and EDA Layout Representation Guide matching OpenROAD GUI with interactive color wheels."""

from typing import Optional, Callable
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
    QColorDialog,
    QPushButton,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtCore import Qt, Signal, QPointF


class ClickableSwatch(QFrame):
    """An interactive color swatch that emits clicked() on mouse press."""

    clicked = Signal()

    def __init__(
        self,
        color: QColor,
        is_filled: bool = True,
        border_color: Optional[QColor] = None,
        is_dashed: bool = False,
        is_polygon: bool = False,
        is_hatch: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._color = color
        self._is_filled = is_filled
        self._border_color = border_color
        self._is_dashed = is_dashed
        self._is_polygon = is_polygon
        self._is_hatch = is_hatch
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to open color wheel and customize layout color")
        self.update_style()

    def update_style(self) -> None:
        if self._is_polygon or self._is_hatch:
            self.setStyleSheet(
                "ClickableSwatch { background-color: #18181c; border: 1px solid #44444e; border-radius: 4px; } "
                "ClickableSwatch:hover { border: 2px solid #FFFFFF; }"
            )
            self.update()
            return
        b_col = self._border_color.name() if self._border_color else self._color.name()
        dash_style = "dashed" if self._is_dashed else "solid"
        border_css = f"border: 2px {dash_style} {b_col};"
        bg_css = f"background-color: {self._color.name() if self._is_filled else 'transparent'};"
        self.setStyleSheet(
            f"ClickableSwatch {{ {bg_css} {border_css} border-radius: 4px; }} "
            f"ClickableSwatch:hover {{ border: 2px solid #FFFFFF; }}"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._is_hatch:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, False)
            b_col = self._border_color if self._border_color else self._color
            # Draw dark background tile
            painter.fillRect(3, 3, 24, 24, QColor(26, 26, 32))
            # Draw diagonal hatch pattern matching OpenROAD placement blockage brush
            hatch_brush = QBrush(self._color, Qt.BDiagPattern)
            painter.fillRect(3, 3, 24, 24, hatch_brush)
            # Draw outer border
            painter.setPen(QPen(b_col, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(3, 3, 23, 23)
            painter.end()
            return

        if not self._is_polygon:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        # Draw outer faint die rectangle reference
        painter.setPen(QPen(QColor(110, 110, 120, 140), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(4, 4, 21, 21)
        # Draw stepped rectilinear polygon outline inside swatch
        b_col = self._border_color if self._border_color else self._color
        pen = QPen(b_col, 2, Qt.DashLine if self._is_dashed else Qt.SolidLine)
        painter.setPen(pen)
        poly = QPolygonF([
            QPointF(4, 4),
            QPointF(12, 4),
            QPointF(12, 10),
            QPointF(19, 10),
            QPointF(19, 16),
            QPointF(25, 16),
            QPointF(25, 25),
            QPointF(10, 25),
            QPointF(10, 20),
            QPointF(4, 20),
        ])
        painter.drawPolygon(poly)
        painter.end()

    def setColor(self, color: QColor, border_color: Optional[QColor] = None) -> None:
        self._color = color
        if border_color:
            self._border_color = border_color
        self.update_style()

    def color(self) -> QColor:
        return self._color

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class LegendItem(QFrame):
    """A single legend entry with an interactive color wheel swatch and descriptive text."""

    def __init__(
        self,
        title: str,
        description: str,
        color: QColor,
        is_filled: bool = True,
        border_color: Optional[QColor] = None,
        is_dashed: bool = False,
        is_polygon: bool = False,
        is_hatch: bool = False,
        on_color_changed: Optional[Callable[[QColor], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._title = title
        self._on_color_changed = on_color_changed
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background-color: #252528; border-radius: 4px; padding: 4px; border: 1px solid #333338; } "
            "QFrame:hover { border: 1px solid #4a4a52; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Interactive swatch button
        self._swatch = ClickableSwatch(
            color=color,
            is_filled=is_filled,
            border_color=border_color,
            is_dashed=is_dashed,
            is_polygon=is_polygon,
            is_hatch=is_hatch,
            parent=self,
        )
        self._swatch.clicked.connect(self._open_color_picker)
        layout.addWidget(self._swatch)


        # Text layout
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_font = QFont("Segoe UI", 9, QFont.Bold)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        text_layout.addWidget(title_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setFont(QFont("Segoe UI", 8))
        desc_lbl.setStyleSheet("color: #AAAAAA; border: none; background: transparent;")
        text_layout.addWidget(desc_lbl)

        layout.addLayout(text_layout)

    def _open_color_picker(self) -> None:
        curr_color = self._swatch.color()
        new_color = QColorDialog.getColor(
            curr_color,
            self,
            f"Select Custom Color for {self._title}",
            QColorDialog.ShowAlphaChannel,
        )
        if new_color.isValid():
            self._swatch.setColor(new_color)
            if self._on_color_changed:
                self._on_color_changed(new_color)


class LegendDock(QDockWidget):
    """Dockable panel explaining layout objects with interactive color customization."""

    def __init__(self, viewer=None, parent=None):
        super().__init__("Layout Legend", parent)
        self._viewer = viewer
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        item_layout = QVBoxLayout(container)
        item_layout.setSpacing(8)
        item_layout.setContentsMargins(4, 4, 4, 4)

        # Header intro
        header = QLabel("Silicon Layout Geometry Guide")
        header.setFont(QFont("Segoe UI", 10, QFont.Bold))
        header.setStyleSheet("color: #80CBC4; padding: 2px 0;")
        item_layout.addWidget(header)

        tip = QLabel("Tip: Click any color swatch to customize palette via Color Wheel")
        tip_font = QFont("Segoe UI", 8)
        tip_font.setItalic(True)
        tip.setFont(tip_font)
        tip.setStyleSheet("color: #888899; padding-bottom: 4px;")
        item_layout.addWidget(tip)

        # Helper to get options
        def get_opt():
            return self._viewer.getOptions() if self._viewer else None

        def repaint():
            if self._viewer:
                self._viewer.fullRepaint()

        # 1. SRAM & Macros
        def on_macro_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setMacroColor(c)
                repaint()

        item_layout.addWidget(
            LegendItem(
                "SRAM & Hard Macros",
                "Large memory blocks, cache arrays, & PLL IP cores with customizable fill and golden name badges.",
                color=QColor(130, 50, 210, 180),
                is_filled=True,
                border_color=QColor(210, 140, 255),
                on_color_changed=on_macro_color,
            )
        )

        # 2. Standard Cells
        def on_cell_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setCellColor(c)
                repaint()

        item_layout.addWidget(
            LegendItem(
                "Standard Cells",
                "Logic gates (AND, OR, Flip-Flops, MUXes) placed in standard rows. Fine wireframe outline.",
                color=QColor(120, 120, 120),
                is_filled=False,
                border_color=QColor(140, 140, 140),
                on_color_changed=on_cell_color,
            )
        )

        # 3. Placement Blockages
        def on_blockage_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setPlacementBlockageColor(c)
                repaint()

        blockage_col = get_opt().placementBlockageColor() if get_opt() else QColor(100, 100, 100, 150)
        item_layout.addWidget(
            LegendItem(
                "Placement Blockages",
                "Physical keep-out areas prohibiting standard cell placement, rendered with diagonal hatch pattern.",
                color=blockage_col,
                is_filled=True,
                border_color=QColor(160, 160, 160),
                is_hatch=True,
                on_color_changed=on_blockage_color,
            )
        )

        # 4. Routing Wires
        def on_wire_color(c: QColor):
            if self._viewer and self._viewer.getChip():
                tech = self._viewer.getChip().getTech()
                opt = get_opt()
                if tech and opt:
                    for lay in tech.getLayers():
                        if "metal" in lay.getName().lower() or "m1" in lay.getName().lower():
                            opt.setColor(lay, c)
                            break
                    repaint()

        item_layout.addWidget(
            LegendItem(
                "Signal Routing Wires",
                "Multi-layer copper interconnects. Direction alternates per layer (e.g. M1=Horiz, M2=Vert).",
                color=QColor(51, 102, 255),
                is_filled=True,
                on_color_changed=on_wire_color,
            )
        )

        # 4. Power Grid Stripes
        def on_power_color(c: QColor):
            if self._viewer and self._viewer.getChip():
                tech = self._viewer.getChip().getTech()
                opt = get_opt()
                if tech and opt:
                    layers = tech.getLayers()
                    if len(layers) >= 4:
                        opt.setColor(layers[-2], c)
                    repaint()

        item_layout.addWidget(
            LegendItem(
                "Power / Ground Grid (VDD & VSS)",
                "Wide upper-metal straps (e.g. Metal 6/7/8) delivering low-resistance power across the core.",
                color=QColor(230, 100, 160),
                is_filled=True,
                on_color_changed=on_power_color,
            )
        )

        # 5. Via Cuts
        def on_via_color(c: QColor):
            if self._viewer and self._viewer.getChip():
                tech = self._viewer.getChip().getTech()
                opt = get_opt()
                if tech and opt:
                    for lay in tech.getLayers():
                        if "cut" in lay.getName().lower() or "via" in lay.getName().lower():
                            opt.setColor(lay, c)
                            break
                    repaint()

        item_layout.addWidget(
            LegendItem(
                "Via Cuts",
                "Vertical contact plugs connecting wires between adjacent metal layers.",
                color=QColor(255, 60, 60),
                is_filled=True,
                on_color_changed=on_via_color,
            )
        )

        # 6. Die Area (Rectangular Bounding Box)
        def on_die_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setDieColor(c)
                repaint()

        item_layout.addWidget(
            LegendItem(
                "Die Boundary (Rectangular)",
                "Outer solid rectangle defining the overall silicon die bounding box perimeter.",
                color=QColor(180, 180, 180),
                is_filled=False,
                border_color=QColor(200, 200, 200),
                on_color_changed=on_die_color,
            )
        )

        # 7. Polygon / Core Boundary (Complex Floorplan Shape)
        def on_core_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setPolygonColor(c)
                repaint()

        item_layout.addWidget(
            LegendItem(
                "Polygon / Core Boundary",
                "Inner dashed rectilinear polygon outline wrapping the complex floorplan shape, macros, and placement rows.",
                color=QColor(0, 210, 255),
                is_filled=False,
                border_color=QColor(0, 210, 255),
                is_dashed=True,
                is_polygon=True,
                on_color_changed=on_core_color,
            )
        )


        # 8. I/O Pins
        def on_io_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setIoPinColor(c)
                repaint()

        item_layout.addWidget(
            LegendItem(
                "I/O Boundary Pins",
                "Primary input/output pads along the perimeter connecting core signals to package pins.",
                color=QColor(76, 175, 80),
                is_filled=True,
                on_color_changed=on_io_color,
            )
        )

        # 9. Measurement Ruler
        def on_ruler_color(c: QColor):
            opt = get_opt()
            if opt:
                opt.setRulerColor(c)
                if self._viewer:
                    self._viewer.update()

        item_layout.addWidget(
            LegendItem(
                "Measurement Ruler",
                "Interactive on-screen distance calipers (shortcut 'K') measuring Euclidean and Manhattan distances.",
                color=QColor(255, 235, 59),
                is_filled=True,
                on_color_changed=on_ruler_color,
            )
        )

        item_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        self.setWidget(content)

    def setViewer(self, viewer) -> None:
        self._viewer = viewer
