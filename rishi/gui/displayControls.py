"""DisplayControls dock widget ported from RISHI gui/src/displayControls.cpp."""

from typing import Dict, Optional
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QColorDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap, QIcon, QPainter
from rishi.odb.tech import dbTech, dbTechLayer
from rishi.gui.options import DisplayOptions


class DisplayControls(QDockWidget):
    """Dock widget for controlling layer visibility and object display options."""

    option_toggled = Signal(str, bool)

    def __init__(self, viewer: "LayoutViewer", parent=None):
        super().__init__("Display Controls", parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self._viewer = viewer
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Feature", "Color"])
        self._tree.setColumnWidth(0, 160)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)
        self.setWidget(widget)

        self._layers_group: Optional[QTreeWidgetItem] = None
        self._objects_group: Optional[QTreeWidgetItem] = None
        self._layer_items: Dict[str, QTreeWidgetItem] = {}
        self._object_items: Dict[str, QTreeWidgetItem] = {}

        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._build_tree()

    def _create_color_icon(self, color: QColor) -> QIcon:
        pix = QPixmap(16, 16)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setBrush(color)
        p.setPen(Qt.black)
        p.drawRect(0, 0, 15, 15)
        p.end()
        return QIcon(pix)

    def _build_tree(self) -> None:
        self._tree.clear()
        self._layer_items.clear()
        self._object_items.clear()

        options = self._viewer.getOptions()

        # 1. Layers Group
        self._layers_group = QTreeWidgetItem(self._tree, ["Layers"])
        self._layers_group.setFlags(self._layers_group.flags() | Qt.ItemIsUserCheckable)
        self._layers_group.setCheckState(0, Qt.Checked)

        chip = self._viewer.getChip()
        if chip and chip.getTech():
            for layer in chip.getTech().getLayers():
                lname = layer.getName()
                color = options.color(layer)
                item = QTreeWidgetItem(self._layers_group, [lname])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if options.isVisible(layer) else Qt.Unchecked)
                item.setIcon(1, self._create_color_icon(color))
                item.setData(0, Qt.UserRole, layer)
                self._layer_items[lname.upper()] = item
        self._layers_group.setExpanded(True)

        # 2. General Objects Group
        self._objects_group = QTreeWidgetItem(self._tree, ["Objects"])
        self._objects_group.setExpanded(True)

        categories = [
            ("Die Boundary (Rect)", options.isDieBoundaryVisible(), "_show_die_boundary"),
            ("Polygon / Core Outline", options.isPolygonBoundaryVisible(), "_show_polygon_boundary"),
            ("Standard Cells", options.areStandardCellsVisible(), "_show_standard_cells"),
            ("Macros", options.areMacrosVisible(), "_show_macros"),
            ("Instance Outlines", options.areInstanceOutlinesVisible(), "_show_instance_outlines"),
            ("Instance Names", options.areInstanceNamesVisible(), "_show_instance_names"),
            ("Instance Pins", options.areInstancePinsVisible(), "_show_instance_pins"),
            ("Routing Wires", options.areRoutingSegmentsVisible(), "_show_routing_segments"),
            ("Routing Vias", options.areRoutingViasVisible(), "_show_routing_vias"),
            ("Special Nets", options.areSpecialRoutingSegmentsVisible(), "_show_special_routing_segments"),
            ("Blockages", options.areBlockagesVisible(), "_show_blockages"),
            ("Obstructions", options.areObstructionsVisible(), "_show_obstructions"),
            ("IO Pins", options.areIOPinsVisible(), "_show_io_pins"),
            ("Tracks", options.arePrefTracksVisible(), "_show_pref_tracks"),
            ("Rows & Sites", options.areRowsVisible(), "_show_rows"),
            ("Scale Bar", options.isScaleBarVisible(), "_show_scale_bar"),
            ("Placement Density Heatmap", options.showDensityHeatmap(), "_show_density_heatmap"),
            ("Ratsnest Flightlines", options.showFlightlines(), "_show_flightlines"),
        ]

        color_map = {
            "_show_die_boundary": options.dieColor(),
            "_show_polygon_boundary": options.polygonColor(),
            "_show_io_pins": options.ioPinColor(),
            "_show_blockages": options.placementBlockageColor(),
        }

        for name, checked, attr in categories:
            item = QTreeWidgetItem(self._objects_group, [name])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            item.setData(0, Qt.UserRole, attr)
            if attr in color_map:
                item.setIcon(1, self._create_color_icon(color_map[attr]))
            self._object_items[attr] = item

    def sync_option(self, attr: str, checked: bool) -> None:
        """Synchronizes checkbox state without re-triggering itemChanged handlers."""
        if attr in self._object_items:
            item = self._object_items[attr]
            self._tree.blockSignals(True)
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            self._tree.blockSignals(False)

    def refresh(self) -> None:
        self._build_tree()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return

        is_checked = item.checkState(0) == Qt.Checked
        data = item.data(0, Qt.UserRole)
        options = self._viewer.getOptions()

        if isinstance(data, dbTechLayer):
            options.setVisible(data, is_checked)
            self._viewer.fullRepaint()
        elif isinstance(data, str) and hasattr(options, data):
            setattr(options, data, is_checked)
            self.option_toggled.emit(data, is_checked)
            if data in ("_show_density_heatmap", "_show_flightlines", "_show_scale_bar"):
                self._viewer.update()
            else:
                self._viewer.fullRepaint()
        elif item == self._layers_group:
            # Toggle all layers
            for i in range(self._layers_group.childCount()):
                child = self._layers_group.child(i)
                child.setCheckState(0, item.checkState(0))

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.UserRole)
        options = self._viewer.getOptions()
        if isinstance(data, dbTechLayer):
            curr_color = options.color(data)
            new_color = QColorDialog.getColor(curr_color, self, f"Select Color for {data.getName()}")
            if new_color.isValid():
                new_color.setAlpha(180)
                options.setColor(data, new_color)
                item.setIcon(1, self._create_color_icon(new_color))
                self._viewer.fullRepaint()
        elif data == "_show_die_boundary":
            new_color = QColorDialog.getColor(options.dieColor(), self, "Select Die Boundary Color")
            if new_color.isValid():
                options.setDieColor(new_color)
                item.setIcon(1, self._create_color_icon(new_color))
                self._viewer.fullRepaint()
        elif data == "_show_polygon_boundary":
            new_color = QColorDialog.getColor(options.polygonColor(), self, "Select Polygon / Core Outline Color")
            if new_color.isValid():
                options.setPolygonColor(new_color)
                item.setIcon(1, self._create_color_icon(new_color))
                self._viewer.fullRepaint()
        elif data == "_show_io_pins":
            new_color = QColorDialog.getColor(options.ioPinColor(), self, "Select IO Pin Color")
            if new_color.isValid():
                options.setIoPinColor(new_color)
                item.setIcon(1, self._create_color_icon(new_color))
                self._viewer.fullRepaint()
        elif data == "_show_blockages":
            new_color = QColorDialog.getColor(
                options.placementBlockageColor(),
                self,
                "Select Placement Blockage Color",
                QColorDialog.ShowAlphaChannel,
            )
            if new_color.isValid():
                options.setPlacementBlockageColor(new_color)
                item.setIcon(1, self._create_color_icon(new_color))
                self._viewer.fullRepaint()

