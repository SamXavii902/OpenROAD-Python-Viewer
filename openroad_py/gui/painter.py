"""Painter helper ported from OpenROAD gui/src/painter.cpp."""

from typing import List, Optional
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF
from PySide6.QtCore import QPointF, QRectF, Qt
from openroad_py.odb.geom import Rect, Polygon, Point
from openroad_py.gui.options import DisplayOptions


class GuiPainter:
    """Helper wrapper around QPainter operating in DBU coordinates matching OpenROAD."""

    def __init__(
        self,
        painter: QPainter,
        options: DisplayOptions,
        bounds: Rect,
        pixels_per_dbu: float,
        dbu_per_micron: int,
    ):
        self._painter: QPainter = painter
        self._options: DisplayOptions = options
        self._bounds: Rect = bounds
        self._pixels_per_dbu: float = pixels_per_dbu
        self._dbu_per_micron: int = dbu_per_micron

    def getPainter(self) -> QPainter:
        return self._painter

    def getOptions(self) -> DisplayOptions:
        return self._options

    def getBounds(self) -> Rect:
        return self._bounds

    def getPixelsPerDBU(self) -> float:
        return self._pixels_per_dbu

    def getDbuPerMicron(self) -> int:
        return self._dbu_per_micron

    def saveState(self) -> None:
        self._painter.save()

    def restoreState(self) -> None:
        self._painter.restore()

    def setPen(self, color: QColor, cosmetic: bool = True) -> None:
        pen = QPen(color)
        pen.setCosmetic(cosmetic)
        self._painter.setPen(pen)

    def setBrush(self, color: QColor, pattern: Qt.BrushStyle = Qt.SolidPattern) -> None:
        self._painter.setBrush(QBrush(color, pattern))

    def drawRect(self, rect: Rect) -> None:
        self._painter.drawRect(rect.xMin(), rect.yMin(), rect.dx(), rect.dy())

    def drawPolygon(self, poly: Polygon) -> None:
        qpoly = QPolygonF([QPointF(p.x, p.y) for p in poly.getPoints()])
        self._painter.drawPolygon(qpoly)

    def drawLine(self, p1: Point, p2: Point) -> None:
        self._painter.drawLine(p1.x, p1.y, p2.x, p2.y)
