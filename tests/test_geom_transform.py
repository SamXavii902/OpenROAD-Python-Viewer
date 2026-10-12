import pytest
from openroad_py.odb.geom import Point, Rect, Polygon
from openroad_py.odb.types import dbOrientType
from openroad_py.odb.transform import dbTransform


def test_point():
    p = Point(10, 20)
    assert p.x == 10
    assert p.y == 20
    p.addX(5)
    p.addY(-10)
    assert p.x == 15
    assert p.y == 10


def test_rect():
    r1 = Rect(10, 20, 50, 60)
    assert r1.dx() == 40
    assert r1.dy() == 40
    assert r1.area() == 1600
    assert r1.xCenter() == 30
    assert r1.yCenter() == 40

    r2 = Rect(30, 40, 70, 80)
    assert r1.intersects(r2)
    inter = r1.intersect(r2)
    assert inter == Rect(30, 40, 50, 60)

    r1.merge(r2)
    assert r1 == Rect(10, 20, 70, 80)


def test_transform_orientations():
    # Test point (10, 20)
    p = Point(10, 20)

    # R0
    t = dbTransform(dbOrientType.R0, Point(100, 200))
    p_t = t.apply(p)
    assert p_t == Point(110, 220)

    # R90: (-y, x) -> (-20, 10) + offset
    t = dbTransform(dbOrientType.R90, Point(0, 0))
    assert t.apply(p) == Point(-20, 10)

    # R180: (-x, -y) -> (-10, -20)
    t = dbTransform(dbOrientType.R180, Point(0, 0))
    assert t.apply(p) == Point(-10, -20)

    # R270: (y, -x) -> (20, -10)
    t = dbTransform(dbOrientType.R270, Point(0, 0))
    assert t.apply(p) == Point(20, -10)

    # MY (FN): (-x, y) -> (-10, 20)
    t = dbTransform(dbOrientType.MY, Point(0, 0))
    assert t.apply(p) == Point(-10, 20)

    # MYR90 (FE): (-y, -x) -> (-20, -10)
    t = dbTransform(dbOrientType.MYR90, Point(0, 0))
    assert t.apply(p) == Point(-20, -10)

    # MX (FS): (x, -y) -> (10, -20)
    t = dbTransform(dbOrientType.MX, Point(0, 0))
    assert t.apply(p) == Point(10, -20)

    # MXR90 (FW): (y, x) -> (20, 10)
    t = dbTransform(dbOrientType.MXR90, Point(0, 0))
    assert t.apply(p) == Point(20, 10)


def test_transform_invert():
    t = dbTransform(dbOrientType.R90, Point(100, 200))
    inv = t.invert()
    p = Point(50, 60)
    p_fwd = t.apply(p)
    p_back = inv.apply(p_fwd)
    assert p_back == p
