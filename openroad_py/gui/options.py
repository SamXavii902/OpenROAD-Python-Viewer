"""Display options and color configuration ported from OpenROAD displayControls.cpp & options.h."""

from typing import Dict, Optional, Tuple
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from openroad_py.odb.tech import dbTech, dbTechLayer
from openroad_py.odb.types import dbTechLayerType


# Default metal colors from OpenROAD gui/src/displayControls.cpp:2095
DEFAULT_METAL_COLORS = [
    QColor(0, 0, 254, 180),      # Metal 1
    QColor(254, 0, 0, 180),      # Metal 2
    QColor(9, 221, 0, 180),      # Metal 3
    QColor(190, 244, 81, 180),   # Metal 4
    QColor(222, 33, 96, 180),    # Metal 5
    QColor(32, 216, 253, 180),   # Metal 6
    QColor(253, 108, 160, 180),  # Metal 7
    QColor(117, 63, 194, 180),   # Metal 8
    QColor(128, 155, 49, 180),   # Metal 9
    QColor(234, 63, 252, 180),   # Metal 10
    QColor(9, 96, 19, 180),      # Metal 11
    QColor(214, 120, 239, 180),  # Metal 12
    QColor(192, 222, 164, 180),  # Metal 13
    QColor(110, 68, 107, 180),   # Metal 14
]

# Default cut colors from OpenROAD gui/src/displayControls.cpp:2110
DEFAULT_CUT_COLORS = [
    QColor(126, 126, 255, 180),  # Cut 1
    QColor(255, 126, 126, 180),  # Cut 2
    QColor(4, 110, 0, 180),      # Cut 3
    QColor(95, 122, 40, 180),    # Cut 4
    QColor(111, 17, 48, 180),    # Cut 5
    QColor(16, 108, 126, 180),   # Cut 6
    QColor(126, 54, 80, 180),    # Cut 7
    QColor(58, 32, 97, 180),     # Cut 8
    QColor(225, 255, 136, 180),  # Cut 9
    QColor(117, 32, 126, 180),   # Cut 10
    QColor(18, 192, 38, 180),    # Cut 11
    QColor(107, 60, 119, 180),   # Cut 12
    QColor(96, 111, 82, 180),    # Cut 13
    QColor(220, 136, 214, 180),  # Cut 14
]


