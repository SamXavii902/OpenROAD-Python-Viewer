"""Design block and layout elements ported from OpenROAD OpenDB."""

from typing import List, Optional, Dict, Tuple
from openroad_py.odb.geom import Point, Rect, Polygon
from openroad_py.odb.types import (
    dbOrientType,
    dbPlacementStatus,
    dbSigType,
    dbTechLayerDir,
    dbWireType,
)
from openroad_py.odb.transform import dbTransform
from openroad_py.odb.tech import dbTech, dbTechLayer, dbTechVia, dbSite
from openroad_py.odb.lib import dbMaster, dbMTerm, dbBox


class dbITerm:
    """Instance terminal connecting an instance pin to a net."""

    def __init__(self, inst: "dbInst", mterm: dbMTerm):
        self._inst: "dbInst" = inst
        self._mterm: dbMTerm = mterm
        self._net: Optional["dbNet"] = None

    def getInst(self) -> "dbInst":
        return self._inst

    def getMTerm(self) -> dbMTerm:
        return self._mterm

    def getNet(self) -> Optional["dbNet"]:
        return self._net

    def setNet(self, net: Optional["dbNet"]) -> None:
        self._net = net


class dbInst:
    """Represents a placed standard cell or macro instance."""

    def __init__(self, block: "dbBlock", master: dbMaster, name: str):
        self._block: "dbBlock" = block
        self._master: dbMaster = master
        self._name: str = name
        self._origin: Point = Point(0, 0)
        self._orient: dbOrientType = dbOrientType.R0
        self._status: dbPlacementStatus = dbPlacementStatus.UNPLACED
        self._iterms: List[dbITerm] = []
        for mterm in master.getMTerms():
            self._iterms.append(dbITerm(self, mterm))
        self._halo: Rect = Rect(0, 0, 0, 0)

    def getBlock(self) -> "dbBlock":
        return self._block

    def getMaster(self) -> dbMaster:
        return self._master

    def getName(self) -> str:
        return self._name

    def getOrigin(self) -> Point:
        return self._origin

    def setOrigin(self, x: int, y: int) -> None:
        self._origin = Point(x, y)

    def getOrient(self) -> dbOrientType:
        return self._orient

    def setOrient(self, orient: dbOrientType) -> None:
        self._orient = orient

    def getPlacementStatus(self) -> dbPlacementStatus:
        return self._status

    def setPlacementStatus(self, status: dbPlacementStatus) -> None:
        self._status = status

    def isPlaced(self) -> bool:
        return self._status not in (dbPlacementStatus.NONE, dbPlacementStatus.UNPLACED)

    def getLocation(self) -> Point:
        bbox = self.getBBox().getBox()
        return Point(bbox.xMin(), bbox.yMin())

    def setLocation(self, x: int, y: int) -> None:
        """Sets lower-left position of the placed component, matching OpenROAD definComponent.cpp:
        _cur_inst->setOrigin(dbdist(x) - bbox.xMin(), dbdist(y) - bbox.yMin())
        """
        master = self._master
        if master is not None:
            bbox = master.getPlacementBoundary()
            t = dbTransform(self._orient)
            transformed = t.apply(bbox)
            self.setOrigin(x - transformed.xMin(), y - transformed.yMin())
        else:
            self.setOrigin(x, y)

    def getTransform(self) -> dbTransform:
        return dbTransform(self._orient, self._origin)

    def getBBox(self) -> dbBox:
        xfm = self.getTransform()
        master_box = self._master.getPlacementBoundary()
        placed_rect = xfm.apply(master_box)
        return dbBox(None, placed_rect)

    def getITerms(self) -> List[dbITerm]:
        return self._iterms

    def getITerm(self, name: str) -> Optional[dbITerm]:
        for it in self._iterms:
            if it.getMTerm().getName() == name:
                return it
        # If terminal was not pre-declared in LEF, dynamically create it to preserve connectivity
        mterm = self._master.findMTerm(name)
        if mterm is None:
            mterm = dbMTerm(name)
            self._master.addMTerm(mterm)
        it = dbITerm(self, mterm)
        self._iterms.append(it)
        return it

    def getTransformedHalo(self) -> Rect:
        return self._halo

    def setHalo(self, halo: Rect) -> None:
        self._halo = halo

    def __repr__(self) -> str:
        return f"dbInst({self._name}, master={self._master.getName()}, at={self._origin}, {self._orient.name})"


