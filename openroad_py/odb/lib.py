"""Library and cell macro classes ported from OpenROAD OpenDB (dbMaster, dbMTerm, dbMPin, dbBox, dbLib)."""

from typing import List, Optional, Dict
from openroad_py.odb.geom import Rect, Polygon, Point
from openroad_py.odb.tech import dbTechLayer, dbTechVia
from openroad_py.odb.types import dbMasterType, dbSigType


class dbBox:
    """Represents a geometric shape box on a specific tech layer."""

    __slots__ = ("_layer", "_rect", "_is_via", "_tech_via", "_via_xy")

    def __init__(
        self,
        layer: Optional[dbTechLayer],
        rect: Rect,
        is_via: bool = False,
        tech_via: Optional[dbTechVia] = None,
        via_xy: Optional[Point] = None,
    ):
        self._layer: Optional[dbTechLayer] = layer
        self._rect: Rect = rect
        self._is_via: bool = is_via
        self._tech_via: Optional[dbTechVia] = tech_via
        self._via_xy: Point = via_xy if via_xy is not None else Point(0, 0)

    def getTechLayer(self) -> Optional[dbTechLayer]:
        return self._layer

    def getBox(self) -> Rect:
        return self._rect

    def xMin(self) -> int:
        return self._rect.xMin()

    def yMin(self) -> int:
        return self._rect.yMin()

    def xMax(self) -> int:
        return self._rect.xMax()

    def yMax(self) -> int:
        return self._rect.yMax()

    def dx(self) -> int:
        return self._rect.dx()

    def dy(self) -> int:
        return self._rect.dy()

    def isVia(self) -> bool:
        return self._is_via

    def getTechVia(self) -> Optional[dbTechVia]:
        return self._tech_via

    def getViaXY(self) -> Point:
        return self._via_xy

    def getDX(self) -> int:
        return self._rect.dx()

    def getDY(self) -> int:
        return self._rect.dy()

    def xMin(self) -> int:
        return self._rect.xMin()

    def yMin(self) -> int:
        return self._rect.yMin()

    def xMax(self) -> int:
        return self._rect.xMax()

    def yMax(self) -> int:
        return self._rect.yMax()

    def __repr__(self) -> str:
        layer_name = self._layer.getName() if self._layer else "None"
        return f"dbBox({layer_name}, {self._rect})"


class dbMPin:
    """Represents a physical port / pin of a cell master."""

    def __init__(self):
        self._boxes: List[dbBox] = []
        self._polygons: List[tuple[dbTechLayer, Polygon]] = []

    def addGeometry(self, box: dbBox) -> None:
        self._boxes.append(box)

    def addPolygon(self, layer: dbTechLayer, poly: Polygon) -> None:
        self._polygons.append((layer, poly))

    def getGeometry(self, include_vias: bool = True) -> List[dbBox]:
        if include_vias:
            return self._boxes
        return [b for b in self._boxes if not b.isVia()]

    def getPolygonGeometry(self) -> List[tuple[dbTechLayer, Polygon]]:
        return self._polygons


class dbMTerm:
    """Represents a master terminal (pin interface) of a cell master."""

    def __init__(self, name: str, sig_type: dbSigType = dbSigType.SIGNAL):
        self._name: str = name
        self._sig_type: dbSigType = sig_type
        self._mpins: List[dbMPin] = []

    def getName(self) -> str:
        return self._name

    def getConstName(self) -> str:
        return self._name

    def getSigType(self) -> dbSigType:
        return self._sig_type

    def setSigType(self, sig_type: dbSigType) -> None:
        self._sig_type = sig_type

    def addMPin(self, mpin: dbMPin) -> None:
        self._mpins.append(mpin)

    def getMPins(self) -> List[dbMPin]:
        return self._mpins

    def __repr__(self) -> str:
        return f"dbMTerm({self._name}, {len(self._mpins)} mpins)"