class DisplayOptions:
    """Controls visibility, layer colors, and rendering modes."""

    def __init__(self):
        # Layer attributes
        self._layer_visible: Dict[str, bool] = {}
        self._layer_color: Dict[str, QColor] = {}
        self._layer_pattern: Dict[str, Qt.BrushStyle] = {}

        # Category visibility switches (mirrors DisplayControls)
        self._show_instances: bool = True
        self._show_standard_cells: bool = True
        self._show_macros: bool = True
        self._show_instance_outlines: bool = True
        self._show_instance_names: bool = True
        self._show_instance_pins: bool = True
        self._show_instance_blockages: bool = True
        self._show_routing_segments: bool = True
        self._show_routing_vias: bool = True
        self._show_special_routing_segments: bool = True
        self._show_special_routing_vias: bool = True
        self._show_blockages: bool = True
        self._show_obstructions: bool = True
        self._show_fills: bool = True
        self._show_io_pins: bool = True
        self._show_tracks: bool = True
        self._show_pref_tracks: bool = True
        self._show_non_pref_tracks: bool = False
        self._show_rows: bool = True
        self._show_sites: bool = True
        self._show_scale_bar: bool = True
        self._detailed_visibility: bool = False
        self._show_density_heatmap: bool = False
        self._show_flightlines: bool = True

        # Colors
        self._site_color: QColor = QColor(0, 0xFF, 0, 0x70)
        self._blockage_color: QColor = QColor(100, 100, 100, 150)
        self._instance_name_color: QColor = QColor(255, 255, 255, 200)
        self._macro_color: QColor = QColor(130, 50, 210, 180)
        self._macro_border_color: QColor = QColor(210, 140, 255)
        self._cell_color: QColor = QColor(120, 120, 120)
        self._die_color: QColor = QColor(180, 180, 180)
        self._core_color: QColor = QColor(90, 90, 90)
        self._io_pin_color: QColor = QColor(76, 175, 80)
        self._ruler_color: QColor = QColor(255, 235, 59)

    def tech_init(self, tech: dbTech) -> None:
        """Initializes default layer colors and patterns matching OpenROAD DisplayControls::techInit."""
        metal_idx = 0
        cut_idx = 0

        # Pseudo-random generator seeded with 1 for consistent colors (L2129)
        import random
        rng = random.Random(1)

        for layer in tech.getLayers():
            lname = layer.getName().upper()
            ltype = layer.getType()

            if layer.isBackside():
                color = QColor(50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 180)
            elif ltype == dbTechLayerType.ROUTING:
                if metal_idx < len(DEFAULT_METAL_COLORS):
                    color = DEFAULT_METAL_COLORS[metal_idx]
                    metal_idx += 1
                else:
                    color = QColor(50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 180)
            elif ltype == dbTechLayerType.CUT:
                if cut_idx < len(DEFAULT_CUT_COLORS):
                    color = DEFAULT_CUT_COLORS[cut_idx]
                    cut_idx += 1
                else:
                    color = QColor(50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 180)
            else:
                color = QColor(50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 50 + rng.randint(0, 199), 180)

            self._layer_color[lname] = color
            self._layer_visible[lname] = True
            self._layer_pattern[lname] = Qt.SolidPattern

    def isVisible(self, layer: Optional[dbTechLayer]) -> bool:
        if layer is None:
            return True
        return self._layer_visible.get(layer.getName().upper(), True)

    def setVisible(self, layer: dbTechLayer, visible: bool) -> None:
        self._layer_visible[layer.getName().upper()] = visible

    def color(self, layer: dbTechLayer) -> QColor:
        lname = layer.getName().upper()
        if lname not in self._layer_color:
            return QColor(180, 180, 180, 180)
        return self._layer_color[lname]

    def setColor(self, layer: dbTechLayer, color: QColor) -> None:
        self._layer_color[layer.getName().upper()] = color

    def pattern(self, layer: dbTechLayer) -> Qt.BrushStyle:
        return self._layer_pattern.get(layer.getName().upper(), Qt.SolidPattern)

    # Category accessors
    def areInstancesVisible(self) -> bool:
        return self._show_instances

    def areStandardCellsVisible(self) -> bool:
        return self._show_standard_cells

    def setStandardCellsVisible(self, visible: bool) -> None:
        self._show_standard_cells = visible

    def areMacrosVisible(self) -> bool:
        return self._show_macros

    def setMacrosVisible(self, visible: bool) -> None:
        self._show_macros = visible

    def areInstanceOutlinesVisible(self) -> bool:
        return self._show_instance_outlines

    def areInstanceNamesVisible(self) -> bool:
        return self._show_instance_names

    def areInstancePinsVisible(self) -> bool:
        return self._show_instance_pins

    def areInstanceBlockagesVisible(self) -> bool:
        return self._show_instance_blockages

    def areRoutingSegmentsVisible(self) -> bool:
        return self._show_routing_segments

    def areRoutingViasVisible(self) -> bool:
        return self._show_routing_vias

    def areSpecialRoutingSegmentsVisible(self) -> bool:
        return self._show_special_routing_segments

    def areSpecialRoutingViasVisible(self) -> bool:
        return self._show_special_routing_vias

    def areBlockagesVisible(self) -> bool:
        return self._show_blockages

    def areObstructionsVisible(self) -> bool:
        return self._show_obstructions

    def areFillsVisible(self) -> bool:
        return self._show_fills

    def areIOPinsVisible(self) -> bool:
        return self._show_io_pins

    def areTracksVisible(self) -> bool:
        return self._show_tracks

    def arePrefTracksVisible(self) -> bool:
        return self._show_tracks and self._show_pref_tracks

    def areNonPrefTracksVisible(self) -> bool:
        return self._show_tracks and self._show_non_pref_tracks

    def areRowsVisible(self) -> bool:
        return self._show_rows

    def areSitesVisible(self) -> bool:
        return self._show_sites

    def isScaleBarVisible(self) -> bool:
        return self._show_scale_bar

    def isDetailedVisibility(self) -> bool:
        return self._detailed_visibility

    def siteColor(self) -> QColor:
        return self._site_color

    def placementBlockageColor(self) -> QColor:
        return self._blockage_color

    def placementBlockagePattern(self) -> Qt.BrushStyle:
        return Qt.BDiagPattern

    def instanceNameColor(self) -> QColor:
        return self._instance_name_color

    def macroColor(self) -> QColor:
        return self._macro_color

    def setMacroColor(self, color: QColor) -> None:
        self._macro_color = color

    def macroBorderColor(self) -> QColor:
        return self._macro_border_color

    def setMacroBorderColor(self, color: QColor) -> None:
        self._macro_border_color = color

    def cellColor(self) -> QColor:
        return self._cell_color

    def setCellColor(self, color: QColor) -> None:
        self._cell_color = color

    def dieColor(self) -> QColor:
        return self._die_color

    def setDieColor(self, color: QColor) -> None:
        self._die_color = color

    def coreColor(self) -> QColor:
        return self._core_color

    def setCoreColor(self, color: QColor) -> None:
        self._core_color = color

    def ioPinColor(self) -> QColor:
        return self._io_pin_color

    def setIoPinColor(self, color: QColor) -> None:
        self._io_pin_color = color

    def rulerColor(self) -> QColor:
        return self._ruler_color

    def setRulerColor(self, color: QColor) -> None:
        self._ruler_color = color

    def showDensityHeatmap(self) -> bool:
        return self._show_density_heatmap

    def setShowDensityHeatmap(self, val: bool) -> None:
        self._show_density_heatmap = val

    def showFlightlines(self) -> bool:
        return self._show_flightlines

    def setShowFlightlines(self, val: bool) -> None:
        self._show_flightlines = val

