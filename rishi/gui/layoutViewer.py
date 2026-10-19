"""LayoutViewer widget ported from RISHI gui/src/layoutViewer.cpp with interactive measurement ruler and object highlighting."""

import math
import time
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
from rishi.irdrop.report import IR_DROP_PALETTE


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
        self._mbit_leaf_map: Optional[Dict[str, List[Any]]] = None
        self._leaf_map: Optional[Dict[str, List[Any]]] = None
        self._timing_report_data: Optional[Any] = None
        self._timing_connectivity: Dict[str, List[Point]] = {}
        self._ir_drop_data: Optional[Any] = None
        self._ir_drop_map_visible: bool = False
        self._ir_drop_heatmap_image: Optional[QImage] = None
        self._ir_drop_heatmap_core: Optional[Rect] = None
        self._ir_drop_grid_drop: Optional[np.ndarray] = None
        self._ir_drop_grid_inst: Optional[np.ndarray] = None
        self._ir_drop_nx: int = 120
        self._ir_drop_ny: int = 120
        self._ir_drop_x0: float = 0.0
        self._ir_drop_y0: float = 0.0
        self._ir_drop_bw: float = 0.0
        self._ir_drop_bh: float = 0.0

        # 60 FPS Vector Animation Overlay Engine
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60 FPS
        self._anim_timer.timeout.connect(self._on_anim_frame)
        self._anim_phase: float = 0.0

        # Kinetic Camera Glide State
        self._gliding: bool = False
        self._glide_start_time: float = 0.0
        self._glide_duration: float = 0.28  # 280ms
        self._glide_src_center = Point(0, 0)
        self._glide_dst_center = Point(0, 0)
        self._glide_src_ppd: float = 1.0
        self._glide_dst_ppd: float = 1.0

        # Sonar Radar Ripple State
        self._sonar_rings: List[Dict[str, Any]] = []

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
        self._pixmap = None
        self._search.clear()
        self._cell_boxes.clear()
        self._rulers.clear()
        self._ruler_start = None
        self._ruler_current = None
        self._highlight_items.clear()
        self._selected_inst = None
        self._flightlines.clear()
        self._mbit_alias = None
        self._mbit_leaf_map = None
        self._leaf_map = None
        self._timing_connectivity.clear()
        self._sonar_rings.clear()
        self._gliding = False
        if hasattr(self, "_anim_timer"):
            self._anim_timer.stop()
        self.clearTimingPaths()
        self._density_bins = None
        self._density_image = None
        self._density_core = None
        self._density_max_val = 0.85
        self._ir_drop_heatmap_image = None
        self._ir_drop_heatmap_core = None
        self._ir_drop_grid_drop = None
        if chip and chip.getTech():
            self._options.tech_init(chip.getTech())
        if chip and chip.getBlock():
            self._search.build(chip.getBlock(), callback=progress_callback)
            self._ensure_alias_maps()
            self.fit()
        else:
            self.centering_shift = QPoint(0, 0)
            self._pan_offset = QPoint(0, 0)
            self.pixels_per_dbu = 1.0
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

    def zoomTo(self, rect: Rect, animate: bool = False) -> None:
        """Zooms and centers viewport on the specified DBU rectangle with optional kinetic glide."""
        if not self.hasDesign() or rect.dx() <= 0 or rect.dy() <= 0:
            return
        padded = self.getPaddedRect(rect, factor=0.3)
        w = max(self.width(), 100)
        h = max(self.height(), 100)
        new_ppd = self.computePixelsPerDBU(QSize(w, h), padded)
        new_ppd = max(1e-6, min(100.0, new_ppd))
        target_center = rect.center()

        if not animate or not self.isVisible() or self.pixels_per_dbu <= 0:
            self.pixels_per_dbu = new_ppd
            self._center = target_center
            cx = w / 2.0 - target_center.x * new_ppd
            cy = h / 2.0 + target_center.y * new_ppd
            self.centering_shift = QPoint(int(cx), int(cy))
            self._pan_offset = QPoint(0, 0)
            self.update()
            self.fullRepaint()
            return

        # Start smooth 280ms kinetic camera glide
        self._glide_src_center = Point(self._center.x, self._center.y)
        self._glide_dst_center = target_center
        self._glide_src_ppd = self.pixels_per_dbu
        self._glide_dst_ppd = new_ppd
        self._glide_start_time = time.time()
        self._glide_duration = 0.28
        self._gliding = True
        self._check_start_anim()

    def highlightObjects(self, items: List[Any], zoom: bool = False) -> None:
        """Highlights multiple objects simultaneously with corner reticles."""
        self._highlight_items = list(items)
        if items and zoom:
            xmin = min(item[0].xMin() for item in items)
            ymin = min(item[0].yMin() for item in items)
            xmax = max(item[0].xMax() for item in items)
            ymax = max(item[0].yMax() for item in items)
            self.zoomTo(Rect(xmin, ymin, xmax, ymax), animate=self.isVisible())
        self.update()

    def highlightObject(
        self,
        rect: Optional[Rect],
        label: str = "",
        zoom: bool = False,
        color: Optional[QColor] = None,
    ) -> None:
        """Highlights a specific object with a glowing target bracket reticle."""
        if rect is None:
            self.highlightObjects([], zoom=False)
        else:
            item = (rect, label, color) if color is not None else (rect, label)
            self.highlightObjects([item], zoom=zoom)

    def pingLocation(self, pt: Point, color: QColor = QColor(0, 229, 255)) -> None:
        """Triggers an expanding radar sonar ripple at the specified DBU coordinate."""
        self._sonar_rings.append({
            "pt": pt,
            "start_time": time.time(),
            "duration": 0.45,
            "max_radius": 36.0,
            "color": color,
        })
        self._check_start_anim()

    def _check_start_anim(self) -> None:
        if not self._anim_timer.isActive():
            self._anim_timer.start(16)

    def _check_stop_anim(self) -> None:
        has_active_path = self._active_timing_path is not None and len(self._timing_path_points) >= 2
        if not self._gliding and not self._sonar_rings and not has_active_path:
            if self._anim_timer.isActive():
                self._anim_timer.stop()

    def _on_anim_frame(self) -> None:
        need_anim = False

        # 1. Kinetic camera glide
        if self._gliding:
            now = time.time()
            elapsed = now - self._glide_start_time
            t = min(max(elapsed / max(self._glide_duration, 0.05), 0.0), 1.0)
            ease = 1.0 - (1.0 - t) ** 3

            cur_x = int((1.0 - ease) * self._glide_src_center.x + ease * self._glide_dst_center.x)
            cur_y = int((1.0 - ease) * self._glide_src_center.y + ease * self._glide_dst_center.y)
            self._center = Point(cur_x, cur_y)
            self.pixels_per_dbu = (1.0 - ease) * self._glide_src_ppd + ease * self._glide_dst_ppd

            w = max(self.width(), 100)
            h = max(self.height(), 100)
            cx = w / 2.0 - self._center.x * self.pixels_per_dbu
            cy = h / 2.0 + self._center.y * self.pixels_per_dbu
            self.centering_shift = QPoint(int(cx), int(cy))
            self._pan_offset = QPoint(0, 0)

            if t >= 1.0:
                self._gliding = False
                self.fullRepaint()
            else:
                need_anim = True

        # 2. Sonar radar pings
        if self._sonar_rings:
            now = time.time()
            self._sonar_rings = [r for r in self._sonar_rings if now - r["start_time"] < r["duration"]]
            if self._sonar_rings:
                need_anim = True

        # 3. Active timing path traveling pulses
        if self._active_timing_path is not None and len(self._timing_path_points) >= 2:
            self._anim_phase = (self._anim_phase + 0.025) % 1.0
            need_anim = True

        if need_anim:
            self.update()
        else:
            self._anim_timer.stop()

    def highlightTimingPath(self, path: Optional[Any], zoom: bool = False) -> None:
        """Highlights a specific timing path with yellow directional flightlines, arrows, and flowing pulses."""
        if path is None:
            self._active_timing_path = None
            self._timing_path_points = []
            self._check_stop_anim()
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
            self.zoomTo(rect, animate=self.isVisible())
            self.pingLocation(pts[0], QColor(76, 175, 80))
            if len(pts) > 1:
                self.pingLocation(pts[-1], QColor(229, 57, 53))
        else:
            self._check_start_anim()

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
        """Clears all timing path overlays and stops vector pulse animation."""
        self._active_timing_path = None
        self._timing_path_points = []
        self._multi_path_points = []
        self._check_stop_anim()
        self.update()

    def _ensure_alias_maps(self) -> None:
        """Builds on-demand fast indexes for exact, multi-bit, and leaf-level instances."""
        if getattr(self, "_mbit_alias", None) is not None and getattr(self, "_mbit_leaf_map", None) is not None:
            return
        self._mbit_alias = {}
        self._mbit_leaf_map = {}
        self._leaf_map = {}
        if not self.hasDesign():
            return
        block = self._chip.getBlock()
        inst_dict = getattr(block, "_insts_by_name", None)
        inst_items = inst_dict.items() if isinstance(inst_dict, dict) else [(inst.getName(), inst) for inst in block.getInsts()]
        for name, inst in inst_items:
            # Leaf index
            leaf = name.rsplit("/", 1)[-1] if "/" in name else name
            self._leaf_map.setdefault(leaf, []).append(inst)

            # Multi-bit CDN_MBIT_ index
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
                        self._mbit_leaf_map.setdefault(sub, []).append(inst)

    def _get_mbit_alias(self) -> Dict[str, Any]:
        """Backward-compatible accessor for multi-bit mapping."""
        self._ensure_alias_maps()
        return self._mbit_alias or {}

    def setTimingReportData(self, report_data: Any) -> None:
        """Stores timing report data and builds fast instance connectivity map."""
        self._timing_report_data = report_data
        self._timing_connectivity = {}
        if report_data is None:
            return

        for p in getattr(report_data, "paths", []):
            pts = self._resolve_timing_path_points(p)
            if len(pts) >= 2:
                names: List[Tuple[str, Point]] = []
                if getattr(p, "startpoint", ""):
                    sp_inst = p.startpoint.rsplit("/", 1)[0] if "/" in p.startpoint else p.startpoint
                    names.append((sp_inst, pts[0]))
                for idx, (cell, pin) in enumerate(getattr(p, "cells", [])):
                    c_inst = pin.rsplit("/", 1)[0] if "/" in pin else pin
                    pt_idx = min(idx + 1, len(pts) - 1)
                    names.append((c_inst, pts[pt_idx]))
                if getattr(p, "endpoint", ""):
                    ep_inst = p.endpoint.rsplit("/", 1)[0] if "/" in p.endpoint else p.endpoint
                    names.append((ep_inst, pts[-1]))

                for i in range(len(names)):
                    inst_n, pt_curr = names[i]
                    leaf_n = inst_n.rsplit("/", 1)[-1]
                    if i > 0:
                        _, pt_prev = names[i - 1]
                        self._timing_connectivity.setdefault(inst_n, []).append(pt_prev)
                        self._timing_connectivity.setdefault(leaf_n, []).append(pt_prev)
                    if i < len(names) - 1:
                        _, pt_next = names[i + 1]
                        self._timing_connectivity.setdefault(inst_n, []).append(pt_next)
                        self._timing_connectivity.setdefault(leaf_n, []).append(pt_next)

    def setIRDropData(self, report_data: Optional[Any]) -> None:
        self._ir_drop_data = report_data
        self._ir_drop_heatmap_image = None
        self._ir_drop_heatmap_core = None
        self._ir_drop_grid_drop = None
        self._ir_drop_grid_inst = None
        self.fullRepaint()

    def setIRDropMapVisible(self, visible: bool) -> None:
        self._ir_drop_map_visible = bool(visible)
        self.fullRepaint()

    def isIRDropMapVisible(self) -> bool:
        return self._ir_drop_map_visible and self._ir_drop_data is not None

    def _resolve_timing_path_points(self, path: Any) -> List[Point]:
        """Resolves ordered physical DBU points along the timing path with 2-tier caching."""
        if not self.hasDesign():
            return []

        # Return cached points if already resolved
        if hasattr(path, "_cached_points") and path._cached_points is not None:
            return path._cached_points

        self._ensure_alias_maps()
        block = self._chip.getBlock()
        pts: List[Point] = []

        def get_loc(pin_name: str) -> Optional[Point]:
            if not pin_name:
                return None
            inst_name = pin_name.rsplit("/", 1)[0] if "/" in pin_name else pin_name

            # 1. Exact full-name match in block
            inst = block.findInst(inst_name)

            # 2. Exact prefix + mbit sub-register match
            if inst is None and self._mbit_alias:
                inst = self._mbit_alias.get(inst_name)

            # 3. Leaf multi-bit match with hierarchy disambiguation
            if inst is None and self._mbit_leaf_map:
                leaf = inst_name.rsplit("/", 1)[-1] if "/" in inst_name else inst_name
                candidates = self._mbit_leaf_map.get(leaf)
                if candidates:
                    inst = candidates[0]
                    if len(candidates) > 1 and "/" in inst_name:
                        parent = inst_name.rsplit("/", 1)[0]
                        for c in candidates:
                            if parent in c.getName():
                                inst = c
                                break

            # 4. Leaf placed cell fallback
            if inst is None and self._leaf_map:
                leaf = inst_name.rsplit("/", 1)[-1] if "/" in inst_name else inst_name
                candidates = self._leaf_map.get(leaf)
                if candidates:
                    inst = candidates[0]
                    if len(candidates) > 1 and "/" in inst_name:
                        parent = inst_name.rsplit("/", 1)[0]
                        for c in candidates:
                            if parent in c.getName():
                                inst = c
                                break

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

        # Guaranteed minimum fallback: connect start and end directly if intermediate gates unplaced
        if len(pts) < 2 and p_start and p_end and (p_start.x != p_end.x or p_start.y != p_end.y):
            pts = [p_start, p_end]

        if len(pts) >= 2:
            tech = getattr(self._chip, "getTech", lambda: getattr(block, "getTech", lambda: None)())()
            dbu_per_um = tech.getDbuPerMicron() if (tech and hasattr(tech, "getDbuPerMicron")) else 1000
            manhattan_dbu = sum(
                abs(pts[i + 1].x - pts[i].x) + abs(pts[i + 1].y - pts[i].y)
                for i in range(len(pts) - 1)
            )
            if not getattr(path, "_has_routed_wire_shapes", False):
                path.sum_wire_length = round(manhattan_dbu / float(dbu_per_um), 2)

        try:
            path._cached_points = pts
        except Exception:
            pass

        return pts

    def selectInstance(self, inst: Optional[object]) -> None:
        """Selects an instance in viewport, highlights it, triggers sonar ping, and updates flightlines."""
        self._selected_inst = inst
        if inst is not None:
            box = inst.getBBox().getBox()
            self.highlightObject(box, inst.getName(), zoom=False)
            self.pingLocation(box.center(), QColor(0, 229, 255))
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
        has_signal_nets = False

        for iterm in self._selected_inst.getITerms():
            net = iterm.getNet()
            if net is None or net.isSpecial():
                continue
            has_signal_nets = True
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

        # Fallback for unrouted placement designs with 0 signal nets (e.g. eth_design):
        if not has_signal_nets and self._timing_connectivity:
            inst_name = self._selected_inst.getName()
            leaf_name = inst_name.rsplit("/", 1)[-1]
            targets = self._timing_connectivity.get(inst_name) or self._timing_connectivity.get(leaf_name) or []
            seen = set()
            for pt in targets:
                k = (pt.x, pt.y)
                if k not in seen and (pt.x != c1.x or pt.y != c1.y):
                    seen.add(k)
                    self._flightlines.append((c1, pt))
                    count += 1
                    if count >= max_lines:
                        break

    def _ensure_density_image(self) -> None:
        """Precomputes high-performance 2D placement density gradient image matching OpenROAD RePlAce/GPL standards."""
        if self._density_image is not None or not self.hasDesign():
            return
        block = self._chip.getBlock()

        # 1. OpenROAD standard: Core Area / Placement rows reference
        core = block.getCoreArea()
        if core.dx() <= 0 or core.dy() <= 0:
            rows = block.getRows()
            if rows:
                rb = [r.getBBox() for r in rows]
                core = Rect(
                    min(b.xMin() for b in rb),
                    min(b.yMin() for b in rb),
                    max(b.xMax() for b in rb),
                    max(b.yMax() for b in rb),
                )
            else:
                core = block.getDieArea()
        if core.dx() <= 0 or core.dy() <= 0:
            if hasattr(self._search, "_inst_boxes") and self._search._inst_boxes is not None and len(self._search._inst_boxes) > 0:
                boxes = self._search._inst_boxes
                core = Rect(int(np.min(boxes[:, 0])), int(np.min(boxes[:, 1])), int(np.max(boxes[:, 2])), int(np.max(boxes[:, 3])))
            else:
                return

        nx, ny = 120, 120
        bw = core.dx() / float(nx)
        bh = core.dy() / float(ny)
        bin_area = bw * bh
        if bin_area <= 0:
            return

        inv_bw = 1.0 / bw
        inv_bh = 1.0 / bh
        x0 = float(core.xMin())
        y0 = float(core.yMin())

        # Vectorized instance separation via spatial search
        if hasattr(self._search, "_inst_boxes") and self._search._inst_boxes is not None and len(self._search._inst_boxes) > 0:
            inst_boxes = self._search._inst_boxes
            is_macro = self._search._inst_is_macro
            is_filler = getattr(self._search, "_inst_is_filler", None)
            if is_filler is not None and np.any(is_filler):
                # Isolate active logic cells from non-functional filler cells (OpenROAD placement density standard)
                std_boxes = inst_boxes[~is_macro & ~is_filler]
            else:
                std_boxes = inst_boxes[~is_macro]
            macro_boxes = inst_boxes[is_macro]
        else:
            all_insts = [inst for inst in block.getInsts() if inst.isPlaced()]
            if not all_insts:
                return
            boxes = []
            is_m_list = []
            is_f_list = []
            for inst in all_insts:
                b = inst.getBBox().getBox()
                boxes.append([b.xMin(), b.yMin(), b.xMax(), b.yMax()])
                m = inst.getMaster()
                is_m = m.isMacro() if m else False
                is_f = m.isFiller() if m else False
                is_m_list.append(is_m)
                is_f_list.append(is_f)
            inst_boxes = np.array(boxes, dtype=np.int32)
            is_macro = np.array(is_m_list, dtype=bool)
            is_filler = np.array(is_f_list, dtype=bool)
            if np.any(is_filler):
                std_boxes = inst_boxes[~is_macro & ~is_filler]
            else:
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

        macro_frac = np.clip(macro_grid / bin_area, 0.0, 1.0)
        placeable_area = np.maximum(bin_area - macro_grid, 0.0)

        # Standard cell density relative to placeable capacity
        with np.errstate(divide='ignore', invalid='ignore'):
            std_dens = np.where(placeable_area > 0.05 * bin_area, std_grid / placeable_area, 0.0)

        max_std_d = float(np.max(std_dens)) if std_dens.size > 0 else 0.0
        self._density_max_val = max_std_d
        self._density_bins = std_dens
        self._density_macro_bins = macro_frac
        self._density_nx = nx
        self._density_ny = ny
        self._density_bw = bw
        self._density_bh = bh
        self._density_x0 = x0
        self._density_y0 = y0

        img = QImage(nx, ny, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)

        for iy in range(ny):
            py = ny - 1 - iy  # Flip Y: chip +Y is up, QImage +Y is down
            for ix in range(nx):
                mf = macro_frac[iy, ix]
                sd = std_dens[iy, ix]

                if mf >= 0.75:
                    # Macro blockage footprint tile
                    alpha = int(min(160.0, 70.0 + mf * 80.0))
                    img.setPixelColor(ix, py, QColor(60, 72, 95, alpha))
                    continue

                if sd <= 0.02:
                    continue

                # OpenROAD standard absolute placement density color gradient:
                # 0.00 - 0.25 ( 0% - 25%): Deep Blue -> Bright Cyan (Sparse)
                # 0.25 - 0.50 (25% - 50%): Cyan -> Green (Moderate)
                # 0.50 - 0.75 (50% - 75%): Green -> Yellow (Target ASIC density ~60-70%)
                # 0.75 - 0.90 (75% - 90%): Yellow -> Orange (High Density)
                # 0.90 - 1.00 (90% - 100%): Orange -> Hotspot Red
                # > 1.00 (> 100%): Over-capacity Crimson / Pink
                if sd < 0.25:
                    f = sd / 0.25
                    r = int(15 * (1 - f) + 0 * f)
                    g = int(90 * (1 - f) + 220 * f)
                    b = int(230 * (1 - f) + 255 * f)
                    a = int(90 + 80 * f)
                elif sd < 0.50:
                    f = (sd - 0.25) / 0.25
                    r = int(0 * (1 - f) + 35 * f)
                    g = int(220 * (1 - f) + 235 * f)
                    b = int(255 * (1 - f) + 40 * f)
                    a = int(170 + 30 * f)
                elif sd < 0.75:
                    f = (sd - 0.50) / 0.25
                    r = int(35 * (1 - f) + 255 * f)
                    g = int(235 * (1 - f) + 200 * f)
                    b = int(40 * (1 - f) + 0 * f)
                    a = int(200 + 25 * f)
                elif sd <= 1.00:
                    f = (sd - 0.75) / 0.25
                    r = int(255 * (1 - f) + 240 * f)
                    g = int(200 * (1 - f) + 25 * f)
                    b = 0
                    a = int(225 + 25 * f)
                else:
                    r = 255
                    g = 20
                    b = 70
                    a = 250
                img.setPixelColor(ix, py, QColor(r, g, b, a))

        self._density_image = img
        self._density_core = core

    def getDensityAt(self, pt_dbu: Point) -> Optional[float]:
        """Returns the local placement density (0.0 to 1.0+) at the given DBU point, or None."""
        if not hasattr(self, "_density_bins") or self._density_bins is None:
            return None
        if not hasattr(self, "_density_core") or self._density_core is None:
            return None
        core = self._density_core
        if not core.contains(pt_dbu):
            return None
        ix = int((pt_dbu.x - self._density_x0) / self._density_bw)
        iy = int((pt_dbu.y - self._density_y0) / self._density_bh)
        if 0 <= ix < self._density_nx and 0 <= iy < self._density_ny:
            return float(self._density_bins[iy, ix])
        return None

    def _ensure_ir_drop_heatmap(self) -> None:
        """Precomputes 2D spatial voltage-drop thermal contour image matching EDA industry standards."""
        if self._ir_drop_heatmap_image is not None or not self.hasDesign() or self._ir_drop_data is None:
            return
        block = self._chip.getBlock()
        report = self._ir_drop_data
        records = getattr(report, "records_by_instance", None)
        if not records:
            return

        core = block.getCoreArea()
        if core.dx() <= 0 or core.dy() <= 0:
            rows = block.getRows()
            if rows:
                rb = [r.getBBox() for r in rows]
                core = Rect(
                    min(b.xMin() for b in rb),
                    min(b.yMin() for b in rb),
                    max(b.xMax() for b in rb),
                    max(b.yMax() for b in rb),
                )
            else:
                core = block.getDieArea()
        if core.dx() <= 0 or core.dy() <= 0:
            return

        nx, ny = 120, 120
        bw = core.dx() / float(nx)
        bh = core.dy() / float(ny)
        if bw <= 0 or bh <= 0:
            return

        inv_bw = 1.0 / bw
        inv_bh = 1.0 / bh
        x0 = float(core.xMin())
        y0 = float(core.yMin())

        grid_drop = np.zeros((ny, nx), dtype=np.float32)
        grid_count = np.zeros((ny, nx), dtype=np.int32)
        grid_inst = np.empty((ny, nx), dtype=object)

        self._ensure_alias_maps()

        # Map instances to spatial grid bins
        if hasattr(self._search, "_inst_boxes") and self._search._inst_boxes is not None and len(self._search._inst_boxes) > 0:
            boxes = self._search._inst_boxes
            insts = self._search._insts
            for i in range(len(insts)):
                inst = insts[i]
                name = inst.getName()
                rec = records.get(name)
                if rec is None and self._leaf_map:
                    leaf = name.rsplit("/", 1)[-1]
                    rec = records.get(leaf)
                if rec is None:
                    continue
                drop_mv = rec[0]
                cx = (boxes[i, 0] + boxes[i, 2]) * 0.5
                cy = (boxes[i, 1] + boxes[i, 3]) * 0.5
                ix = int((cx - x0) * inv_bw)
                iy = int((cy - y0) * inv_bh)
                if 0 <= ix < nx and 0 <= iy < ny:
                    if drop_mv > grid_drop[iy, ix]:
                        grid_drop[iy, ix] = drop_mv
                        grid_inst[iy, ix] = name
                    grid_count[iy, ix] += 1
        else:
            for inst in block.getInsts():
                if not inst.isPlaced():
                    continue
                name = inst.getName()
                rec = records.get(name)
                if rec is None and self._leaf_map:
                    leaf = name.rsplit("/", 1)[-1]
                    rec = records.get(leaf)
                if rec is None:
                    continue
                drop_mv = rec[0]
                c = inst.getBBox().getBox().center()
                ix = int((c.x - x0) * inv_bw)
                iy = int((c.y - y0) * inv_bh)
                if 0 <= ix < nx and 0 <= iy < ny:
                    if drop_mv > grid_drop[iy, ix]:
                        grid_drop[iy, ix] = drop_mv
                        grid_inst[iy, ix] = name
                    grid_count[iy, ix] += 1

        if not np.any(grid_count > 0):
            return

        # Continuous thermal smoothing using gaussian filter (or fallback box filter)
        try:
            from scipy.ndimage import gaussian_filter
            smoothed = gaussian_filter(grid_drop, sigma=1.2)
        except Exception:
            smoothed = grid_drop.copy()

        min_mv = float(report.minimum_mv)
        max_mv = float(report.maximum_mv)
        span_mv = max(max_mv - min_mv, 0.1)

        img = QImage(nx, ny, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)

        # 5 palette anchor stops
        palette_colors = [QColor(c) for c in IR_DROP_PALETTE]

        for iy in range(ny):
            py = ny - 1 - iy  # Flip layout Y to screen image Y
            for ix in range(nx):
                val = smoothed[iy, ix]
                if grid_count[iy, ix] == 0 and val < min_mv:
                    continue

                frac = min(max((val - min_mv) / span_mv, 0.0), 1.0)
                # Map frac across the 5 palette colors
                n_pal = len(palette_colors)
                scaled_f = frac * (n_pal - 1)
                idx0 = int(scaled_f)
                idx1 = min(idx0 + 1, n_pal - 1)
                t = scaled_f - idx0

                c0 = palette_colors[idx0]
                c1 = palette_colors[idx1]

                r = int(c0.red() * (1 - t) + c1.red() * t)
                g = int(c0.green() * (1 - t) + c1.green() * t)
                b = int(c0.blue() * (1 - t) + c1.blue() * t)
                a = int(140 + 85 * frac) if grid_count[iy, ix] > 0 else int(90 * frac)

                img.setPixelColor(ix, py, QColor(r, g, b, a))

        self._ir_drop_heatmap_image = img
        self._ir_drop_heatmap_core = core
        self._ir_drop_grid_drop = grid_drop
        self._ir_drop_grid_smoothed = smoothed
        self._ir_drop_grid_inst = grid_inst
        self._ir_drop_nx = nx
        self._ir_drop_ny = ny
        self._ir_drop_x0 = x0
        self._ir_drop_y0 = y0
        self._ir_drop_bw = bw
        self._ir_drop_bh = bh
        self._ir_drop_inv_bw = inv_bw
        self._ir_drop_inv_bh = inv_bh

    def _draw_ir_drop_heatmap(self, painter: QPainter) -> None:
        """Renders continuous 2D voltage-drop heatmap and HUD legend card."""
        if not self._ir_drop_map_visible or self._ir_drop_data is None or not self.hasDesign():
            return
        if self._ir_drop_heatmap_image is None:
            self._ensure_ir_drop_heatmap()
        if self._ir_drop_heatmap_image is None or self._ir_drop_heatmap_core is None:
            return

        painter.save()
        p1 = self.dbuPointToScreen(Point(self._ir_drop_heatmap_core.xMin(), self._ir_drop_heatmap_core.yMax()))
        p2 = self.dbuPointToScreen(Point(self._ir_drop_heatmap_core.xMax(), self._ir_drop_heatmap_core.yMin()))
        w = p2.x() - p1.x()
        h = p2.y() - p1.y()
        if w > 1 and h > 1:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(QRectF(p1.x(), p1.y(), w, h), self._ir_drop_heatmap_image)

        self._draw_ir_drop_hud_legend(painter)
        painter.restore()

    def _draw_ir_drop_hud_legend(self, painter: QPainter) -> None:
        """Renders sleek EDA IR-drop spectrum gradient bar and statistics HUD card."""
        if self._ir_drop_data is None:
            return
        report = self._ir_drop_data

        card_w = 280
        card_h = 60
        margin_r = 20
        margin_t = 20
        if self._options.showDensityHeatmap():
            margin_t += 68

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
        painter.drawText(x + 10, y + 16, "⚡ IR-Drop Heatmap")

        stat_font = QFont("Segoe UI", 7, QFont.Normal)
        painter.setFont(stat_font)
        painter.setPen(QColor(255, 110, 110))
        worst_str = f"Worst: {report.maximum_mv:.1f} mV"
        painter.drawText(x + card_w - 95, y + 16, worst_str)

        # Continuous IR-Drop Palette Gradient Bar
        bar_x = x + 10
        bar_y = y + 23
        bar_w = card_w - 20
        bar_h = 10

        grad = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
        grad.setColorAt(0.00, QColor("#39B7A5"))
        grad.setColorAt(0.25, QColor("#419BC4"))
        grad.setColorAt(0.50, QColor("#5E7DCE"))
        grad.setColorAt(0.75, QColor("#8B68C6"))
        grad.setColorAt(1.00, QColor("#D8588A"))

        painter.setPen(QPen(QColor(40, 50, 65), 1))
        painter.setBrush(grad)
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        # Tick Labels
        tick_font = QFont("Segoe UI", 7)
        painter.setFont(tick_font)
        painter.setPen(QColor(170, 180, 195))
        min_str = f"{report.minimum_mv:.1f}"
        p95_str = f"P95: {report.percentile_95_mv:.1f}"
        max_str = f"{report.maximum_mv:.1f} mV"
        painter.drawText(bar_x, bar_y + bar_h + 13, min_str)
        painter.drawText(bar_x + int(bar_w * 0.45) - 15, bar_y + bar_h + 13, p95_str)
        painter.drawText(bar_x + bar_w - 45, bar_y + bar_h + 13, max_str)

    def getIRDropAt(self, pt_dbu: Point) -> Optional[Tuple[float, str]]:
        """Returns the local IR drop in mV and instance name at the given DBU point, or None."""
        if self._ir_drop_data is None:
            return None
        if getattr(self, "_ir_drop_grid_drop", None) is None:
            self._ensure_ir_drop_heatmap()

        # First check if directly hitting a placed instance
        inst = self._hit_test_instance(pt_dbu)
        if inst is not None:
            rec = self._ir_drop_data.records_by_instance.get(inst.getName())
            if rec is None and self._leaf_map:
                leaf = inst.getName().rsplit("/", 1)[-1]
                rec = self._ir_drop_data.records_by_instance.get(leaf)
            if rec is not None:
                return (rec[0], inst.getName())

        # Fallback to spatial grid
        if (
            hasattr(self, "_ir_drop_grid_drop")
            and self._ir_drop_grid_drop is not None
            and self._ir_drop_heatmap_core is not None
        ):
            if self._ir_drop_heatmap_core.contains(pt_dbu):
                inv_bw = getattr(self, "_ir_drop_inv_bw", 1.0 / self._ir_drop_bw)
                inv_bh = getattr(self, "_ir_drop_inv_bh", 1.0 / self._ir_drop_bh)
                ix = int((pt_dbu.x - self._ir_drop_x0) * inv_bw)
                iy = int((pt_dbu.y - self._ir_drop_y0) * inv_bh)
                if 0 <= ix < self._ir_drop_nx and 0 <= iy < self._ir_drop_ny:
                    drop = float(self._ir_drop_grid_drop[iy, ix])
                    inst_n = self._ir_drop_grid_inst[iy, ix] or ""
                    if drop <= 0 and hasattr(self, "_ir_drop_grid_smoothed") and self._ir_drop_grid_smoothed is not None:
                        drop = float(self._ir_drop_grid_smoothed[iy, ix])
                    if drop > 0:
                        return (drop, inst_n)
        return None

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
            # Pad rendering bounds by 25% into RAM so panning has immediate visual coverage
            pad_w = int(rect.width() * 0.25)
            pad_h = int(rect.height() * 0.25)
            padded_rect = rect.adjusted(-pad_w, -pad_h, pad_w, pad_h)
            self._render_thread.render(padded_rect)

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

            # IR-Drop Heatmap overlay
            if self._ir_drop_map_visible and self._ir_drop_data is not None:
                self._draw_ir_drop_heatmap(painter)

            # Sonar radar ripples overlay
            if self._sonar_rings:
                self._draw_sonar_rings(painter)

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

    def _draw_sonar_rings(self, painter: QPainter) -> None:
        """Renders animated expanding sonar radar ripples around selected objects."""
        if not self._sonar_rings:
            return
        now = time.time()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            for ring in self._sonar_rings:
                elapsed = now - ring["start_time"]
                t = min(max(elapsed / ring["duration"], 0.0), 1.0)
                r = t * ring["max_radius"]
                alpha = int(220 * (1.0 - t))
                col = QColor(ring["color"])
                col.setAlpha(alpha)
                painter.setPen(QPen(col, 2.0))
                painter.setBrush(Qt.NoBrush)
                spt = self.dbuPointToScreen(ring["pt"])
                painter.drawEllipse(spt, r, r)
        finally:
            painter.restore()

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

                # 3. Traveling electric signal photons along segments
                for i in range(len(pts) - 1):
                    sp1 = self.dbuPointToScreen(pts[i])
                    sp2 = self.dbuPointToScreen(pts[i + 1])
                    seg_dx = sp2.x() - sp1.x()
                    seg_dy = sp2.y() - sp1.y()
                    seg_len = math.hypot(seg_dx, seg_dy)
                    if seg_len > 12:
                        frac = (self._anim_phase + (i * 0.35)) % 1.0
                        px = sp1.x() + seg_dx * frac
                        py = sp1.y() + seg_dy * frac

                        # Outer cyan halo
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QColor(0, 229, 255, 80))
                        painter.drawEllipse(QPointF(px, py), 6.0, 6.0)

                        # Core photon
                        painter.setBrush(QColor(0, 229, 255, 240))
                        painter.drawEllipse(QPointF(px, py), 3.0, 3.0)

                # Intermediate gate markers
                painter.setBrush(QColor(255, 230, 0, 220))
                painter.setPen(QPen(QColor(20, 20, 20), 1))
                for pt in pts[1:-1]:
                    spt = self.dbuPointToScreen(pt)
                    painter.drawEllipse(spt, 3.5, 3.5)

                # Startpoint marker (Green badge with subtle breathing halo)
                sp_start = self.dbuPointToScreen(pts[0])
                halo_pulse = 2.5 * math.sin(self._anim_phase * 6.28318)
                painter.setPen(QPen(QColor(76, 175, 80, 160), 1.5))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(sp_start, 7.0 + halo_pulse, 7.0 + halo_pulse)

                painter.setBrush(QColor(76, 175, 80))
                painter.setPen(QPen(Qt.white, 1.5))
                painter.drawEllipse(sp_start, 7, 7)
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(Qt.white)
                painter.drawText(QRectF(sp_start.x() - 7, sp_start.y() - 7, 14, 14), Qt.AlignCenter, "S")

                # Endpoint marker (Red badge with subtle breathing halo)
                sp_end = self.dbuPointToScreen(pts[-1])
                painter.setPen(QPen(QColor(229, 57, 53, 160), 1.5))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(sp_end, 7.0 + halo_pulse, 7.0 + halo_pulse)

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

        for item in self._highlight_items:
            rect = item[0]
            label = item[1] if len(item) > 1 else ""
            custom_color = item[2] if len(item) > 2 else None

            p_min = self.dbuPointToScreen(Point(rect.xMin(), rect.yMin()))
            p_max = self.dbuPointToScreen(Point(rect.xMax(), rect.yMax()))

            left = min(p_min.x(), p_max.x())
            top = min(p_min.y(), p_max.y())
            width = max(abs(p_max.x() - p_min.x()), 16.0)
            height = max(abs(p_max.y() - p_min.y()), 16.0)
            screen_box = QRectF(left, top, width, height)

            draw_col = custom_color if custom_color is not None else cyan
            fill_col = QColor(draw_col.red(), draw_col.green(), draw_col.blue(), 45)

            painter.setPen(QPen(draw_col, 2))
            painter.setBrush(fill_col)
            painter.drawRect(screen_box)

            # Bold corner reticle brackets
            b_len = min(12.0, min(screen_box.width(), screen_box.height()) / 2.0)
            bx = screen_box.x()
            by = screen_box.y()
            bw = screen_box.width()
            bh = screen_box.height()

            reticle_pen = QPen(draw_col.lighter(130), 3) if custom_color is not None else p_bold
            reticle_pen.setCosmetic(True)
            painter.setPen(reticle_pen)
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

                painter.setPen(QPen(draw_col, 1.5))
                painter.setBrush(QColor(15, 20, 30, 235))
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
