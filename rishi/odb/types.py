"""OpenDB types ported from RISHI odb/include/odb/dbTypes.h."""

from enum import Enum, auto


class dbOrientType(Enum):
    R0 = 0
    R90 = 1
    R180 = 2
    R270 = 3
    MY = 4
    MYR90 = 5
    MX = 6
    MXR90 = 7

    @classmethod
    def from_str(cls, s: str) -> "dbOrientType":
        name = s.strip().upper()
        # Aliases
        if name in ("N", "R0"):
            return cls.R0
        elif name in ("W", "R90"):
            return cls.R90
        elif name in ("S", "R180"):
            return cls.R180
        elif name in ("E", "R270"):
            return cls.R270
        elif name in ("FN", "MY"):
            return cls.MY
        elif name in ("FW", "MYR90", "MY90"):
            return cls.MYR90
        elif name in ("FS", "MX"):
            return cls.MX
        elif name in ("FE", "MXR90", "MX90"):
            return cls.MXR90
        raise ValueError(f"Unknown orientation string: {s}")


class dbTechLayerType(Enum):
    NONE = auto()
    ROUTING = auto()
    CUT = auto()
    MASTERSLICE = auto()
    OVERLAP = auto()
    IMPLANT = auto()
    DIFFUSION = auto()
    TRIM = auto()
    MIMCAP = auto()


class dbTechLayerDir(Enum):
    NONE = auto()
    HORIZONTAL = auto()
    VERTICAL = auto()


class dbSigType(Enum):
    SIGNAL = auto()
    POWER = auto()
    GROUND = auto()
    CLOCK = auto()
    TIEOFF = auto()
    ANALOG = auto()
    SCAN = auto()
    RESET = auto()


class dbIoType(Enum):
    INPUT = auto()
    OUTPUT = auto()
    INOUT = auto()
    FEEDTHRU = auto()


class dbMasterType(Enum):
    CORE = auto()
    CORE_ANTENNACELL = auto()
    CORE_FEEDTHRU = auto()
    CORE_TIEHIGH = auto()
    CORE_TIELOW = auto()
    CORE_WELLTAP = auto()
    CORE_SPACER = auto()
    BLOCK = auto()
    PAD = auto()
    PAD_INPUT = auto()
    PAD_OUTPUT = auto()
    PAD_INOUT = auto()
    PAD_POWER = auto()
    PAD_SPACER = auto()
    PAD_AREAIO = auto()
    RING = auto()
    ENDCAP = auto()
    ENDCAP_PRE = auto()
    ENDCAP_POST = auto()
    COVER = auto()


class dbPlacementStatus(Enum):
    NONE = auto()
    UNPLACED = auto()
    PLACED = auto()
    FIXED = auto()
    COVER = auto()
    FIRM = auto()
    SUGGESTED = auto()


class dbWireType(Enum):
    NONE = auto()
    COVER = auto()
    FIXED = auto()
    ROUTED = auto()
    SHIELD = auto()
    NOSHIELD = auto()


class dbWireShapeType(Enum):
    NONE = auto()
    RING = auto()
    PADRING = auto()
    BLOCKRING = auto()
    STRIPE = auto()
    FOLLOWPIN = auto()
    IOWIRE = auto()
    COREWIRE = auto()
    BLOCKWIRE = auto()
    BLOCKAGEWIRE = auto()
    FILLWIRE = auto()
    DRCFILL = auto()