class dbMaster:
    """Represents a standard cell or macro definition from LEF."""

    def __init__(self, name: str, master_type: dbMasterType = dbMasterType.CORE):
        self._name: str = name
        self._type: dbMasterType = master_type
        self._width: int = 0
        self._height: int = 0
        self._origin: Point = Point(0, 0)
        self._mterms: List[dbMTerm] = []
        self._mterms_by_name: Dict[str, dbMTerm] = {}
        self._obstructions: List[dbBox] = []
        self._poly_obstructions: List[tuple[dbTechLayer, Polygon]] = []

    def getName(self) -> str:
        return self._name

    def getType(self) -> dbMasterType:
        return self._type

    def setType(self, t: dbMasterType) -> None:
        self._type = t

    def getWidth(self) -> int:
        return self._width

    def getHeight(self) -> int:
        return self._height

    def setWidth(self, w: int) -> None:
        self._width = w

    def setHeight(self, h: int) -> None:
        self._height = h

    def getOrigin(self) -> Point:
        return self._origin

    def setOrigin(self, pt: Point) -> None:
        self._origin = Point(pt.x, pt.y)

    def getPlacementBoundary(self, box: Optional[Rect] = None) -> Rect:
        res = Rect(
            -self._origin.x,
            -self._origin.y,
            self._width - self._origin.x,
            self._height - self._origin.y,
        )
        if box is not None:
            box.set_xlo(res.xMin())
            box.set_ylo(res.yMin())
            box.set_xhi(res.xMax())
            box.set_yhi(res.yMax())
        return res

    def getBBox(self) -> Rect:
        return self.getPlacementBoundary()

    def isCore(self) -> bool:
        return self._type in (
            dbMasterType.CORE,
            dbMasterType.CORE_ANTENNACELL,
            dbMasterType.CORE_FEEDTHRU,
            dbMasterType.CORE_TIEHIGH,
            dbMasterType.CORE_TIELOW,
            dbMasterType.CORE_WELLTAP,
            dbMasterType.CORE_SPACER,
        )

    def isBlock(self) -> bool:
        return self._type == dbMasterType.BLOCK

    def isPad(self) -> bool:
        return self._type in (
            dbMasterType.PAD,
            dbMasterType.PAD_INPUT,
            dbMasterType.PAD_OUTPUT,
            dbMasterType.PAD_INOUT,
            dbMasterType.PAD_POWER,
            dbMasterType.PAD_SPACER,
            dbMasterType.PAD_AREAIO,
        )

    def addMTerm(self, mterm: dbMTerm) -> None:
        self._mterms.append(mterm)
        self._mterms_by_name[mterm.getName().upper()] = mterm

    def getMTerms(self) -> List[dbMTerm]:
        return self._mterms

    def findMTerm(self, name: str) -> Optional[dbMTerm]:
        return self._mterms_by_name.get(name.upper())

    def addObstruction(self, box: dbBox) -> None:
        self._obstructions.append(box)

    def addPolyObstruction(self, layer: dbTechLayer, poly: Polygon) -> None:
        self._poly_obstructions.append((layer, poly))

    def getObstructions(self, include_vias: bool = True) -> List[dbBox]:
        return self._obstructions

    def getPolygonObstructions(self) -> List[tuple[dbTechLayer, Polygon]]:
        return self._poly_obstructions

    def __repr__(self) -> str:
        return f"dbMaster({self._name}, {self._width}x{self._height}, {len(self._mterms)} terms)"


class dbLib:
    """Represents a standard cell library container."""

    def __init__(self, name: str = ""):
        self._name: str = name
        self._masters: List[dbMaster] = []
        self._masters_by_name: Dict[str, dbMaster] = {}

    def getName(self) -> str:
        return self._name

    def addMaster(self, master: dbMaster) -> None:
        self._masters.append(master)
        self._masters_by_name[master.getName().upper()] = master

    def getMasters(self) -> List[dbMaster]:
        return self._masters

    def findMaster(self, name: str) -> Optional[dbMaster]:
        return self._masters_by_name.get(name.upper())

    def __repr__(self) -> str:
        return f"dbLib({len(self._masters)} masters)"
