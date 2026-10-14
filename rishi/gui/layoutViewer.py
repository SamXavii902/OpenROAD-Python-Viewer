"""LayoutViewer widget ported from RISHI gui/src/layoutViewer.cpp with interactive measurement ruler and object highlighting."""

import math
from typing import Optional, Dict, List, Tuple, Callable, Any
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPoint, QSize, QPointF, QLineF, QTimer
from PySide6.QtGui import (
    QPainter,
    QImage,
    QPaintEvent,
    QMouseEvent,
    QWheelEvent,
    QKeyEvent,
    QPolygonF,
    QPen,
    QColor,
    QFont,
    QLinearGradient,
)
import numpy as np
from rishi.odb.geom import Rect, Point
from rishi.odb.tech import dbTechLayer
from rishi.odb.lib import dbMaster
from rishi.odb.database import dbChip
from rishi.gui.options import DisplayOptions
from rishi.gui.search import SpatialSearch
from rishi.gui.renderThread import RenderThread


kZoomScaleFactor = 1.25


class LayoutViewer(QWidget):
    """Layout viewport widget matching RISHI gui::LayoutViewer with measurement ruler & highlights."""

    cursor_moved = Signal(float, float)  # Emits (x_microns, y_microns)
    ruler_measured = Signal(float, float, float)  # Emits (dist_um, dx_um, dy_um)
    ruler_mode_changed = Signal(bool)
    instance_selected = Signal(object)  # Emits selected dbInst or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._chip: Optional[dbChip] = None
        self._options = DisplayOptions()
        self._search = SpatialSearch()

        # Viewport transform parameters (mirrors RISHI layoutViewer.h)
        self.pixels_per_dbu: float = 1.0
        self.centering_shift = QPoint(0, 0)
        self._center = Point(0, 0)

        # Image cache rendered by RenderThread with its coordinate space
        self._pixmap: Optional[QImage] = None
        self._pixmap_bounds = QRect()
        self._pixmap_ppd: float = 0.0
        self._pixmap_centering = QPoint(0, 0)

        # Debounce timer for smooth real-time wheel zooming
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(120)
        self._zoom_timer.timeout.connect(self._on_zoom_settled)

        # Per-master shape cache: cell_boxes_[master][layer] (layoutViewer.cpp:1459-1559)
        self._cell_boxes: Dict[dbMaster, Dict[str, Dict[str, List[QPolygonF]]]] = {}

        # Pan state
        self._is_panning = False
        self._pan_start = QPoint()
        self._pan_offset = QPoint(0, 0)
        self._press_pos: Optional[QPoint] = None

        # Interactive Ruler / Caliper State
        self._ruler_mode: bool = False
        self._ruler_start: Optional[Point] = None
        self._ruler_current: Optional[Point] = None
        self._rulers: List[Tuple[Point, Point]] = []

        # Object Highlight & Multi-selection State
        self._highlight_items: List[Tuple[Rect, str]] = []
        self._selected_inst: Optional[object] = None
        self._flightlines: List[Tuple[Point, Point]] = []
        self._density_bins: Optional[List[Tuple[Rect, QColor]]] = None
        self._density_image: Optional[QImage] = None
        self._density_core: Optional[Rect] = None
        self._density_max_val: float = 0.85

        # Timing path debug overlay (Cadence Innovus/Tempus flightlines)
        self._active_timing_path: Optional[Any] = None
        self._timing_path_points: List[Point] = []
        self._multi_path_points: List[List[Point]] = []
        self._mbit_alias: Optional[Dict[str, Any]] = None

        # Background rendering thread (layoutViewer.cpp:125-259)
        self._render_thread = RenderThread(self)
        self._render_thread.done.connect(self._on_render_done)

    def closeEvent(self, event):
        self._render_thread.exit_thread()
        super().closeEvent(event)

    def __del__(self):
        try:
            if hasattr(self, "_render_thread") and self._render_thread is not None:
                self._render_thread.exit_thread()
        except (RuntimeError, Exception):
            pass

    def getChip(self) -> Optional[dbChip]:
        return self._chip

    def setChip(self, chip: Optional[dbChip], progress_callback: Optional[Callable[[str, int, int], None]] = None) -> None:
        self._chip = chip
        self._cell_boxes.clear()
        self._rulers.clear()
        self._ruler_start = None
        self._ruler_current = None
        self._highlight_items.clear()
        self._selected_inst = None
        self._flightlines.clear()
        self._mbit_alias = None
        self.clearTimingPaths()
        self._density_bins = None
        self._density_image = None
        self._density_core = None
        self._density_max_val = 0.85
        if chip and chip.getTech():
            self._options.tech_init(chip.getTech())
        if chip and chip.getBlock():
            self._search.build(chip.getBlock(), callback=progress_callback)
            self._get_mbit_alias()
            self.fit()
        else:
            self.update()

    def getOptions(self) -> DisplayOptions:
        return self._options

    def getSearch(self) -> SpatialSearch:
        return self._search

    def hasDesign(self) -> bool:
        return self._chip is not None and self._chip.getBlock() is not None

    def getBounds(self) -> Rect:
        if not self.hasDesign():
            return Rect(0, 0, 1000, 1000)
        return self._chip.getBlock().getDieArea()

    def getPaddedRect(self, rect: Rect, factor: float = 0.05) -> Rect:
        margin = int(factor * max(rect.dx(), rect.dy()))
        return Rect(rect.xMin() - margin, rect.yMin() - margin, rect.xMax() + margin, rect.yMax() + margin)

    # Ported from: gui/src/layoutViewer.cpp:291 computePixelsPerDBU
    def computePixelsPerDBU(self, size: QSize, dbu_rect: Rect) -> float:
        if dbu_rect.dx() <= 0 or dbu_rect.dy() <= 0:
            return 1.0
        return min(size.width() / float(dbu_rect.dx()), size.height() / float(dbu_rect.dy()))

    # Ported from: gui/src/layoutViewer.cpp:1711-1753 screenToDBU / dbuToScreen
    def screenToDBU(self, screen_rect: QRect) -> Rect:
        ppd = self.pixels_per_dbu
        if ppd <= 0:
            return Rect(0, 0, 0, 0)
        curr_shift = self.centering_shift + self._pan_offset
        dbu_left = int(math.floor((screen_rect.left() - curr_shift.x()) / ppd))
        dbu_right = int(math.ceil((screen_rect.right() - curr_shift.x()) / ppd))
        # Flip Y coordinate
        dbu_top = int(math.ceil((curr_shift.y() - screen_rect.top()) / ppd))
        dbu_bottom = int(math.floor((curr_shift.y() - screen_rect.bottom()) / ppd))
        return Rect(dbu_left, dbu_bottom, dbu_right, dbu_top)

    def screenPointToDBU(self, pt: QPoint) -> Point:
        ppd = self.pixels_per_dbu
        if ppd <= 0:
            return Point(0, 0)
        curr_shift = self.centering_shift + self._pan_offset
        x = int(round((pt.x() - curr_shift.x()) / ppd))
        y = int(round((curr_shift.y() - pt.y()) / ppd))
        return Point(x, y)

    def dbuPointToScreen(self, pt: Point) -> QPointF:
        ppd = self.pixels_per_dbu
        curr_shift = self.centering_shift + self._pan_offset
        x = curr_shift.x() + pt.x * ppd
        y = curr_shift.y() - pt.y * ppd
        return QPointF(x, y)

    # Level-of-Detail limits (gui/src/layoutViewer.cpp:2638-2651)
    def fineViewableResolution(self) -> int:
        return max(int(1.0 / self.pixels_per_dbu), 1)

    def nominalViewableResolution(self) -> int:
        return max(int(5.0 / self.pixels_per_dbu), 1)

    def coarseViewableResolution(self) -> int:
        return max(int(10.0 / self.pixels_per_dbu), 1)

    def instanceSizeLimit(self) -> int:
        if self._options.isDetailedVisibility():
            return 0
        return self.nominalViewableResolution()

    def shapeSizeLimit(self) -> int:
        if self._options.isDetailedVisibility():
            return self.fineViewableResolution()
        return self.nominalViewableResolution()

    # Ported from: gui/src/layoutViewer.cpp:2090 fit
    def fit(self) -> None:
        if not self.hasDesign():
            return
        bounds = self.getBounds()
        padded = self.getPaddedRect(bounds)

        w = max(self.width(), 100)
        h = max(self.height(), 100)
        self.pixels_per_dbu = self.computePixelsPerDBU(QSize(w, h), padded)

        # Center design in viewport
        cx = (w - bounds.dx() * self.pixels_per_dbu) / 2.0 - bounds.xMin() * self.pixels_per_dbu
        cy = (h + bounds.dy() * self.pixels_per_dbu) / 2.0 + bounds.yMin() * self.pixels_per_dbu
        self.centering_shift = QPoint(int(cx), int(cy))
        self._pan_offset = QPoint(0, 0)
        self._center = bounds.center()

        self.update()
        self.fullRepaint()

    # Ported from: gui/src/layoutViewer.cpp:430 zoom
    def zoom(self, focus_dbu: Point, factor: float, debounce: bool = False) -> None:
        if not self.hasDesign():
            return

        old_ppd = self.pixels_per_dbu
        new_ppd = old_ppd * factor

        # Clamp zoom limits
        if new_ppd < 1e-6 or new_ppd > 100.0:
            return

        # Keep focus_dbu at the same screen location
        screen_pt = self.dbuPointToScreen(focus_dbu)

        self.pixels_per_dbu = new_ppd
        new_shift_x = int(screen_pt.x() - focus_dbu.x * new_ppd)
        new_shift_y = int(screen_pt.y() + focus_dbu.y * new_ppd)
        self.centering_shift = QPoint(new_shift_x, new_shift_y)
        self._pan_offset = QPoint(0, 0)

        # Instant 60 FPS visual feedback via scaled pixmap blit
        self.update()

        if debounce:
            self._zoom_timer.start(120)
        else:
            self.fullRepaint()

    def _on_zoom_settled(self) -> None:
        self.fullRepaint()

    def zoomIn(self) -> None:
        self.zoom(self._center, kZoomScaleFactor, debounce=False)

    def zoomOut(self) -> None:
        self.zoom(self._center, 1.0 / kZoomScaleFactor, debounce=False)

    def zoomTo(self, rect: Rect) -> None:
        """Zooms and centers viewport on the specified DBU rectangle."""
        if not self.hasDesign() or rect.dx() <= 0 or rect.dy() <= 0:
            return
        padded = self.getPaddedRect(rect, factor=0.3)
        w = max(self.width(), 100)
        h = max(self.height(), 100)
        new_ppd = self.computePixelsPerDBU(QSize(w, h), padded)
        new_ppd = max(1e-6, min(100.0, new_ppd))
        self.pixels_per_dbu = new_ppd
        center = rect.center()
        cx = w / 2.0 - center.x * new_ppd
        cy = h / 2.0 + center.y * new_ppd
        self.centering_shift = QPoint(int(cx), int(cy))
        self._pan_offset = QPoint(0, 0)
        self.update()
        self.fullRepaint()

    def highlightObjects(self, items: List[Tuple[Rect, str]], zoom: bool = False) -> None:
        """Highlights multiple objects simultaneously with corner reticles."""
        self._highlight_items = list(items)
        if items and zoom:
            xmin = min(r.xMin() for r, _ in items)
            ymin = min(r.yMin() for r, _ in items)
            xmax = max(r.xMax() for r, _ in items)
            ymax = max(r.yMax() for r, _ in items)
            self.zoomTo(Rect(xmin, ymin, xmax, ymax))
        self.update()

    def highlightObject(self, rect: Optional[Rect], label: str = "", zoom: bool = False) -> None:
        """Highlights a specific object with a glowing target bracket reticle."""
        if rect is None:
            self.highlightObjects([], zoom=False)
        else:
            self.highlightObjects([(rect, label)], zoom=zoom)

    def highlightTimingPath(self, path: Optional[Any], zoom: bool = False) -> None:
        """Highlights a specific timing path with yellow directional flightlines and arrowheads."""
        if path is None:
            self._active_timing_path = None
            self._timing_path_points = []
            self.update()
            return

        pts = self._resolve_timing_path_points(path)
        self._active_timing_path = path
        self._timing_path_points = pts

        if pts and zoom:
            xmin = min(p.x for p in pts)
            ymin = min(p.y for p in pts)
            xmax = max(p.x for p in pts)
            ymax = max(p.y for p in pts)
            dx = max(xmax - xmin, 5000)
            dy = max(ymax - ymin, 5000)
            rect = Rect(
                xmin - int(dx * 0.15),
                ymin - int(dy * 0.15),
                xmax + int(dx * 0.15),
                ymax + int(dy * 0.15),
            )
            self.zoomTo(rect)

        self.update()

    def highlightTimingPaths(self, paths: List[Any]) -> None:
        """Highlights multiple timing paths simultaneously."""
        multi_pts = []
        for p in paths:
            pts = self._resolve_timing_path_points(p)
            if pts:
                multi_pts.append(pts)
        self._multi_path_points = multi_pts
        self.update()

    def clearTimingPaths(self) -> None:
        """Clears all timing path overlays."""
        self._active_timing_path = None
        self._timing_path_points = []
        self._multi_path_points = []
        self.update()

    def _get_mbit_alias(self) -> Dict[str, Any]:
        """Builds on-demand mapping from logical registers to physical multi-bit CDN_MBIT_ instances."""
        if getattr(self, "_mbit_alias", None) is not None:
            return self._mbit_alias
        self._mbit_alias = {}
        if not self.hasDesign():
            return self._mbit_alias
        block = self._chip.getBlock()
        inst_dict = getattr(block, "_insts_by_name", None)
        inst_items = inst_dict.items() if isinstance(inst_dict, dict) else [(inst.getName(), inst) for inst in block.getInsts()]
        for name, inst in inst_items:
            if "CDN_MBIT_" in name:
                if "/" in name:
                    parent, base = name.rsplit("/", 1)
                    prefix = f"{parent}/"
                else:
                    prefix = ""
                    base = name
                if "CDN_MBIT_" in base:
                    mbit_part = base.split("CDN_MBIT_", 1)[1]
                    for sub in mbit_part.split("_MB_"):
                        self._mbit_alias[f"{prefix}{sub}"] = inst
        return self._mbit_alias

    def _resolve_timing_path_points(self, path: Any) -> List[Point]:
        """Resolves ordered physical DBU points along the timing path with caching."""
        if not self.hasDesign():
            return []

        # Return cached points if already resolved
        if hasattr(path, "_cached_points") and path._cached_points is not None:
            return path._cached_points

        block = self._chip.getBlock()
        pts: List[Point] = []
        alias_map = self._get_mbit_alias()

        def get_loc(pin_name: str) -> Optional[Point]:
            if not pin_name:
                return None
            inst_name = pin_name.rsplit("/", 1)[0] if "/" in pin_name else pin_name
            inst = block.findInst(inst_name)
            if inst is None:
                inst = alias_map.get(inst_name)
            if inst and inst.isPlaced():
                return inst.getBBox().getBox().center()
            bterm = block.findBTerm(pin_name)
            if bterm:
                bbox = bterm.getBBox()
                if bbox and (bbox.dx() > 0 or bbox.dy() > 0):
                    return bbox.center()
            return None

        # Startpoint
        p_start = get_loc(getattr(path, "startpoint", ""))
        if p_start:
            pts.append(p_start)

        # Intermediate logic cells
        for cell_master, pin_name in getattr(path, "cells", []):
            pt = get_loc(pin_name)
            if pt and (not pts or (pt.x != pts[-1].x or pt.y != pts[-1].y)):
                pts.append(pt)

        # Endpoint
        p_end = get_loc(getattr(path, "endpoint", ""))
        if p_end and (not pts or (p_end.x != pts[-1].x or p_end.y != pts[-1].y)):
            pts.append(p_end)

        try:
            path._cached_points = pts
        except Exception:
            pass

        return pts

    def selectInstance(self, inst: Optional[object]) -> None:
        """Selects an instance in viewport, highlights it, and updates flightlines."""
        self._selected_inst = inst
        if inst is not None:
            box = inst.getBBox().getBox()
            self.highlightObject(box, inst.getName(), zoom=False)
        else:
            self.highlightObject(None)
        self._update_flightlines()
        self.instance_selected.emit(inst)
        self.update()

    def _update_flightlines(self) -> None:
        self._flightlines.clear()
        if self._selected_inst is None:
            return
        c1 = self._selected_inst.getBBox().getBox().center()
        max_lines = 400
        count = 0
        for iterm in self._selected_inst.getITerms():
            net = iterm.getNet()
            if net is None or net.isSpecial():
                continue
            iterms = net.getITerms()
            net_lines = 0
            for other_it in iterms:
                other_inst = other_it.getInst()
                if other_inst != self._selected_inst:
                    c2 = other_inst.getBBox().getBox().center()
                    self._flightlines.append((c1, c2))
                    count += 1
                    net_lines += 1
                    if count >= max_lines or net_lines >= 40:
                        break
            if count >= max_lines:
                break
            for bterm in net.getBTerms():
                found_pin = False
                for bpin in bterm.getBPins():
                    for layer, box in bpin.getBoxes():
                        self._flightlines.append((c1, box.center()))
                        count += 1
                        found_pin = True
                        if count >= max_lines:
                            break
                    if count >= max_lines:
                        break
                if not found_pin and self._chip and self._chip.getBlock():
                    die = self._chip.getBlock().getDieArea()
                    self._flightlines.append((c1, Point(die.xMin(), c1.y)))
                    count += 1
                if count >= max_lines:
                    break

    def _ensure_density_image(self) -> None:
        """Precomputes high-performance 2D placement density gradient image across placed instances."""
        if self._density_image is not None or not self.hasDesign():
            return
        block = self._chip.getBlock()
        die = block.getDieArea()
        if die.dx() <= 0 or die.dy() <= 0:
            die = block.getCoreArea()
        if die.dx() <= 0 or die.dy() <= 0:
            if hasattr(self._search, "_inst_boxes") and self._search._inst_boxes is not None and len(self._search._inst_boxes) > 0:
                boxes = self._search._inst_boxes
                die = Rect(int(np.min(boxes[:, 0])), int(np.min(boxes[:, 1])), int(np.max(boxes[:, 2])), int(np.max(boxes[:, 3])))
            else:
                return

        nx, ny = 120, 120
        bw = die.dx() / float(nx)
        bh = die.dy() / float(ny)
        bin_area = bw * bh
        if bin_area <= 0:
            return

        inv_bw = 1.0 / bw
        inv_bh = 1.0 / bh
        x0 = float(die.xMin())
        y0 = float(die.yMin())

        # Vectorized instance separation via spatial search
        if hasattr(self._search, "_inst_boxes") and self._search._inst_boxes is not None and len(self._search._inst_boxes) > 0:
            inst_boxes = self._search._inst_boxes
            is_macro = self._search._inst_is_macro
            std_boxes = inst_boxes[~is_macro]
            macro_boxes = inst_boxes[is_macro]
        else:
            all_insts = [inst for inst in block.getInsts() if inst.isPlaced()]
            if not all_insts:
                return
            boxes = []
            is_m_list = []
            for inst in all_insts:
                b = inst.getBBox().getBox()
                boxes.append([b.xMin(), b.yMin(), b.xMax(), b.yMax()])
                m = inst.getMaster()
                nl = m.getName().lower() if m else ""
                is_m = m and (m.isBlock() or m.isPad() or m.getWidth() > 15000 or m.getHeight() > 15000 or any(k in nl for k in ("ram", "sram", "rom", "fakeram", "pll", "fifo", "mem")))
                is_m_list.append(is_m)
            inst_boxes = np.array(boxes, dtype=np.int32)
            is_macro = np.array(is_m_list, dtype=bool)
            std_boxes = inst_boxes[~is_macro]
            macro_boxes = inst_boxes[is_macro]

        # 1. Standard cells: fast vectorized bincount by center coordinates
        std_grid = np.zeros((ny, nx), dtype=np.float64)
        if len(std_boxes) > 0:
            xc = (std_boxes[:, 0].astype(np.float64) + std_boxes[:, 2].astype(np.float64)) * 0.5
            yc = (std_boxes[:, 1].astype(np.float64) + std_boxes[:, 3].astype(np.float64)) * 0.5
            areas = (std_boxes[:, 2] - std_boxes[:, 0]).astype(np.float64) * (std_boxes[:, 3] - std_boxes[:, 1]).astype(np.float64)
            ix = np.clip(((xc - x0) * inv_bw).astype(np.int32), 0, nx - 1)
            iy = np.clip(((yc - y0) * inv_bh).astype(np.int32), 0, ny - 1)
            lin_idx = iy * nx + ix
            std_grid = np.bincount(lin_idx, weights=areas, minlength=nx * ny).reshape((ny, nx))

        # 2. Macros: distribute overlap area proportionally across all bins they intersect
        macro_grid = np.zeros((ny, nx), dtype=np.float64)
        if len(macro_boxes) > 0:
            for b in macro_boxes:
                ix1 = max(0, int((b[0] - x0) * inv_bw))
                ix2 = min(nx - 1, int((b[2] - x0) * inv_bw))
                iy1 = max(0, int((b[1] - y0) * inv_bh))
                iy2 = min(ny - 1, int((b[3] - y0) * inv_bh))
                for iy in range(iy1, iy2 + 1):
                    by1 = y0 + iy * bh
                    by2 = by1 + bh
                    over_y = max(0.0, min(float(b[3]), by2) - max(float(b[1]), by1))
                    for ix in range(ix1, ix2 + 1):
                        bx1 = x0 + ix * bw
                        bx2 = bx1 + bw
                        over_x = max(0.0, min(float(b[2]), bx2) - max(float(b[0]), bx1))
                        macro_grid[iy, ix] += over_x * over_y

        std_dens = std_grid / bin_area
        macro_dens = np.clip(macro_grid / bin_area, 0.0, 1.0)
        max_std_d = float(np.max(std_dens)) if std_dens.size > 0 else 0.0
        ref_max = max(max_std_d, 0.50)
        self._density_max_val = max_std_d

        img = QImage(nx, ny, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)

        for iy in range(ny):
            py = ny - 1 - iy  # Flip Y: chip +Y is up, QImage +Y is down
            for ix in range(nx):
                md = macro_dens[iy, ix]
                sd = std_dens[iy, ix]

                if md > 0.35:
                    # Macro blockage footprint tile
                    alpha = int(min(150.0, 60.0 + md * 90.0))
                    img.setPixelColor(ix, py, QColor(65, 75, 105, alpha))
                    continue

                if sd <= 0.03:
                    continue

                ratio = min(sd / ref_max, 1.0)
                if ratio < 0.25:
                    f = ratio / 0.25
                    r = int(15 * (1 - f) + 0 * f)
                    g = int(90 * (1 - f) + 220 * f)
                    b = int(230 * (1 - f) + 255 * f)
                    a = int(90 + 90 * f)
                elif ratio < 0.50:
                    f = (ratio - 0.25) / 0.25
                    r = int(0 * (1 - f) + 35 * f)
                    g = int(220 * (1 - f) + 235 * f)
                    b = int(255 * (1 - f) + 40 * f)
                    a = int(180 + 30 * f)
                elif ratio < 0.75:
                    f = (ratio - 0.50) / 0.25
                    r = int(35 * (1 - f) + 255 * f)
                    g = int(235 * (1 - f) + 195 * f)
                    b = int(40 * (1 - f) + 0 * f)
                    a = int(210 + 25 * f)
                else:
                    f = (ratio - 0.75) / 0.25
                    r = int(255 * (1 - f) + 240 * f)
                    g = int(195 * (1 - f) + 25 * f)
                    b = 0
                    a = 240
                img.setPixelColor(ix, py, QColor(r, g, b, a))

        self._density_image = img
        self._density_core = die

    def _hit_test_instance(self, pt_dbu: Point) -> Optional[object]:
        if self._chip is None or self._chip.getBlock() is None:
            return None
        block = self._chip.getBlock()
        tol_dbu = int(12 / max(self.pixels_per_dbu, 1e-4))
        candidates = self._search.searchInsts(
            block,
            pt_dbu.x - tol_dbu,
            pt_dbu.y - tol_dbu,
            pt_dbu.x + tol_dbu,
            pt_dbu.y + tol_dbu,
        )
        if not candidates:
            return None
        contained = [inst for inst in candidates if inst.getBBox().getBox().contains(pt_dbu)]
        if contained:
            return min(contained, key=lambda inst: inst.getBBox().getBox().dx() * inst.getBBox().getBox().dy())
        return min(candidates, key=lambda inst: inst.getBBox().getBox().dx() * inst.getBBox().getBox().dy())

    def toggleRulerMode(self) -> None:
        """Toggles measurement ruler mode (shortcut 'K')."""
        self.setRulerMode(not self._ruler_mode)

    def setRulerMode(self, active: bool) -> None:
        self._ruler_mode = active
        if active:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
            self._ruler_start = None
            self._ruler_current = None
        self.ruler_mode_changed.emit(active)
        self.update()

    def isRulerMode(self) -> bool:
        return self._ruler_mode

    def clearRulers(self) -> None:
        """Clears all persistent measurement rulers."""
        self._rulers.clear()
        self._ruler_start = None
        self._ruler_current = None
        self.update()

    def cancelRuler(self) -> None:
        """Cancels active ruler or exits ruler mode."""
        if self._ruler_start is not None:
            self._ruler_start = None
            self._ruler_current = None
            self.update()
        elif self._ruler_mode:
            self.setRulerMode(False)

    def fullRepaint(self) -> None:
        rect = self.rect()
        if not rect.isEmpty():
            self._render_thread.render(rect)

    def _on_render_done(
        self,
        image: QImage,
        rect: QRect,
        ppd: float = 0.0,
        centering: Optional[QPoint] = None,
    ) -> None:
        self._pixmap = image
        self._pixmap_bounds = rect
        self._pixmap_ppd = ppd if ppd > 0 else self.pixels_per_dbu
        self._pixmap_centering = centering if centering is not None else QPoint(self.centering_shift)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fullRepaint()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(20, 20, 20))
            if self._pixmap and not self._pixmap.isNull() and self._pixmap_ppd > 0:
                scale = self.pixels_per_dbu / self._pixmap_ppd
                curr_shift = self.centering_shift + self._pan_offset
                trans_x = curr_shift.x() - scale * self._pixmap_centering.x()
                trans_y = curr_shift.y() - scale * self._pixmap_centering.y()

                painter.save()
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.translate(trans_x, trans_y)
                painter.scale(scale, scale)
                painter.drawImage(self._pixmap_bounds.topLeft(), self._pixmap)
                painter.restore()

            # Placement Density Heatmap overlay
            if self._options.showDensityHeatmap():
                self._draw_density_heatmap(painter)

            # Ratsnest flightlines overlay
            self._draw_flightlines(painter)

            # Object Highlight overlay
            self._draw_highlight(painter)

            # Timing path flightlines overlay (Cadence Innovus/Tempus directional arrows)
            self._draw_timing_paths(painter)

            # Measurement Rulers overlay
            self._draw_rulers(painter)

            # Scale bar (gui/src/layoutViewer.cpp:1755)
            if self._options.isScaleBarVisible() and self.hasDesign():
                self._draw_scale_bar(painter)
        finally:
            painter.end()

    def _draw_flightlines(self, painter: QPainter) -> None:
        """Renders ratsnest flightlines connecting selected instance to its connected sinks."""
        if not self._flightlines or not self._options.showFlightlines():
            return
        painter.save()
        try:
            pen = QPen(QColor(255, 230, 0, 220), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            qline_list = []
            for p1, p2 in self._flightlines:
                sp1 = self.dbuPointToScreen(p1)
                sp2 = self.dbuPointToScreen(p2)
                qline_list.append(QLineF(sp1, sp2))
            painter.drawLines(qline_list)
        finally:
            painter.restore()

    def _draw_timing_paths(self, painter: QPainter) -> None:
        """Renders yellow directional timing path flightlines with arrows from startpoint to endpoint."""
        if not self._timing_path_points and not self._multi_path_points:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        try:
            # 1. Draw secondary highlighted paths
            pen_secondary = QPen(QColor(255, 230, 0, 150), 1.5, Qt.DashLine)
            pen_secondary.setCosmetic(True)
            painter.setPen(pen_secondary)

            for pts in self._multi_path_points:
                if len(pts) < 2:
                    continue
                for i in range(len(pts) - 1):
                    sp1 = self.dbuPointToScreen(pts[i])
                    sp2 = self.dbuPointToScreen(pts[i + 1])
                    painter.drawLine(sp1, sp2)

            # 2. Draw active timing path
            if len(self._timing_path_points) >= 2:
                pts = self._timing_path_points
                pen_active = QPen(QColor(255, 230, 0, 240), 2.5)
                pen_active.setCosmetic(True)
                painter.setPen(pen_active)

                for i in range(len(pts) - 1):
                    sp1 = self.dbuPointToScreen(pts[i])
                    sp2 = self.dbuPointToScreen(pts[i + 1])
                    painter.drawLine(sp1, sp2)

                    # Directional arrow in the middle of each segment
                    dx = sp2.x() - sp1.x()
                    dy = sp2.y() - sp1.y()
                    dist = math.hypot(dx, dy)
                    if dist > 14:
                        angle = math.atan2(dy, dx)
                        mid_x = (sp1.x() + sp2.x()) / 2.0
                        mid_y = (sp1.y() + sp2.y()) / 2.0
                        arrow_len = 8.0
                        arrow_angle = math.pi / 6.0

                        p_arrow1 = QPointF(
                            mid_x - arrow_len * math.cos(angle - arrow_angle),
                            mid_y - arrow_len * math.sin(angle - arrow_angle),
                        )
                        p_arrow2 = QPointF(
                            mid_x - arrow_len * math.cos(angle + arrow_angle),
                            mid_y - arrow_len * math.sin(angle + arrow_angle),
                        )
                        arrow_poly = QPolygonF([QPointF(mid_x, mid_y), p_arrow1, p_arrow2])
                        painter.setBrush(QColor(255, 230, 0, 240))
                        painter.drawPolygon(arrow_poly)

                # Intermediate gate markers
                painter.setBrush(QColor(255, 230, 0, 220))
                painter.setPen(QPen(QColor(20, 20, 20), 1))
                for pt in pts[1:-1]:
                    spt = self.dbuPointToScreen(pt)
                    painter.drawEllipse(spt, 3.5, 3.5)

                # Startpoint marker (Green badge)
                sp_start = self.dbuPointToScreen(pts[0])
                painter.setBrush(QColor(76, 175, 80))
                painter.setPen(QPen(Qt.white, 1.5))
                painter.drawEllipse(sp_start, 7, 7)
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(Qt.white)
                painter.drawText(QRectF(sp_start.x() - 7, sp_start.y() - 7, 14, 14), Qt.AlignCenter, "S")

                # Endpoint marker (Red badge)
                sp_end = self.dbuPointToScreen(pts[-1])
                painter.setBrush(QColor(229, 57, 53))
                painter.setPen(QPen(Qt.white, 1.5))
                painter.drawEllipse(sp_end, 7, 7)
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(Qt.white)
                painter.drawText(QRectF(sp_end.x() - 7, sp_end.y() - 7, 14, 14), Qt.AlignCenter, "E")

                # Floating Path HUD badge near startpoint
                if self._active_timing_path:
                    path = self._active_timing_path
                    slack_col = "#FF5252" if getattr(path, "slack", 0.0) < 0 else "#66BB6A"
                    hud_text = f"Path {getattr(path, 'id', 1)} | Slack: {getattr(path, 'slack', 0.0):+.4f} ns"
                    hud_font = QFont("Segoe UI", 8, QFont.Bold)
                    painter.setFont(hud_font)
                    fm = painter.fontMetrics()
                    hw = fm.horizontalAdvance(hud_text) + 24
                    hh = fm.height() + 8
                    hud_rect = QRectF(sp_start.x() + 12, sp_start.y() - hh / 2.0, hw, hh)

                    painter.setPen(QPen(QColor("#FFE600"), 1))
                    painter.setBrush(QColor(15, 20, 30, 230))
                    painter.drawRoundedRect(hud_rect, 4, 4)

                    painter.setFont(hud_font)
                    painter.setPen(QColor(slack_col))
                    painter.drawText(hud_rect, Qt.AlignCenter, hud_text)

            elif len(self._timing_path_points) == 1:
                sp_start = self.dbuPointToScreen(self._timing_path_points[0])
                painter.setBrush(QColor(76, 175, 80))
                painter.setPen(QPen(Qt.white, 1.5))
                painter.drawEllipse(sp_start, 7, 7)
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(Qt.white)
                painter.drawText(QRectF(sp_start.x() - 7, sp_start.y() - 7, 14, 14), Qt.AlignCenter, "S")

                if self._active_timing_path:
                    path = self._active_timing_path
                    slack_col = "#FF5252" if getattr(path, "slack", 0.0) < 0 else "#66BB6A"
                    hud_text = f"Path {getattr(path, 'id', 1)} | Slack: {getattr(path, 'slack', 0.0):+.4f} ns"
                    hud_font = QFont("Segoe UI", 8, QFont.Bold)
                    painter.setFont(hud_font)
                    fm = painter.fontMetrics()
                    hw = fm.horizontalAdvance(hud_text) + 24
                    hh = fm.height() + 8
                    hud_rect = QRectF(sp_start.x() + 12, sp_start.y() - hh / 2.0, hw, hh)

                    painter.setPen(QPen(QColor("#FFE600"), 1))
                    painter.setBrush(QColor(15, 20, 30, 230))
                    painter.drawRoundedRect(hud_rect, 4, 4)

                    painter.setFont(hud_font)
                    painter.setPen(QColor(slack_col))
                    painter.drawText(hud_rect, Qt.AlignCenter, hud_text)
        finally:
            painter.restore()

    def _draw_density_heatmap(self, painter: QPainter) -> None:
        """Renders placement density 2D heatmap color gradient across the core or die area."""
        if not self._options.showDensityHeatmap() or not self.hasDesign():
            return
        if self._density_image is None:
            self._ensure_density_image()
        if self._density_image is None or self._density_core is None:
            return

        painter.save()
        p1 = self.dbuPointToScreen(Point(self._density_core.xMin(), self._density_core.yMax()))
        p2 = self.dbuPointToScreen(Point(self._density_core.xMax(), self._density_core.yMin()))
        w = p2.x() - p1.x()
        h = p2.y() - p1.y()
        if w > 1 and h > 1:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(QRectF(p1.x(), p1.y(), w, h), self._density_image)

        self._draw_heatmap_hud_legend(painter)
        painter.restore()

    def _draw_heatmap_hud_legend(self, painter: QPainter) -> None:
        """Renders professional EDA density spectrum gradient bar and statistics HUD card."""
        card_w = 280
        card_h = 58
        margin_r = 20
        margin_t = 20
        x = self.width() - card_w - margin_r
        y = margin_t

        # Translucent dark HUD card background
        painter.setBrush(QColor(15, 20, 28, 235))
        painter.setPen(QPen(QColor(60, 72, 90), 1))
        painter.drawRoundedRect(QRectF(x, y, card_w, card_h), 6, 6)

        # Title & Stats
        title_font = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(230, 235, 245))
        peak_val = getattr(self, "_density_max_val", 0.85)
        peak_str = f"Peak: {peak_val * 100:.0f}%"
        painter.drawText(x + 10, y + 16, "Placement Density")

        stat_font = QFont("Segoe UI", 7, QFont.Normal)
        painter.setFont(stat_font)
        painter.setPen(QColor(160, 175, 195))
        painter.drawText(x + card_w - 75, y + 16, peak_str)

        # Continuous Turbo Gradient Bar
        bar_x = x + 10
        bar_y = y + 23
        bar_w = card_w - 20
        bar_h = 10

        grad = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
        grad.setColorAt(0.0, QColor(20, 90, 230))    # Low (Blue)
        grad.setColorAt(0.25, QColor(0, 220, 255))   # Light (Cyan)
        grad.setColorAt(0.50, QColor(35, 230, 60))   # Mid (Green)
        grad.setColorAt(0.75, QColor(255, 200, 0))   # High (Yellow)
        grad.setColorAt(1.0, QColor(240, 25, 25))    # Peak (Hotspot Red)

        painter.setPen(QPen(QColor(40, 50, 65), 1))
        painter.setBrush(grad)
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        # Tick Labels (0%, 25%, 50%, 75%, 100%)
        tick_font = QFont("Segoe UI", 7)
        painter.setFont(tick_font)
        painter.setPen(QColor(170, 180, 195))
        labels = [("0%", 0.0), ("25%", 0.25), ("50%", 0.50), ("75%", 0.75), ("100%", 1.0)]
        for lbl, frac in labels:
            lx = bar_x + frac * bar_w
            if frac == 1.0:
                lx -= 20
            elif frac > 0.0:
                lx -= 8
            painter.drawText(int(lx), bar_y + bar_h + 13, lbl)

    def _draw_scale_bar(self, painter: QPainter) -> None:
        dbu_per_um = self._chip.getTech().getDbuPerMicron() if self._chip and self._chip.getTech() else 1000
        ppd = self.pixels_per_dbu
        target_um = (100.0 / ppd) / dbu_per_um
        magnitude = 10 ** math.floor(math.log10(max(target_um, 1e-4)))
        mult = target_um / magnitude
        if mult < 1.5:
            bar_um = 1.0 * magnitude
        elif mult < 3.5:
            bar_um = 2.0 * magnitude
        elif mult < 7.5:
            bar_um = 5.0 * magnitude
        else:
            bar_um = 10.0 * magnitude

        bar_px = bar_um * dbu_per_um * ppd
        margin_x = 20
        margin_y = self.height() - 25

        painter.setPen(QPen(Qt.white, 2))
        painter.drawLine(margin_x, margin_y, int(margin_x + bar_px), margin_y)
        painter.drawLine(margin_x, margin_y - 4, margin_x, margin_y + 4)
        painter.drawLine(int(margin_x + bar_px), margin_y - 4, int(margin_x + bar_px), margin_y + 4)

        text = f"{bar_um:g} µm" if bar_um < 1000 else f"{bar_um/1000:g} mm"
        painter.drawText(margin_x + 5, margin_y - 6, text)

    def _draw_rulers(self, painter: QPainter) -> None:
        """Renders persistent and active measurement rulers on top of layout."""
        if not self._rulers and self._ruler_start is None:
            return

        dbu_per_um = self._chip.getTech().getDbuPerMicron() if self._chip and self._chip.getTech() else 1000
        ruler_col = self._options.rulerColor()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        pen = QPen(ruler_col, 2)
        pen.setCosmetic(True)
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)

        all_rulers: List[Tuple[Point, Point]] = list(self._rulers)
        if self._ruler_start and self._ruler_current:
            all_rulers.append((self._ruler_start, self._ruler_current))

        for p1_dbu, p2_dbu in all_rulers:
            sp1 = self.dbuPointToScreen(p1_dbu)
            sp2 = self.dbuPointToScreen(p2_dbu)

            # Main measurement line
            painter.setPen(pen)
            painter.drawLine(sp1, sp2)

            # Endpoint crosshairs
            t_size = 6
            painter.drawLine(QPointF(sp1.x() - t_size, sp1.y()), QPointF(sp1.x() + t_size, sp1.y()))
            painter.drawLine(QPointF(sp1.x(), sp1.y() - t_size), QPointF(sp1.x(), sp1.y() + t_size))
            painter.drawLine(QPointF(sp2.x() - t_size, sp2.y()), QPointF(sp2.x() + t_size, sp2.y()))
            painter.drawLine(QPointF(sp2.x(), sp2.y() - t_size), QPointF(sp2.x(), sp2.y() + t_size))

            # Caliper end-caps orthogonal to line
            dx = sp2.x() - sp1.x()
            dy = sp2.y() - sp1.y()
            length_px = math.hypot(dx, dy)
            if length_px > 2:
                ux = -dy / length_px * 7
                uy = dx / length_px * 7
                painter.drawLine(QPointF(sp1.x() - ux, sp1.y() - uy), QPointF(sp1.x() + ux, sp1.y() + uy))
                painter.drawLine(QPointF(sp2.x() - ux, sp2.y() - uy), QPointF(sp2.x() + ux, sp2.y() + uy))

            # Distances in microns
            dx_um = abs(p2_dbu.x - p1_dbu.x) / float(dbu_per_um)
            dy_um = abs(p2_dbu.y - p1_dbu.y) / float(dbu_per_um)
            dist_um = math.hypot(p2_dbu.x - p1_dbu.x, p2_dbu.y - p1_dbu.y) / float(dbu_per_um)

            label = f"L: {dist_um:,.3f} µm (dx: {dx_um:,.3f}, dy: {dy_um:,.3f})"
            mid_x = (sp1.x() + sp2.x()) / 2.0
            mid_y = (sp1.y() + sp2.y()) / 2.0

            # Badge pill
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label) + 14
            th = fm.height() + 6
            badge_rect = QRectF(mid_x - tw / 2.0, mid_y - th / 2.0 - 12, tw, th)

            painter.setPen(QPen(ruler_col, 1))
            painter.setBrush(QColor(15, 18, 24, 230))
            painter.drawRoundedRect(badge_rect, 4, 4)

            painter.setPen(QColor(255, 255, 255))
            painter.drawText(badge_rect, Qt.AlignCenter, label)

        painter.restore()

    def _draw_highlight(self, painter: QPainter) -> None:
        """Renders glowing corner target reticle and label around highlighted objects."""
        if not self._highlight_items:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)

        cyan = QColor("#00E5FF")
        p_bold = QPen(QColor("#FFE600"), 3)
        p_bold.setCosmetic(True)

        for rect, label in self._highlight_items:
            p_min = self.dbuPointToScreen(Point(rect.xMin(), rect.yMin()))
            p_max = self.dbuPointToScreen(Point(rect.xMax(), rect.yMax()))

            left = min(p_min.x(), p_max.x())
            top = min(p_min.y(), p_max.y())
            width = max(abs(p_max.x() - p_min.x()), 16.0)
            height = max(abs(p_max.y() - p_min.y()), 16.0)
            screen_box = QRectF(left, top, width, height)

            painter.setPen(QPen(cyan, 2))
            painter.setBrush(QColor(0, 229, 255, 30))
            painter.drawRect(screen_box)

            # Bold corner reticle brackets
            b_len = min(12.0, min(screen_box.width(), screen_box.height()) / 2.0)
            bx = screen_box.x()
            by = screen_box.y()
            bw = screen_box.width()
            bh = screen_box.height()

            painter.setPen(p_bold)
            painter.drawLine(QPointF(bx, by), QPointF(bx + b_len, by))
            painter.drawLine(QPointF(bx, by), QPointF(bx, by + b_len))
            painter.drawLine(QPointF(bx + bw, by), QPointF(bx + bw - b_len, by))
            painter.drawLine(QPointF(bx + bw, by), QPointF(bx + bw, by + b_len))
            painter.drawLine(QPointF(bx, by + bh), QPointF(bx + b_len, by + bh))
            painter.drawLine(QPointF(bx, by + bh), QPointF(bx, by + bh - b_len))
            painter.drawLine(QPointF(bx + bw, by + bh), QPointF(bx + bw - b_len, by + bh))
            painter.drawLine(QPointF(bx + bw, by + bh), QPointF(bx + bw, by + bh - b_len))

            # Floating label badge above target if reasonable count
            if label and len(self._highlight_items) <= 30:
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(label) + 14
                th = fm.height() + 6
                badge_rect = QRectF(bx + bw / 2.0 - tw / 2.0, by - th - 6, tw, th)

                painter.setPen(QPen(cyan, 1))
                painter.setBrush(QColor(15, 20, 30, 230))
                painter.drawRoundedRect(badge_rect, 4, 4)

                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(badge_rect, Qt.AlignCenter, label)

        painter.restore()

    # Master geometry caching (layoutViewer.cpp:1461-1559)
    def boxesByLayer(self, master: dbMaster, layer: dbTechLayer) -> Optional[Dict[str, List[QPolygonF]]]:
        if master not in self._cell_boxes:
            boxes_map: Dict[str, Dict[str, List[QPolygonF]]] = {}
            for box in master.getObstructions():
                l = box.getTechLayer()
                if l:
                    lname = l.getName().upper()
                    b = box.getBox()
                    poly = QPolygonF([QPointF(b.xMin(), b.yMin()), QPointF(b.xMax(), b.yMin()), QPointF(b.xMax(), b.yMax()), QPointF(b.xMin(), b.yMax())])
                    boxes_map.setdefault(lname, {}).setdefault("obs", []).append(poly)

            for mterm in master.getMTerms():
                for mpin in mterm.getMPins():
                    for box in mpin.getGeometry():
                        l = box.getTechLayer()
                        if l:
                            lname = l.getName().upper()
                            b = box.getBox()
                            poly = QPolygonF([QPointF(b.xMin(), b.yMin()), QPointF(b.xMax(), b.yMin()), QPointF(b.xMax(), b.yMax()), QPointF(b.xMin(), b.yMax())])
                            boxes_map.setdefault(lname, {}).setdefault("mterms", []).append(poly)
            self._cell_boxes[master] = boxes_map

        lname = layer.getName().upper()
        return self._cell_boxes[master].get(lname)

    # Mouse & Keyboard interaction
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_K:
            if event.modifiers() & Qt.ShiftModifier:
                self.clearRulers()
            else:
                self.toggleRulerMode()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            self.cancelRuler()
            event.accept()
        elif event.key() == Qt.Key_F:
            self.fit()
            event.accept()
        elif event.key() == Qt.Key_Z:
            if event.modifiers() & Qt.ShiftModifier:
                self.zoomOut()
            else:
                self.zoomIn()
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        mouse_pos = event.position().toPoint()
        focus_dbu = self.screenPointToDBU(mouse_pos)

        num_steps = delta / 120.0
        factor = kZoomScaleFactor ** num_steps
        self.zoom(focus_dbu, factor, debounce=True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._ruler_mode and event.button() == Qt.LeftButton:
            pt = self.screenPointToDBU(event.pos())
            if self._ruler_start is None:
                self._ruler_start = pt
                self._ruler_current = pt
                self.update()
            else:
                dbu_per_um = self._chip.getTech().getDbuPerMicron() if self._chip and self._chip.getTech() else 1000
                dx_um = abs(pt.x - self._ruler_start.x) / float(dbu_per_um)
                dy_um = abs(pt.y - self._ruler_start.y) / float(dbu_per_um)
                dist_um = math.hypot(pt.x - self._ruler_start.x, pt.y - self._ruler_start.y) / float(dbu_per_um)
                self._rulers.append((self._ruler_start, pt))
                self.ruler_measured.emit(dist_um, dx_um, dy_um)
                self._ruler_start = None
                self._ruler_current = None
                self.update()
            event.accept()
            return

        if self._ruler_mode and event.button() == Qt.RightButton:
            self.cancelRuler()
            event.accept()
            return

        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._press_pos = event.pos()
            self._is_panning = True
            self._pan_start = event.pos()
            self._pan_offset = QPoint(0, 0)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pt_dbu = self.screenPointToDBU(event.pos())
        dbu_per_um = self._chip.getTech().getDbuPerMicron() if self._chip and self._chip.getTech() else 1000
        x_um = pt_dbu.x / float(dbu_per_um)
        y_um = pt_dbu.y / float(dbu_per_um)
        self.cursor_moved.emit(x_um, y_um)

        if self._ruler_mode and self._ruler_start is not None:
            self._ruler_current = pt_dbu
            self.update()

        if self._is_panning:
            delta = event.pos() - self._pan_start
            self._pan_offset += delta
            self._pan_start = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not self._ruler_mode:
            if self._press_pos is not None and (event.pos() - self._press_pos).manhattanLength() < 5:
                self._is_panning = False
                cursor = Qt.ArrowCursor
                self.setCursor(cursor)
                self._pan_offset = QPoint(0, 0)
                pt_dbu = self.screenPointToDBU(event.pos())
                hit = self._hit_test_instance(pt_dbu)
                self.selectInstance(hit)
                event.accept()
                return

        if event.button() in (Qt.LeftButton, Qt.MiddleButton) and self._is_panning:
            self._is_panning = False
            cursor = Qt.CrossCursor if self._ruler_mode else Qt.ArrowCursor
            self.setCursor(cursor)
            self.centering_shift += self._pan_offset
            self._pan_offset = QPoint(0, 0)
            self.fullRepaint()
            event.accept()