class dbBPin:
    """Physical pin geometry for a block terminal (IO pin)."""

    def __init__(self):
        self._boxes: List[Tuple[dbTechLayer, Rect]] = []
        self._polygons: List[Tuple[dbTechLayer, Polygon]] = []
        self._placement_status: dbPlacementStatus = dbPlacementStatus.PLACED
        self._loc: Optional[Point] = None
        self._orient: dbOrientType = dbOrientType.R0

    def addBox(self, layer: dbTechLayer, box: Rect) -> None:
        self._boxes.append((layer, box))

    def addPolygon(self, layer: dbTechLayer, poly: Polygon) -> None:
        self._polygons.append((layer, poly))

    def getBoxes(self) -> List[Tuple[dbTechLayer, Rect]]:
        return self._boxes

    def getPolygons(self) -> List[Tuple[dbTechLayer, Polygon]]:
        return self._polygons

    def getPlacementStatus(self) -> dbPlacementStatus:
        return self._placement_status

    def setPlacementStatus(self, status: dbPlacementStatus) -> None:
        self._placement_status = status

    def setLoc(self, pt: Point) -> None:
        self._loc = pt

    def getLoc(self) -> Optional[Point]:
        return self._loc

    def hasLoc(self) -> bool:
        return self._loc is not None

    def setOrient(self, orient: dbOrientType) -> None:
        self._orient = orient

    def getOrient(self) -> dbOrientType:
        return self._orient


class dbBTerm:
    """Block terminal (primary IO pin)."""

    def __init__(self, block: "dbBlock", name: str, sig_type: dbSigType = dbSigType.SIGNAL):
        self._block: "dbBlock" = block
        self._name: str = name
        self._sig_type: dbSigType = sig_type
        self._bpins: List[dbBPin] = []
        self._net: Optional["dbNet"] = None

    def getName(self) -> str:
        return self._name

    def getSigType(self) -> dbSigType:
        return self._sig_type

    def setSigType(self, sig_type: dbSigType) -> None:
        self._sig_type = sig_type

    def addBPin(self, bpin: dbBPin) -> None:
        self._bpins.append(bpin)

    def getBPins(self) -> List[dbBPin]:
        return self._bpins

    def getNet(self) -> Optional["dbNet"]:
        return self._net

    def setNet(self, net: Optional["dbNet"]) -> None:
        self._net = net

    def getBBox(self) -> Rect:
        bbox: Optional[Rect] = None
        for bpin in self._bpins:
            for _, box in bpin.getBoxes():
                if bbox is None:
                    bbox = Rect(box.xMin(), box.yMin(), box.xMax(), box.yMax())
                else:
                    bbox.merge(box)
            for _, poly in bpin.getPolygons():
                er = poly.getEnclosingRect()
                if bbox is None:
                    bbox = Rect(er.xMin(), er.yMin(), er.xMax(), er.yMax())
                else:
                    bbox.merge(er)
        if bbox is None:
            for bpin in self._bpins:
                if bpin.hasLoc():
                    loc = bpin.getLoc()
                    d = 140  # 0.14um nominal pin half-width
                    return Rect(loc.x - d, loc.y - d, loc.x + d, loc.y + d)
            return Rect(0, 0, 0, 0)
        return bbox

    def getBoxes(self):
        boxes = []
        for bpin in self._bpins:
            boxes.extend(bpin.getBoxes())
        return boxes

    def __repr__(self) -> str:
        return f"dbBTerm({self._name}, {len(self._bpins)} pins)"


