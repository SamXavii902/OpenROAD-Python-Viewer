"""Real-time Fuzzy Search and Quick-Jump Navigation Dock matching OpenROAD EDA GUI."""

import difflib
from typing import Optional, List, Dict, Tuple
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QFrame,
    QApplication,
    QAbstractItemView,
)
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtCore import Qt, Signal, QTimer
from openroad_py.odb.geom import Rect
from openroad_py.odb.block import dbBlock, dbInst, dbNet, dbBTerm
from openroad_py.odb.database import dbChip


class SearchResultItem:
    """Stores metadata for a searchable chip design object."""

    __slots__ = ("name", "category", "rect", "detail", "score")

    def __init__(self, name: str, category: str, rect: Rect, detail: str, score: float = 0.0):
        self.name: str = name
        self.category: str = category  # "MACRO", "INST", "NET", "PIN"
        self.rect: Rect = rect
        self.detail: str = detail
        self.score: float = score


class SearchDock(QDockWidget):
    """Dockable intelligent search panel with similarity search & instant viewport redirect."""

    object_selected = Signal(Rect, str)  # (target_rect, display_label)
    objects_selected = Signal(list)       # List[Tuple[Rect, str]] for multi-selection

    CATEGORY_COLORS = {
        "MACRO": "#D28CFF",  # Violet
        "INST": "#A0C0E0",   # Soft blue
        "NET": "#64B5F6",    # Cyan / blue
        "PIN": "#81C784",    # Green
    }

    def __init__(self, parent=None):
        super().__init__("Design Search & Quick-Jump", parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )

        self._chip: Optional[dbChip] = None
        self._cached_items: List[SearchResultItem] = []
        self._dbu_per_um: int = 1000
        self._last_clicked_item: Optional[QListWidgetItem] = None

        # Debounce timer for smooth typing on 300k+ designs
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._execute_search)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Search Controls Header
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)

        self._category_combo = QComboBox()
        self._category_combo.addItems(["All Objects", "Macros Only", "Std Cells Only", "Nets Only", "IO Pins Only"])
        self._category_combo.currentIndexChanged.connect(self._on_search_text_changed)
        filter_layout.addWidget(self._category_combo)

        layout.addLayout(filter_layout)

        # Search Input Field
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Type name, prefix, or similarity (e.g. sram, clk, _123_)...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            "QLineEdit { background-color: #1e1e24; color: #FFFFFF; border: 1px solid #3d3d48; "
            "border-radius: 4px; padding: 6px; font-size: 11px; } "
            "QLineEdit:focus { border: 1px solid #80CBC4; }"
        )
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(self._on_return_pressed)
        layout.addWidget(self._search_input)

        # Status Summary Label
        self._status_label = QLabel("No design loaded")
        self._status_label.setStyleSheet("color: #888899; font-size: 10px; padding: 0 2px;")
        layout.addWidget(self._status_label)

        # Results List
        self._results_list = QListWidget()
        self._results_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._results_list.setStyleSheet(
            "QListWidget { background-color: #18181c; border: 1px solid #2e2e38; border-radius: 4px; } "
            "QListWidget::item { padding: 4px; border-bottom: 1px solid #22222a; } "
            "QListWidget::item:hover { background-color: #262632; } "
            "QListWidget::item:selected { background-color: #2b3a4a; border-left: 3px solid #80CBC4; }"
        )
        self._results_list.itemClicked.connect(self._on_item_clicked)
        self._results_list.itemSelectionChanged.connect(self._on_selection_changed)
        self._results_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._results_list)

        self.setWidget(content)

    def setChip(self, chip: Optional[dbChip]) -> None:
        """Re-indexes searchable design entities upon loading a chip."""
        self._chip = chip
        self._cached_items.clear()
        self._results_list.clear()

        if chip is None or chip.getBlock() is None:
            self._status_label.setText("No design loaded")
            return

        block = chip.getBlock()
        tech = chip.getTech()
        self._dbu_per_um = tech.getDbuPerMicron() if tech else 1000

        # Indexing:
        # 1. Macros and Standard Cells
        insts = block.getInsts()
        for idx, inst in enumerate(insts):
            if idx > 0 and idx % 10000 == 0:
                QApplication.processEvents()
            master = inst.getMaster()
            mw = master.getWidth()
            mh = master.getHeight()
            name_lower = master.getName().lower()
            is_macro = (
                mw > 20000
                or mh > 20000
                or any(k in name_lower for k in ("ram", "sram", "fakeram", "cache", "pll"))
            )
            cat = "MACRO" if is_macro else "INST"
            bbox = inst.getBBox().getBox()
            x_um = bbox.xMin() / float(self._dbu_per_um)
            y_um = bbox.yMin() / float(self._dbu_per_um)
            w_um = bbox.dx() / float(self._dbu_per_um)
            h_um = bbox.dy() / float(self._dbu_per_um)
            detail = f"{master.getName()} | at ({x_um:,.1f}, {y_um:,.1f}) µm | {w_um:,.1f}x{h_um:,.1f} µm"
            self._cached_items.append(SearchResultItem(inst.getName(), cat, bbox, detail))

        # 2. Nets (compute wire bounding box)
        for idx, net in enumerate(block.getNets()):
            if idx > 0 and idx % 10000 == 0:
                QApplication.processEvents()
            shapes = net.getWireShapes() + net.getSpecialWireShapes()
            if shapes:
                x0 = min(s.box.xMin() for s in shapes)
                y0 = min(s.box.yMin() for s in shapes)
                x1 = max(s.box.xMax() for s in shapes)
                y1 = max(s.box.yMax() for s in shapes)
                net_box = Rect(x0, y0, x1, y1)
                detail = f"{len(shapes)} wire shapes | Net"
                self._cached_items.append(SearchResultItem(net.getName(), "NET", net_box, detail))

        # 3. IO Pins (BTerms)
        for bterm in block.getBTerms():
            bbox = bterm.getBBox()
            if bbox.dx() > 0 or bbox.dy() > 0:
                x_um = bbox.xMin() / float(self._dbu_per_um)
                y_um = bbox.yMin() / float(self._dbu_per_um)
                detail = f"IO Pin | at ({x_um:,.1f}, {y_um:,.1f}) µm"
                self._cached_items.append(SearchResultItem(bterm.getName(), "PIN", bbox, detail))

        macro_count = sum(1 for it in self._cached_items if it.category == "MACRO")
        inst_count = sum(1 for it in self._cached_items if it.category == "INST")
        net_count = sum(1 for it in self._cached_items if it.category == "NET")
        pin_count = sum(1 for it in self._cached_items if it.category == "PIN")
        self._status_label.setText(
            f"Indexed {len(self._cached_items):,} objects ({macro_count} macros, {inst_count:,} cells, {net_count:,} nets, {pin_count} pins)"
        )

    def _on_search_text_changed(self) -> None:
        self._search_timer.start()

    def _execute_search(self) -> None:
        query = self._search_input.text().strip().lower()
        self._results_list.clear()

        if not query:
            macro_count = sum(1 for it in self._cached_items if it.category == "MACRO")
            self._status_label.setText(
                f"Enter search query ({len(self._cached_items):,} objects indexed, {macro_count} macros)"
            )
            # Show all macros by default when input is blank
            macro_items = [it for it in self._cached_items if it.category == "MACRO"][:50]
            for it in macro_items:
                self._add_list_item(it)
            return

        cat_filter = self._category_combo.currentIndex()
        # 0: All, 1: Macros, 2: Insts, 3: Nets, 4: Pins
        cat_map = {1: "MACRO", 2: "INST", 3: "NET", 4: "PIN"}
        required_cat = cat_map.get(cat_filter)

        candidates = (
            [it for it in self._cached_items if it.category == required_cat]
            if required_cat
            else self._cached_items
        )

        matches: List[SearchResultItem] = []
        for it in candidates:
            name_lower = it.name.lower()
            if query == name_lower:
                it.score = 100.0
                matches.append(it)
            elif name_lower.startswith(query):
                it.score = 80.0 - (len(name_lower) - len(query)) * 0.1
                matches.append(it)
            elif query in name_lower:
                it.score = 60.0 - (len(name_lower) - len(query)) * 0.1
                matches.append(it)
            else:
                # Fast fuzzy similarity ratio
                ratio = difflib.SequenceMatcher(None, query, name_lower[: len(query) + 5]).ratio()
                if ratio >= 0.65:
                    it.score = 40.0 * ratio
                    matches.append(it)

        # Sort highest score first, then shorter names
        matches.sort(key=lambda x: (-x.score, len(x.name)))
        display_limit = 100
        shown_matches = matches[:display_limit]

        for it in shown_matches:
            self._add_list_item(it)

        self._status_label.setText(f"Found {len(matches):,} matches (showing top {len(shown_matches)})")

    def _add_list_item(self, item: SearchResultItem) -> None:
        list_item = QListWidgetItem()
        color = self.CATEGORY_COLORS.get(item.category, "#FFFFFF")

        # Visual item container
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(8)

        badge = QLabel(f"[{item.category}]")
        badge.setFont(QFont("Consolas", 8, QFont.Bold))
        badge.setStyleSheet(f"color: {color}; background-color: #24242c; padding: 2px 4px; border-radius: 3px;")
        row.addWidget(badge)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        name_lbl = QLabel(item.name)
        name_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        name_lbl.setStyleSheet("color: #FFFFFF;")
        text_layout.addWidget(name_lbl)

        detail_lbl = QLabel(item.detail)
        detail_lbl.setFont(QFont("Segoe UI", 8))
        detail_lbl.setStyleSheet("color: #9E9E9E;")
        text_layout.addWidget(detail_lbl)

        row.addLayout(text_layout)
        row.addStretch()

        list_item.setSizeHint(widget.sizeHint())
        list_item.setData(Qt.UserRole, item)
        self._results_list.addItem(list_item)
        self._results_list.setItemWidget(list_item, widget)

    def _on_item_clicked(self, list_item: QListWidgetItem) -> None:
        modifiers = QApplication.keyboardModifiers()
        has_multi = bool(modifiers & (Qt.ControlModifier | Qt.ShiftModifier))

        # If clicking an already selected single item without Ctrl or Shift, deselect to revert highlight
        if not has_multi and self._last_clicked_item == list_item:
            # Check if this item is currently selected
            if list_item.isSelected():
                list_item.setSelected(False)
                self._last_clicked_item = None
                self._emit_selection()
                return

        self._last_clicked_item = list_item
        self._emit_selection()

    def _on_selection_changed(self) -> None:
        self._emit_selection()

    def get_selected_items(self) -> List[Tuple[Rect, str]]:
        """Returns the list of (Rect, label) tuples for currently selected search items."""
        selected = self._results_list.selectedItems()
        items: List[Tuple[Rect, str]] = []
        for it in selected:
            item_data: Optional[SearchResultItem] = it.data(Qt.UserRole)
            if item_data and item_data.rect:
                items.append((item_data.rect, f"[{item_data.category}] {item_data.name}"))
        return items

    def _emit_selection(self) -> None:
        selected = self._results_list.selectedItems()
        items: List[Tuple[Rect, str]] = []
        for it in selected:
            item_data: Optional[SearchResultItem] = it.data(Qt.UserRole)
            if item_data and item_data.rect:
                items.append((item_data.rect, f"[{item_data.category}] {item_data.name}"))

        self.objects_selected.emit(items)
        if len(items) == 1:
            self.object_selected.emit(items[0][0], items[0][1])

    def _on_item_double_clicked(self, list_item: QListWidgetItem) -> None:
        self._on_item_clicked(list_item)

    def _on_return_pressed(self) -> None:
        if self._results_list.count() > 0:
            first_item = self._results_list.item(0)
            self._results_list.setCurrentItem(first_item)
            self._on_item_clicked(first_item)
