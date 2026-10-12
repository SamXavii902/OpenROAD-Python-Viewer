"""Geometry classes ported from OpenROAD odb/include/odb/geom.h."""

from typing import List, Tuple, Optional


class Point:
    __slots__ = ("_x", "_y")

    def __init__(self, x: int = 0, y: int = 0):
        self._x = int(x)
        self._y = int(y)

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    def getX(self) -> int:
        return self._x

    def getY(self) -> int:
        return self._y

    def setX(self, x: int) -> None:
        self._x = int(x)

    def setY(self, y: int) -> None:
        self._y = int(y)

    def addX(self, dx: int) -> None:
        self._x += int(dx)

    def addY(self, dy: int) -> None:
        self._y += int(dy)

    def __repr__(self) -> str:
        return f"Point({self._x}, {self._y})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return False
        return self._x == other._x and self._y == other._y

    def __hash__(self) -> int:
        return hash((self._x, self._y))


class Rect:
    __slots__ = ("_xlo", "_ylo", "_xhi", "_yhi")

    def __init__(self, xlo: int = 0, ylo: int = 0, xhi: int = 0, yhi: int = 0):
        # Normalize so xlo <= xhi and ylo <= yhi
        if xlo <= xhi:
            self._xlo = int(xlo)
            self._xhi = int(xhi)
        else:
            self._xlo = int(xhi)
            self._xhi = int(xlo)

        if ylo <= yhi:
            self._ylo = int(ylo)
            self._yhi = int(yhi)
        else:
            self._ylo = int(yhi)
            self._yhi = int(ylo)

    def xMin(self) -> int:
        return self._xlo

    def yMin(self) -> int:
        return self._ylo

    def xMax(self) -> int:
        return self._xhi

    def yMax(self) -> int:
        return self._yhi

    def dx(self) -> int:
        return self._xhi - self._xlo

    def dy(self) -> int:
        return self._yhi - self._ylo

    def width(self) -> int:
        return self.dx()

    def height(self) -> int:
        return self.dy()

    def area(self) -> int:
        return self.dx() * self.dy()

    def set_xlo(self, x: int) -> None:
        self._xlo = int(x)

    def set_ylo(self, y: int) -> None:
        self._ylo = int(y)

    def set_xhi(self, x: int) -> None:
        self._xhi = int(x)

    def set_yhi(self, y: int) -> None:
        self._yhi = int(y)

    def ll(self) -> Point:
        return Point(self._xlo, self._ylo)

    def ur(self) -> Point:
        return Point(self._xhi, self._yhi)

    def xCenter(self) -> int:
        return (self._xlo + self._xhi) // 2

    def yCenter(self) -> int:
        return (self._ylo + self._yhi) // 2

    def center(self) -> Point:
        return Point(self.xCenter(), self.yCenter())

    def intersects(self, other: "Rect") -> bool:
        if self._xlo >= other._xhi or other._xlo >= self._xhi:
            return False
        if self._ylo >= other._yhi or other._ylo >= self._yhi:
            return False
        return True

    def intersect(self, other: "Rect") -> "Rect":
        xlo = max(self._xlo, other._xlo)
        ylo = max(self._ylo, other._ylo)
        xhi = min(self._xhi, other._xhi)
        yhi = min(self._yhi, other._yhi)
        if xlo > xhi or ylo > yhi:
            return Rect(0, 0, 0, 0)
        return Rect(xlo, ylo, xhi, yhi)

    def merge(self, other: "Rect") -> None:
        if other.area() == 0 and other._xlo == other._xhi and other._ylo == other._yhi:
            return
        self._xlo = min(self._xlo, other._xlo)
        self._ylo = min(self._ylo, other._ylo)
        self._xhi = max(self._xhi, other._xhi)
        self._yhi = max(self._yhi, other._yhi)

    def getPoints(self) -> List[Point]:
        return [
            Point(self._xlo, self._ylo),
            Point(self._xhi, self._ylo),
            Point(self._xhi, self._yhi),
            Point(self._xlo, self._yhi),
        ]

    def __repr__(self) -> str:
        return f"Rect({self._xlo}, {self._ylo}, {self._xhi}, {self._yhi})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Rect):
            return False
        return (
            self._xlo == other._xlo
            and self._ylo == other._ylo
            and self._xhi == other._xhi
            and self._yhi == other._yhi
        )


class Polygon:
    __slots__ = ("_points",)

    def __init__(self, points: Optional[List[Point]] = None):
        self._points = list(points) if points else []

    def getPoints(self) -> List[Point]:
        return self._points

    def addPoint(self, pt: Point) -> None:
        self._points.append(pt)

    def getEnclosingRect(self) -> Rect:
        if not self._points:
            return Rect(0, 0, 0, 0)
        xlo = min(p.x for p in self._points)
        ylo = min(p.y for p in self._points)
        xhi = max(p.x for p in self._points)
        yhi = max(p.y for p in self._points)
        return Rect(xlo, ylo, xhi, yhi)

    def __repr__(self) -> str:
        return f"Polygon({self._points})"