class dbRow:
    """Standard cell placement row."""

    def __init__(
        self,
        block: "dbBlock",
        name: str,
        site: dbSite,
        origin: Point,
        orient: dbOrientType,
        direction: dbTechLayerDir,
        num_sites: int,
        spacing: int,
    ):
        self._block: "dbBlock" = block
        self._name: str = name
        self._site: dbSite = site
        self._origin: Point = Point(origin.x, origin.y)
        self._orient: dbOrientType = orient
        self._dir: dbTechLayerDir = direction
        self._site_count: int = num_sites
        self._spacing: int = spacing

    def getName(self) -> str:
        return self._name

    def getSite(self) -> dbSite:
        return self._site

    def getOrigin(self) -> Point:
        return self._origin

    def getOrient(self) -> dbOrientType:
        return self._orient

    def getDirection(self) -> dbTechLayerDir:
        return self._dir

    def getSiteCount(self) -> int:
        return self._site_count

    def getSpacing(self) -> int:
        return self._spacing

    def getBBox(self) -> Rect:
        w = self._site.getWidth()
        h = self._site.getHeight()
        if self._orient in (dbOrientType.R90, dbOrientType.R270, dbOrientType.MYR90, dbOrientType.MXR90):
            w, h = h, w
        if self._dir == dbTechLayerDir.HORIZONTAL:
            total_w = self._spacing * self._site_count
            total_h = h
        else:
            total_w = w
            total_h = self._spacing * self._site_count
        return Rect(self._origin.x, self._origin.y, self._origin.x + total_w, self._origin.y + total_h)

    def __repr__(self) -> str:
        return f"dbRow({self._name}, site={self._site.getName()}, count={self._site_count})"


class dbTrackGrid:
    """Routing track grid for a layer."""

    def __init__(self, layer: dbTechLayer):
        self._layer: dbTechLayer = layer
        self._grid_patterns_x: List[Tuple[int, int, int]] = []  # (origin, count, step)
        self._grid_patterns_y: List[Tuple[int, int, int]] = []

    def getTechLayer(self) -> dbTechLayer:
        return self._layer

    def addGridPatternX(self, origin: int, count: int, step: int) -> None:
        self._grid_patterns_x.append((origin, count, step))

    def addGridPatternY(self, origin: int, count: int, step: int) -> None:
        self._grid_patterns_y.append((origin, count, step))

    def getNumGridPatternsX(self) -> int:
        return len(self._grid_patterns_x)

    def getNumGridPatternsY(self) -> int:
        return len(self._grid_patterns_y)

    def getGridPatternX(self, idx: int) -> Tuple[int, int, int]:
        return self._grid_patterns_x[idx]

    def getGridPatternY(self, idx: int) -> Tuple[int, int, int]:
        return self._grid_patterns_y[idx]

    def getGridX(self) -> List[int]:
        coords: List[int] = []
        for orig, count, step in self._grid_patterns_x:
            for i in range(count):
                coords.append(orig + i * step)
        return sorted(set(coords))

    def getGridY(self) -> List[int]:
        coords: List[int] = []
        for orig, count, step in self._grid_patterns_y:
            for i in range(count):
                coords.append(orig + i * step)
        return sorted(set(coords))


class dbObstruction:
    """Routing obstruction on a specific layer."""

    __slots__ = ("_layer", "_box")

    def __init__(self, layer: dbTechLayer, box: Rect):
        self._layer: dbTechLayer = layer
        self._box: Rect = box

    def getTechLayer(self) -> dbTechLayer:
        return self._layer

    def getBBox(self) -> dbBox:
        return dbBox(self._layer, self._box)

    def getBox(self) -> Rect:
        return self._box


class dbBlockage:
    """Placement blockage."""

    __slots__ = ("_box", "_is_soft")

    def __init__(self, box: Rect, is_soft: bool = False):
        self._box: Rect = box
        self._is_soft: bool = is_soft

    def getBBox(self) -> dbBox:
        return dbBox(None, self._box)

    def getBox(self) -> Rect:
        return self._box

    def isSoft(self) -> bool:
        return self._is_soft


