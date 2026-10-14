"""Technology classes ported from RISHI OpenDB (dbTech, dbTechLayer, dbTechVia, dbSite)."""

from typing import List, Optional, Dict
from rishi.odb.geom import Rect
from rishi.odb.types import dbTechLayerType, dbTechLayerDir


class dbTechLayer:
    """Represents a technology layer (routing, cut, masterslice, etc.)."""

    def __init__(
        self,
        name: str,
        layer_type: dbTechLayerType = dbTechLayerType.ROUTING,
        direction: dbTechLayerDir = dbTechLayerDir.NONE,
        width: int = 0,
        pitch: int = 0,
    ):
        self._name: str = name
        self._type: dbTechLayerType = layer_type
        self._direction: dbTechLayerDir = direction
        self._width: int = width
        self._spacing: int = 0
        self._pitch_x: int = pitch
        self._pitch_y: int = pitch
        self._routing_level: int = 0
        self._upper_layer: Optional["dbTechLayer"] = None
        self._lower_layer: Optional["dbTechLayer"] = None
        self._is_backside: bool = False

    def getName(self) -> str:
        return self._name

    def getType(self) -> dbTechLayerType:
        return self._type

    def getDirection(self) -> dbTechLayerDir:
        return self._direction

    def getWidth(self) -> int:
        return self._width

    def getSpacing(self) -> int:
        return self._spacing

    def getPitch(self) -> int:
        return self._pitch_x

    def getPitchX(self) -> int:
        return self._pitch_x

    def getPitchY(self) -> int:
        return self._pitch_y

    def getRoutingLevel(self) -> int:
        return self._routing_level

    def getUpperLayer(self) -> Optional["dbTechLayer"]:
        return self._upper_layer

    def getLowerLayer(self) -> Optional["dbTechLayer"]:
        return self._lower_layer

    def isBackside(self) -> bool:
        return self._is_backside

    def setType(self, t: dbTechLayerType) -> None:
        self._type = t

    def setDirection(self, d: dbTechLayerDir) -> None:
        self._direction = d

    def setWidth(self, w: int) -> None:
        self._width = w

    def setSpacing(self, s: int) -> None:
        self._spacing = s

    def setPitch(self, p: int) -> None:
        self._pitch_x = p
        self._pitch_y = p

    def setPitchXY(self, px: int, py: int) -> None:
        self._pitch_x = px
        self._pitch_y = py

    def setRoutingLevel(self, lvl: int) -> None:
        self._routing_level = lvl

    def setUpperLayer(self, layer: Optional["dbTechLayer"]) -> None:
        self._upper_layer = layer

    def setLowerLayer(self, layer: Optional["dbTechLayer"]) -> None:
        self._lower_layer = layer

    def __repr__(self) -> str:
        return f"dbTechLayer({self._name}, {self._type.name}, {self._direction.name}, w={self._width})"


class dbTechViaBox:
    """Box inside a via with layer reference."""

    __slots__ = ("_layer", "_box")

    def __init__(self, layer: dbTechLayer, box: Rect):
        self._layer: dbTechLayer = layer
        self._box: Rect = box

    def getTechLayer(self) -> dbTechLayer:
        return self._layer

    def getBox(self) -> Rect:
        return self._box

    def getDX(self) -> int:
        return self._box.dx()

    def getDY(self) -> int:
        return self._box.dy()

    def __repr__(self) -> str:
        return f"dbTechViaBox({self._layer.getName()}, {self._box})"


class dbTechVia:
    """Represents a standard via definition from LEF."""

    def __init__(self, name: str):
        self._name: str = name
        self._boxes: List[dbTechViaBox] = []

    def getName(self) -> str:
        return self._name

    def addBox(self, layer: dbTechLayer, box: Rect) -> None:
        self._boxes.append(dbTechViaBox(layer, box))

    def getBoxes(self) -> List[dbTechViaBox]:
        return self._boxes

    def getBBox(self) -> Rect:
        bbox = Rect(0, 0, 0, 0)
        for b in self._boxes:
            bbox.merge(b.getBox())
        return bbox

    def __repr__(self) -> str:
        return f"dbTechVia({self._name}, {len(self._boxes)} boxes)"


class dbSite:
    """Represents a standard cell placement site."""

    def __init__(self, name: str, width: int = 0, height: int = 0):
        self._name: str = name
        self._width: int = width
        self._height: int = height
        self._class: str = "CORE"

    def getName(self) -> str:
        return self._name

    def getWidth(self) -> int:
        return self._width

    def getHeight(self) -> int:
        return self._height

    def getClass(self) -> str:
        return self._class

    def setWidth(self, w: int) -> None:
        self._width = w

    def setHeight(self, h: int) -> None:
        self._height = h

    def setClass(self, c: str) -> None:
        self._class = c

    def __repr__(self) -> str:
        return f"dbSite({self._name}, {self._width}x{self._height})"


class dbTech:
    """Represents the technology database containing layers, vias, and sites."""

    def __init__(self, dbu_per_micron: int = 1000):
        self._name: str = "RISHI Tech"
        self._dbu_per_micron: int = dbu_per_micron
        self._layers: List[dbTechLayer] = []
        self._layers_by_name: Dict[str, dbTechLayer] = {}
        self._vias: List[dbTechVia] = []
        self._vias_by_name: Dict[str, dbTechVia] = {}
        self._sites: List[dbSite] = []
        self._sites_by_name: Dict[str, dbSite] = {}
        self._manufacturing_grid: int = 0

    def getName(self) -> str:
        return self._name

    def setName(self, name: str) -> None:
        self._name = name

    def getDbuPerMicron(self) -> int:
        return self._dbu_per_micron

    def setDbuPerMicron(self, dbu: int) -> None:
        self._dbu_per_micron = dbu

    def getManufacturingGrid(self) -> int:
        return self._manufacturing_grid

    def hasManufacturingGrid(self) -> bool:
        return self._manufacturing_grid > 0

    def setManufacturingGrid(self, grid: int) -> None:
        self._manufacturing_grid = grid

    def addLayer(self, layer: dbTechLayer) -> None:
        if self._layers:
            prev = self._layers[-1]
            prev.setUpperLayer(layer)
            layer.setLowerLayer(prev)
        self._layers.append(layer)
        self._layers_by_name[layer.getName().upper()] = layer

    def getLayers(self) -> List[dbTechLayer]:
        return self._layers

    def findLayer(self, name: str) -> Optional[dbTechLayer]:
        return self._layers_by_name.get(name.upper())

    def addVia(self, via: dbTechVia) -> None:
        self._vias.append(via)
        self._vias_by_name[via.getName().upper()] = via

    def getVias(self) -> List[dbTechVia]:
        return self._vias

    def findVia(self, name: str) -> Optional[dbTechVia]:
        return self._vias_by_name.get(name.upper())

    def addSite(self, site: dbSite) -> None:
        self._sites.append(site)
        self._sites_by_name[site.getName().upper()] = site

    def getSites(self) -> List[dbSite]:
        return self._sites

    def findSite(self, name: str) -> Optional[dbSite]:
        return self._sites_by_name.get(name.upper())

    def __repr__(self) -> str:
        return f"dbTech({len(self._layers)} layers, {len(self._vias)} vias, {len(self._sites)} sites)"
