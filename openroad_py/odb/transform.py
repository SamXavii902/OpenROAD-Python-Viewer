"""Transform class ported from OpenROAD odb/include/odb/dbTransform.h."""

from typing import Union, List
from openroad_py.odb.geom import Point, Rect, Polygon
from openroad_py.odb.types import dbOrientType


class dbTransform:
    """Represents a 2D affine transform consisting of orientation and offset (translation)."""

    def __init__(self, orient: Union[dbOrientType, Point] = dbOrientType.R0, offset: Point = None):
        if isinstance(orient, Point):
            self._orient = dbOrientType.R0
            self._offset = Point(orient.x, orient.y)
        else:
            self._orient = orient if isinstance(orient, dbOrientType) else dbOrientType.R0
            self._offset = Point(offset.x, offset.y) if offset is not None else Point(0, 0)

    @property
    def orient(self) -> dbOrientType:
        return self._orient

    @property
    def offset(self) -> Point:
        return self._offset

    def getOrient(self) -> dbOrientType:
        return self._orient

    def getOffset(self) -> Point:
        return self._offset

    def setOrient(self, orient: dbOrientType) -> None:
        self._orient = orient

    def setOffset(self, offset: Point) -> None:
        self._offset = Point(offset.x, offset.y)

    def setTransform(self, orient: dbOrientType, offset: Point) -> None:
        self._orient = orient
        self._offset = Point(offset.x, offset.y)

    def apply_to_point(self, pt: Point) -> Point:
        """Transforms point pt by orient then translation offset."""
        x, y = pt.x, pt.y
        o = self._orient

        # Apply orientation rotation/reflection around (0,0)
        # Matches OpenROAD dbTransform and standard DEF 5.8 semantics:
        # R0: (x, y)
        # R90: (-y, x)
        # R180: (-x, -y)
        # R270: (y, -x)
        # MY: (-x, y)
        # MYR90 (FE): (-y, -x) [or rotate 90 then mirror Y: (-y, x) -> (y, x)?]
        # In DEF specification:
        # N: (x, y)
        # W: (-y, x)
        # S: (-x, -y)
        # E: (y, -x)
        # FN: (-x, y)
        # FW: (y, x)
        # FS: (x, -y)
        # FE: (-y, -x)
        if o == dbOrientType.R0:
            rx, ry = x, y
        elif o == dbOrientType.R90:
            rx, ry = -y, x
        elif o == dbOrientType.R180:
            rx, ry = -x, -y
        elif o == dbOrientType.R270:
            rx, ry = y, -x
        elif o == dbOrientType.MY:
            rx, ry = -x, y
        elif o == dbOrientType.MYR90:
            rx, ry = -y, -x
        elif o == dbOrientType.MX:
            rx, ry = x, -y
        elif o == dbOrientType.MXR90:
            rx, ry = y, x
        else:
            rx, ry = x, y

        return Point(rx + self._offset.x, ry + self._offset.y)

    def apply(self, target: Union[Point, Rect, Polygon]) -> Union[Point, Rect, Polygon]:
        """Applies transform to target (Point, Rect, or Polygon)."""
        if isinstance(target, Point):
            return self.apply_to_point(target)
        elif isinstance(target, Rect):
            # Transform all four corners and compute enclosing bounding box
            p1 = self.apply_to_point(Point(target.xMin(), target.yMin()))
            p2 = self.apply_to_point(Point(target.xMax(), target.yMin()))
            p3 = self.apply_to_point(Point(target.xMax(), target.yMax()))
            p4 = self.apply_to_point(Point(target.xMin(), target.yMax()))
            xlo = min(p1.x, p2.x, p3.x, p4.x)
            ylo = min(p1.y, p2.y, p3.y, p4.y)
            xhi = max(p1.x, p2.x, p3.x, p4.x)
            yhi = max(p1.y, p2.y, p3.y, p4.y)
            return Rect(xlo, ylo, xhi, yhi)
        elif isinstance(target, Polygon):
            new_pts = [self.apply_to_point(p) for p in target.getPoints()]
            return Polygon(new_pts)
        else:
            raise TypeError(f"Unsupported target type for dbTransform: {type(target)}")

    def invert(self) -> "dbTransform":
        """Returns the inverse transform."""
        # Inverse orient:
        # R0 <-> R0
        # R90 <-> R270
        # R180 <-> R180
        # R270 <-> R90
        # Reflections are self-inverse:
        # MY <-> MY
        # MX <-> MX
        # MYR90 <-> MYR90
        # MXR90 <-> MXR90
        inv_orient_map = {
            dbOrientType.R0: dbOrientType.R0,
            dbOrientType.R90: dbOrientType.R270,
            dbOrientType.R180: dbOrientType.R180,
            dbOrientType.R270: dbOrientType.R90,
            dbOrientType.MY: dbOrientType.MY,
            dbOrientType.MYR90: dbOrientType.MYR90,
            dbOrientType.MX: dbOrientType.MX,
            dbOrientType.MXR90: dbOrientType.MXR90,
        }
        inv_orient = inv_orient_map.get(self._orient, dbOrientType.R0)
        # The offset must be transformed: x_new = -offset under inv_orient
        neg_offset = Point(-self._offset.x, -self._offset.y)
        t_temp = dbTransform(inv_orient, Point(0, 0))
        inv_offset = t_temp.apply_to_point(neg_offset)
        return dbTransform(inv_orient, inv_offset)

    def __repr__(self) -> str:
        return f"dbTransform({self._orient.name}, {self._offset})"