class dbFill:
    """Fill rect on a specific layer."""

    __slots__ = ("_layer", "_box")

    def __init__(self, layer: dbTechLayer, box: Rect):
        self._layer: dbTechLayer = layer
        self._box: Rect = box

    def getTechLayer(self) -> dbTechLayer:
        return self._layer

    def getRect(self, out: Rect) -> None:
        out.set_xlo(self._box.xMin())
        out.set_ylo(self._box.yMin())
        out.set_xhi(self._box.xMax())
        out.set_yhi(self._box.yMax())

    def getBox(self) -> Rect:
        return self._box


class RouteShape:
    """A single routing shape: wire segment or via box."""

    __slots__ = ("layer", "box", "is_via", "tech_via", "poly")

    def __init__(
        self,
        layer: dbTechLayer,
        box: Rect,
        is_via: bool = False,
        tech_via: Optional[dbTechVia] = None,
        poly: Optional[Polygon] = None,
    ):
        self.layer: dbTechLayer = layer
        self.box: Rect = box
        self.is_via: bool = is_via
        self.tech_via: Optional[dbTechVia] = tech_via
        self.poly: Optional[Polygon] = poly


class dbNet:
    """Signal or power/ground net."""

    def __init__(self, block: "dbBlock", name: str, sig_type: dbSigType = dbSigType.SIGNAL):
        self._block: "dbBlock" = block
        self._name: str = name
        self._sig_type: dbSigType = sig_type
        self._wire_shapes: List[RouteShape] = []
        self._special_wire_shapes: List[RouteShape] = []
        self._iterms: List["dbITerm"] = []
        self._bterms: List["dbBTerm"] = []

    def addITerm(self, iterm: "dbITerm") -> None:
        self._iterms.append(iterm)

    def getITerms(self) -> List["dbITerm"]:
        return self._iterms

    def addBTerm(self, bterm: "dbBTerm") -> None:
        self._bterms.append(bterm)

    def getBTerms(self) -> List["dbBTerm"]:
        return self._bterms

    def getBlock(self) -> "dbBlock":
        return self._block

    def getName(self) -> str:
        return self._name

    def getSigType(self) -> dbSigType:
        return self._sig_type

    def setSigType(self, sig_type: dbSigType) -> None:
        self._sig_type = sig_type

    def isSpecial(self) -> bool:
        return self._sig_type in (dbSigType.POWER, dbSigType.GROUND)

    def addWireShape(self, shape: RouteShape) -> None:
        self._wire_shapes.append(shape)

    def addSpecialWireShape(self, shape: RouteShape) -> None:
        self._special_wire_shapes.append(shape)

    def getWireShapes(self) -> List[RouteShape]:
        return self._wire_shapes

    def getSpecialWireShapes(self) -> List[RouteShape]:
        return self._special_wire_shapes

    def __repr__(self) -> str:
        return f"dbNet({self._name}, {self._sig_type.name}, {len(self._wire_shapes)} wires, {len(self._special_wire_shapes)} swires)"


