"""Top-level database and chip container ported from RISHI OpenDB (dbDatabase, dbChip)."""

from typing import List, Optional
from rishi.odb.tech import dbTech
from rishi.odb.lib import dbLib
from rishi.odb.block import dbBlock
from rishi.odb.geom import Rect


class dbChip:
    """Represents a chip container having a top-level dbBlock."""

    def __init__(self, db: "dbDatabase", block: dbBlock):
        self._db: "dbDatabase" = db
        self._block: dbBlock = block
        self._chip_insts: List = []

    def getDb(self) -> "dbDatabase":
        return self._db

    def getBlock(self) -> dbBlock:
        return self._block

    def getTech(self) -> dbTech:
        return self._block.getTech()

    def getChipInsts(self) -> List:
        return self._chip_insts

    def getWidth(self) -> int:
        return self._block.getDieArea().dx()

    def getHeight(self) -> int:
        return self._block.getDieArea().dy()

    def getBBox(self) -> Rect:
        return self._block.getDieArea()

    def __repr__(self) -> str:
        return f"dbChip({self._block.getName()})"


class dbDatabase:
    """Top-level OpenDB database holding the technology, libraries, and chip."""

    def __init__(self):
        self._tech: Optional[dbTech] = None
        self._libs: List[dbLib] = []
        self._chip: Optional[dbChip] = None

    def getTech(self) -> Optional[dbTech]:
        return self._tech

    def setTech(self, tech: dbTech) -> None:
        self._tech = tech

    def getLibs(self) -> List[dbLib]:
        return self._libs

    def addLib(self, lib: dbLib) -> None:
        self._libs.append(lib)

    def getChip(self) -> Optional[dbChip]:
        return self._chip

    def setChip(self, chip: dbChip) -> None:
        self._chip = chip

    def getDbuPerMicron(self) -> int:
        if self._tech:
            return self._tech.getDbuPerMicron()
        return 1000

    def __repr__(self) -> str:
        tech_str = self._tech.getName() if hasattr(self._tech, "getName") else "Tech"
        return f"dbDatabase({tech_str}, {len(self._libs)} libs, chip={self._chip})"