class dbBlock:
    """Top-level chip design block containing all physical layout objects."""

    def __init__(self, tech: dbTech, name: str = ""):
        self._tech: dbTech = tech
        self._name: str = name
        self._die_area_rect: Rect = Rect(0, 0, 0, 0)
        self._die_area_poly: Polygon = Polygon()
        self._core_area_rect: Rect = Rect(0, 0, 0, 0)
        self._core_area_poly: Polygon = Polygon()
        self._insts: List[dbInst] = []
        self._insts_by_name: Dict[str, dbInst] = {}
        self._nets: List[dbNet] = []
        self._nets_by_name: Dict[str, dbNet] = {}
        self._bterms: List[dbBTerm] = []
        self._bterms_by_name: Dict[str, dbBTerm] = {}
        self._rows: List[dbRow] = []
        self._track_grids: Dict[str, dbTrackGrid] = {}
        self._obstructions: List[dbObstruction] = []
        self._blockages: List[dbBlockage] = []
        self._fills: List[dbFill] = []
        self._block_vias: List[dbTechVia] = []
        self._block_vias_by_name: Dict[str, dbTechVia] = {}
        self._children: List["dbBlock"] = []

    def getTech(self) -> dbTech:
        return self._tech

    def getName(self) -> str:
        return self._name

    def setName(self, name: str) -> None:
        self._name = name

    def getDieArea(self) -> Rect:
        return self._die_area_rect

    def setDieArea(self, rect: Rect) -> None:
        self._die_area_rect = rect
        self._die_area_poly = Polygon(rect.getPoints())

    def getDieAreaPolygon(self) -> Polygon:
        return self._die_area_poly

    def setDieAreaPolygon(self, poly: Polygon) -> None:
        self._die_area_poly = poly
        self._die_area_rect = poly.getEnclosingRect()

    def getCoreArea(self) -> Rect:
        return self._core_area_rect

    def setCoreArea(self, rect: Rect) -> None:
        self._core_area_rect = rect
        self._core_area_poly = Polygon(rect.getPoints())

    def getCoreAreaPolygon(self) -> Polygon:
        return self._core_area_poly

    def getBBox(self) -> dbBox:
        return dbBox(None, self._die_area_rect)

    def addInst(self, inst: dbInst) -> None:
        self._insts.append(inst)
        self._insts_by_name[inst.getName()] = inst

    def getInsts(self) -> List[dbInst]:
        return self._insts

    def findInst(self, name: str) -> Optional[dbInst]:
        return self._insts_by_name.get(name)

    def addNet(self, net: dbNet) -> None:
        self._nets.append(net)
        self._nets_by_name[net.getName()] = net

    def getNets(self) -> List[dbNet]:
        return self._nets

    def findNet(self, name: str) -> Optional[dbNet]:
        return self._nets_by_name.get(name)

    def addBTerm(self, bterm: dbBTerm) -> None:
        self._bterms.append(bterm)
        self._bterms_by_name[bterm.getName()] = bterm

    def getBTerms(self) -> List[dbBTerm]:
        return self._bterms

    def findBTerm(self, name: str) -> Optional[dbBTerm]:
        return self._bterms_by_name.get(name)

    def addRow(self, row: dbRow) -> None:
        self._rows.append(row)

    def getRows(self) -> List[dbRow]:
        return self._rows

    def setTrackGrid(self, layer: dbTechLayer, grid: dbTrackGrid) -> None:
        self._track_grids[layer.getName().upper()] = grid

    def findTrackGrid(self, layer: dbTechLayer) -> Optional[dbTrackGrid]:
        return self._track_grids.get(layer.getName().upper())

    def addObstruction(self, obs: dbObstruction) -> None:
        self._obstructions.append(obs)

    def getObstructions(self) -> List[dbObstruction]:
        return self._obstructions

    def addBlockage(self, b: dbBlockage) -> None:
        self._blockages.append(b)

    def getBlockages(self) -> List[dbBlockage]:
        return self._blockages

    def addFill(self, fill: dbFill) -> None:
        self._fills.append(fill)

    def getFills(self) -> List[dbFill]:
        return self._fills

    def addVia(self, via: dbTechVia) -> None:
        self._block_vias.append(via)
        self._block_vias_by_name[via.getName().upper()] = via

    def findVia(self, name: str) -> Optional[dbTechVia]:
        v = self._block_vias_by_name.get(name.upper())
        if v:
            return v
        return self._tech.findVia(name)

    def getChildren(self) -> List["dbBlock"]:
        return self._children

    def findChild(self, name: str) -> Optional["dbBlock"]:
        for c in self._children:
            if c.getName() == name:
                return c
        return None

    def getMasters(self, out: List[dbMaster]) -> None:
        masters_set = set()
        for inst in self._insts:
            masters_set.add(inst.getMaster())
        out.extend(list(masters_set))

    def __repr__(self) -> str:
        return f"dbBlock({self._name}, {len(self._insts)} insts, {len(self._nets)} nets, {len(self._bterms)} bterms, {self._die_area_rect})"
