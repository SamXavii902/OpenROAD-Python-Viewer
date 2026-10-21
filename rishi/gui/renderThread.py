"""RenderThread ported from RISHI gui/src/renderThread.cpp."""

from typing import TYPE_CHECKING, List, Dict, Tuple, Optional, Any
from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition, QRect, QRectF, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QImage,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QTransform,
    QFont,
    QFontMetrics,
    QPolygonF,
)
from bisect import bisect_left, bisect_right
import numpy as np
from rishi.odb.geom import Rect, Point
from rishi.odb.types import (
    dbOrientType,
    dbTechLayerType,
    dbTechLayerDir,
    dbIoType,
)
from rishi.odb.transform import dbTransform
from rishi.odb.tech import dbTech, dbTechLayer
from rishi.odb.lib import dbMaster
from rishi.odb.block import dbBlock, dbInst, dbRow
from rishi.gui.options import DisplayOptions
from rishi.gui.painter import GuiPainter
from rishi.irdrop.report import IR_DROP_PALETTE

if TYPE_CHECKING:
    from rishi.gui.layoutViewer import LayoutViewer


class RenderThread(QThread):
    """Background rendering thread drawing layout onto QImage matching RISHI RenderThread."""

    done = Signal(QImage, QRect, float, QPoint)

    def __init__(self, viewer: "LayoutViewer"):
        super().__init__()
        self._viewer = viewer
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._abort = False
        self._restart = False
        self._draw_rect = QRect()
        self._draw_ppd = 1.0
        self._draw_centering = QPoint(0, 0)
        self._is_rendering = False

    def stop_render(self) -> None:
        """Cancels any pending or active background render pass."""
        try:
            self._mutex.lock()
            self._draw_rect = QRect()
            self._restart = True
            self._condition.wakeOne()
            self._mutex.unlock()
        except (RuntimeError, Exception):
            pass

    def exit_thread(self) -> None:
        try:
            if not self.isRunning():
                return
            self._mutex.lock()
            self._abort = True
            self._restart = True
            self._condition.wakeOne()
            self._mutex.unlock()
            self.wait(2000)
        except (RuntimeError, Exception):
            pass

    def __del__(self) -> None:
        try:
            self.exit_thread()
        except (RuntimeError, Exception):
            pass

    def render(self, draw_rect: QRect) -> None:
        if self._abort:
            return

        self._mutex.lock()
        self._draw_rect = draw_rect
        self._draw_ppd = self._viewer.pixels_per_dbu
        self._draw_centering = QPoint(self._viewer.centering_shift)
        if not self.isRunning():
            self._mutex.unlock()
            self.start(QThread.LowPriority)
        else:
            self._restart = True
            self._condition.wakeOne()
            self._mutex.unlock()

    def run(self) -> None:
        while True:
            self._mutex.lock()
            draw_bounds = self._draw_rect
            draw_ppd = self._draw_ppd
            draw_centering = self._draw_centering
            self._mutex.unlock()

            if draw_bounds.isEmpty() or draw_bounds.width() <= 0 or draw_bounds.height() <= 0:
                self._mutex.lock()
                if not self._restart:
                    self._condition.wait(self._mutex)
                self._restart = False
                self._mutex.unlock()
                continue

            image = QImage(
                draw_bounds.width(),
                draw_bounds.height(),
                QImage.Format_ARGB32_Premultiplied,
            )

            try:
                self.draw(image, draw_bounds, draw_ppd, draw_centering)
            except Exception as e:
                pass

            if not self._restart and not self._abort:
                self.done.emit(image, draw_bounds, draw_ppd, draw_centering)

            if self._abort:
                return

            self._mutex.lock()
            if not self._restart:
                self._condition.wait(self._mutex)
            self._restart = False
            self._mutex.unlock()

    # Ported from: gui/src/renderThread.cpp:200 draw
    def draw(
        self,
        image: QImage,
        draw_bounds: QRect,
        ppd: Optional[float] = None,
        centering: Optional[QPoint] = None,
    ) -> None:
        if image.isNull():
            return

        self._restart = False

        chip = self._viewer.getChip()
        if chip is None:
            image.fill(QColor(24, 24, 24))
            return

        block = chip.getBlock()
        if block is None:
            image.fill(QColor(24, 24, 24))
            return

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, False)

        # RISHI background: dark theme
        bg_color = QColor(20, 20, 20)
        image.fill(bg_color)

        if ppd is None:
            ppd = self._viewer.pixels_per_dbu
        if centering is None:
            centering = self._viewer.centering_shift

        # Setup coordinate mapping DBU -> Pixels (L222-225)
        painter.translate(-draw_bounds.topLeft())
        painter.translate(centering)
        painter.scale(ppd, -ppd)  # Flip Y so design +Y is up

        dbu_bounds = self._viewer.screenToDBU(draw_bounds)
        options = self._viewer.getOptions()
        gui_painter = GuiPainter(
            painter,
            options,
            dbu_bounds,
            ppd,
            chip.getTech().getDbuPerMicron() if chip.getTech() else 1000,
        )

        self.drawChip(painter, block, dbu_bounds, gui_painter)
        painter.end()

    # Ported from: gui/src/renderThread.cpp:1164 drawChip
    def drawChip(
        self,
        painter: QPainter,
        block: dbBlock,
        bounds: Rect,
        gui_painter: GuiPainter,
    ) -> None:
        options = self._viewer.getOptions()
        search = self._viewer.getSearch()

        # 1. Die Area & Polygon / Core Area outlines (L1174-1200)
        self.drawBoundaries(painter, block)

        if self._restart:
            return

        # 2. Query visible instances (L1210-1230)
        ir_drop_active = bool(
            getattr(self._viewer, "_ir_drop_map_visible", False)
            and getattr(self._viewer, "_ir_drop_data", None) is not None
        )
        # Preserve normal instanceSizeLimit() so zoomed-out views never flood drawLayer/drawInstanceShapes
        # with hundreds of thousands of sub-5px standard cells. Progressive LOD is rendered in drawIRDropOverlay.
        inst_limit = self._viewer.instanceSizeLimit()

        insts = search.searchInsts(
            block,
            bounds.xMin(),
            bounds.yMin(),
            bounds.xMax(),
            bounds.yMax(),
            inst_limit,
            show_std_cells=options.areStandardCellsVisible() or ir_drop_active,
            show_macros=options.areMacrosVisible(),
        )

        # 3. Draw instance outlines (L1237)
        if (options.areInstancesVisible() and options.areInstanceOutlinesVisible()) or ir_drop_active:
            self.drawInstanceOutlines(painter, insts)

        if self._restart:
            return

        # 4. Draw placement blockages (L1242)
        if options.areBlockagesVisible():
            self.drawBlockages(painter, block, bounds, insts)

        if self._restart:
            return

        # 5. Draw layers bottom-up (L1245-1270)
        tech = block.getTech()
        if tech is not None:
            for layer in tech.getLayers():
                if self._restart:
                    return
                self.drawLayer(painter, block, layer, insts, bounds, gui_painter)

        if self._restart:
            return

        # 6. Draw rows & sites (L1280)
        if options.areRowsVisible():
            self.drawRows(painter, block, bounds)

        if ir_drop_active:
            self.drawIRDropOverlay(painter, insts, bounds)

        if self._restart:
            return

        # 7. Re-draw Die & Polygon outlines on top of blockages/macros so boundaries remain unbroken
        self.drawBoundaries(painter, block)

        # 8. Draw instance names (L1273)
        if options.areInstanceNamesVisible():
            self.drawInstanceNames(painter, insts)

        # 9. Draw IO pins (L1233)
        if options.areIOPinsVisible():
            self.drawIOPins(painter, block, bounds)

    def _get_selected_hbin_info(self, report: Any) -> Tuple[Optional[int], Optional[Any]]:
        selected_bin = getattr(self._viewer, "_ir_drop_selected_bin", None)
        selected_hbin = getattr(self._viewer, "_ir_drop_selected_hbin_idx", None)
        if selected_bin is not None and selected_hbin is None and report is not None:
            bins = getattr(report, "bins", None)
            if bins:
                try:
                    selected_hbin = bins.index(selected_bin)
                except ValueError:
                    for idx, b in enumerate(bins):
                        if (
                            abs(b.minimum_mv - selected_bin.minimum_mv) < 1e-6
                            and abs(b.maximum_mv - selected_bin.maximum_mv) < 1e-6
                        ):
                            selected_hbin = idx
                            break
            if selected_hbin is None and hasattr(selected_bin, "bin_index"):
                selected_hbin = int(selected_bin.bin_index)
        return selected_hbin, selected_bin

    def drawIRDropOverlay(self, painter: QPainter, insts: List[dbInst], bounds: Optional[Rect] = None) -> None:
        """Draws IR-drop range colors over standard cells with progressive multi-resolution LOD."""
        ppd = getattr(self._viewer, "pixels_per_dbu", 1.0)
        if ppd <= 0:
            return
        report = getattr(self._viewer, "_ir_drop_data", None)
        if report is None:
            return

        ensure_fn = getattr(self._viewer, "_ensure_ir_drop_color_cache", None)
        if ensure_fn is not None:
            ensure_fn()

        selected_hbin, selected_bin = self._get_selected_hbin_info(report)

        resolve_both_fn = getattr(self._viewer, "resolve_ir_drop_bin_and_hbin", None)
        resolve_fn = getattr(self._viewer, "resolve_ir_drop_bin", None)
        name_to_bin = getattr(self._viewer, "_ir_drop_name_to_bin", None)
        name_to_hbin = getattr(self._viewer, "_ir_drop_name_to_hbin", None)
        records = getattr(report, "records_by_instance", {})
        if name_to_bin is None and resolve_fn is None and resolve_both_fn is None:
            name_to_bin = {k: report.color_index(v[0]) for k, v in records.items()}
        if name_to_hbin is None and resolve_both_fn is None and hasattr(report, "histogram_bin_index"):
            name_to_hbin = {k: report.histogram_bin_index(v[0]) for k, v in records.items()}
        leaf_to_bin = getattr(self._viewer, "_ir_drop_leaf_to_bin", {})
        leaf_to_hbin = getattr(self._viewer, "_ir_drop_leaf_to_hbin", {})

        def _fallback_resolve_both(name: str) -> Tuple[int, int]:
            if resolve_both_fn is not None:
                return resolve_both_fn(name)
            if resolve_fn is not None:
                b_res = resolve_fn(name)
            else:
                b_val = name_to_bin.get(name) if name_to_bin else None
                if b_val is None and leaf_to_bin:
                    leaf = name.rsplit("/", 1)[-1] if "/" in name else name
                    b_val = leaf_to_bin.get(leaf)
                b_res = b_val if b_val is not None else -1
            if b_res < 0:
                return -1, -1
            hb_val = name_to_hbin.get(name) if name_to_hbin else None
            if hb_val is None and leaf_to_hbin:
                leaf = name.rsplit("/", 1)[-1] if "/" in name else name
                hb_val = leaf_to_hbin.get(leaf)
            if hb_val is None and hasattr(report, "histogram_bin_index"):
                rec = records.get(name)
                if rec is not None:
                    hb_val = report.histogram_bin_index(rec[0])
            return b_res, (hb_val if hb_val is not None else -1)

        brushes = []
        pens = []
        for color_hex in IR_DROP_PALETTE:
            color = QColor(color_hex)
            pen = QPen(color.lighter(125), 0)
            pen.setCosmetic(True)
            pens.append(pen)
            color.setAlpha(195)
            brushes.append(QBrush(color))

        # Fast Vectorized Progressive LOD path using SpatialSearch NumPy arrays
        search = self._viewer.getSearch() if hasattr(self._viewer, "getSearch") else None
        boxes = getattr(search, "_inst_boxes", None) if search is not None else None
        if bounds is not None and boxes is not None and len(boxes) > 0:
            mask = (
                (boxes[:, 2] >= bounds.xMin())
                & (boxes[:, 0] <= bounds.xMax())
                & (boxes[:, 3] >= bounds.yMin())
                & (boxes[:, 1] <= bounds.yMax())
                & (~search._inst_is_macro)
            )
            vis_indices = np.flatnonzero(mask)
            num_vis = len(vis_indices)
            if num_vis == 0:
                return

            LOD_BUDGET = 8000
            stride = max(1, (num_vis + LOD_BUDGET - 1) // LOD_BUDGET)

            all_insts = search._insts
            inst_bins = getattr(self._viewer, "_ir_drop_inst_bins", None)
            inst_hbins = getattr(self._viewer, "_ir_drop_inst_hbins", None)
            if (
                inst_bins is None
                or len(inst_bins) != len(all_insts)
                or inst_hbins is None
                or len(inst_hbins) != len(all_insts)
            ):
                inst_bins = np.full(len(all_insts), -2, dtype=np.int8)
                inst_hbins = np.full(len(all_insts), -2, dtype=np.int8)
                self._viewer._ir_drop_inst_bins = inst_bins
                self._viewer._ir_drop_inst_hbins = inst_hbins

            bins_to_draw: Tuple[List[int], ...] = ([], [], [], [], [])
            total_matched = 0
            resolve_pair = resolve_both_fn if resolve_both_fn is not None else _fallback_resolve_both

            if selected_hbin is not None:
                # Fast path if all visible instances have already been resolved: pure C/NumPy vector mask
                if not np.any(inst_bins[vis_indices] == -2):
                    matched_vis = vis_indices[inst_hbins[vis_indices] == selected_hbin]
                    bin_stride = max(1, (len(matched_vis) + LOD_BUDGET - 1) // LOD_BUDGET)
                    if bin_stride > 1:
                        matched_vis = matched_vis[::bin_stride]
                    for raw_idx in matched_vis:
                        i = int(raw_idx)
                        b = int(inst_bins[i])
                        if 0 <= b < 5:
                            bins_to_draw[b].append(i)
                            total_matched += 1
                else:
                    expected_count = getattr(selected_bin, "count", 0) if selected_bin is not None else 0
                    target_max = min(expected_count, LOD_BUDGET) if expected_count > 0 else LOD_BUDGET
                    for k, raw_idx in enumerate(vis_indices):
                        if k % 4000 == 0 and self._restart:
                            return
                        i = int(raw_idx)
                        b = int(inst_bins[i])
                        hb = int(inst_hbins[i])
                        if b == -2:
                            b, hb = resolve_pair(all_insts[i].getName())
                            inst_bins[i] = b
                            inst_hbins[i] = hb
                        if hb == selected_hbin and 0 <= b < 5:
                            bins_to_draw[b].append(i)
                            total_matched += 1
                            if total_matched >= target_max:
                                break
            else:
                sampled_indices = vis_indices[::stride] if stride > 1 else vis_indices
                for k, raw_idx in enumerate(sampled_indices):
                    if k % 2000 == 0 and self._restart:
                        return
                    i = int(raw_idx)
                    b = int(inst_bins[i])
                    if b == -2:
                        b, hb = resolve_pair(all_insts[i].getName())
                        inst_bins[i] = b
                        inst_hbins[i] = hb
                    if 0 <= b < 5:
                        bins_to_draw[b].append(i)
                        total_matched += 1

                # If strided sampling hit mostly filler/unreported cells, scan remaining visible instances
                # up to LOD_BUDGET matched cells so sparse or filler-heavy designs still render all colors.
                if stride > 1 and total_matched < min(1000, LOD_BUDGET):
                    for k, raw_idx in enumerate(vis_indices):
                        if k % 4000 == 0 and self._restart:
                            return
                        if k % stride == 0:
                            continue
                        i = int(raw_idx)
                        b = int(inst_bins[i])
                        if b == -2:
                            b, hb = resolve_pair(all_insts[i].getName())
                            inst_bins[i] = b
                            inst_hbins[i] = hb
                        if 0 <= b < 5:
                            bins_to_draw[b].append(i)
                            total_matched += 1
                            if total_matched >= LOD_BUDGET:
                                break

            painter.save()
            if stride > 1:
                if selected_hbin is not None:
                    bin_total = getattr(selected_bin, "count", total_matched) if selected_bin is not None else total_matched
                    bin_stride = max(1, (bin_total + LOD_BUDGET - 1) // LOD_BUDGET)
                    scale = min(float(bin_stride) ** 0.48, 4.0) if bin_stride > 1 else 1.0
                else:
                    eff_stride = max(1, num_vis // max(total_matched, 1)) if total_matched > 0 else stride
                    scale = min(float(max(stride, eff_stride)) ** 0.48, 7.0)
                min_dbu = int(3.5 / max(ppd, 1e-6))
                for b_idx in range(len(IR_DROP_PALETTE)):
                    idx_list = bins_to_draw[b_idx]
                    if not idx_list:
                        continue
                    c = QColor(IR_DROP_PALETTE[b_idx])
                    c.setAlpha(210 if stride > 2 else 195)
                    painter.setPen(pens[b_idx])
                    painter.setBrush(QBrush(c))
                    for i in idx_list:
                        x1 = int(boxes[i, 0])
                        y1 = int(boxes[i, 1])
                        x2 = int(boxes[i, 2])
                        y2 = int(boxes[i, 3])
                        dw = max(int((x2 - x1) * scale), min_dbu)
                        dh = max(int((y2 - y1) * scale), min_dbu)
                        cx = (x1 + x2) >> 1
                        cy = (y1 + y2) >> 1
                        painter.drawRect(cx - (dw >> 1), cy - (dh >> 1), dw, dh)
            else:
                for b_idx in range(len(IR_DROP_PALETTE)):
                    idx_list = bins_to_draw[b_idx]
                    if not idx_list:
                        continue
                    painter.setPen(pens[b_idx])
                    painter.setBrush(brushes[b_idx])
                    for i in idx_list:
                        x1 = int(boxes[i, 0])
                        y1 = int(boxes[i, 1])
                        x2 = int(boxes[i, 2])
                        y2 = int(boxes[i, 3])
                        painter.drawRect(x1, y1, x2 - x1, y2 - y1)
            painter.restore()
            return

        # Fallback path for direct insts list (e.g. unit tests)
        if not insts:
            return
        painter.save()
        last_idx = None
        step = 1 if selected_hbin is not None else max(1, len(insts) // 8000)
        resolve_pair = resolve_both_fn if resolve_both_fn is not None else _fallback_resolve_both
        for index in range(0, len(insts), step):
            if index % 2000 == 0 and self._restart:
                break
            inst = insts[index]
            if inst.getMaster().isMacro():
                continue
            name = inst.getName()
            idx, hb_idx = resolve_pair(name)
            if idx is None or idx < 0:
                continue
            if selected_hbin is not None and hb_idx != selected_hbin:
                continue
            box = inst.getBBox().getBox()
            if box.area() <= 0:
                continue
            if idx != last_idx:
                painter.setPen(pens[idx])
                painter.setBrush(brushes[idx])
                last_idx = idx
            painter.drawRect(box.xMin(), box.yMin(), box.dx(), box.dy())
        painter.restore()

    def drawBoundaries(self, painter: QPainter, block: dbBlock) -> None:
        options = self._viewer.getOptions()

        # 1. Outer Rectangular Die Boundary
        die_rect = block.getDieArea()
        if options.isDieBoundaryVisible() and die_rect.area() > 0:
            die_pen = QPen(options.dieColor(), 1)
            die_pen.setCosmetic(True)
            painter.setPen(die_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(die_rect.xMin(), die_rect.yMin(), die_rect.dx(), die_rect.dy())

        # 2. Second Outline: Complex Polygon / Core Shape wrapping design elements
        if options.isPolygonBoundaryVisible():
            poly_pen = QPen(options.polygonColor(), 2, Qt.DashLine)
            poly_pen.setCosmetic(True)
            painter.setPen(poly_pen)
            painter.setBrush(Qt.NoBrush)

            if block.hasComplexDiePolygon():
                die_poly = block.getDieAreaPolygon()
                qpoly = QPolygonF([QPointF(p.x, p.y) for p in die_poly.getPoints()])
                painter.drawPolygon(qpoly)

            core_poly = block.getCoreAreaPolygon()
            if len(core_poly.getPoints()) > 4:
                qcore = QPolygonF([QPointF(p.x, p.y) for p in core_poly.getPoints()])
                painter.drawPolygon(qcore)
            else:
                core_rect = block.getCoreArea()
                if core_rect.area() > 0:
                    painter.drawRect(core_rect.xMin(), core_rect.yMin(), core_rect.dx(), core_rect.dy())


    # Ported from: gui/src/renderThread.cpp:271 addInstTransform
    def addInstTransform(self, xfm: QTransform, inst_xfm) -> None:
        if inst_xfm is None:
            return
        xfm.translate(inst_xfm.getOffset().x, inst_xfm.getOffset().y)
        o = inst_xfm.getOrient()
        if o == dbOrientType.R0:
            pass
        elif o == dbOrientType.R90:
            xfm.rotate(90)
        elif o == dbOrientType.R180:
            xfm.rotate(180)
        elif o == dbOrientType.R270:
            xfm.rotate(270)
        elif o == dbOrientType.MY:
            xfm.scale(-1, 1)
        elif o == dbOrientType.MYR90:
            xfm.rotate(90)
            xfm.scale(-1, 1)
        elif o == dbOrientType.MX:
            xfm.scale(1, -1)
        elif o == dbOrientType.MXR90:
            xfm.rotate(90)
            xfm.scale(1, -1)

    @staticmethod
    def isMacro(inst: dbInst) -> bool:
        return inst.getMaster().isMacro()

    # Ported from: gui/src/renderThread.cpp:510 drawInstanceOutlines
    def drawInstanceOutlines(self, painter: QPainter, insts: List[dbInst]) -> None:
        options = self._viewer.getOptions()
        ir_drop_active = bool(
            getattr(self._viewer, "_ir_drop_map_visible", False)
            and getattr(self._viewer, "_ir_drop_data", None) is not None
        )
        show_std_cells = options.areStandardCellsVisible() or ir_drop_active
        show_macros = options.areMacrosVisible()
        if not show_std_cells and not show_macros:
            return

        min_tag_height = self._viewer.nominalViewableResolution()
        initial_xfm = painter.transform()
        ppd = getattr(self._viewer, "pixels_per_dbu", 1.0)

        cell_pen = QPen(options.cellColor(), 0)
        cell_pen.setCosmetic(True)

        macro_pen = QPen(options.macroBorderColor(), 2)
        macro_pen.setCosmetic(True)
        macro_brush = QBrush(options.macroColor())

        resolve_both_fn = getattr(self._viewer, "resolve_ir_drop_bin_and_hbin", None)
        resolve_fn = getattr(self._viewer, "resolve_ir_drop_bin", None)
        selected_hbin = None
        if ir_drop_active:
            ensure_fn = getattr(self._viewer, "_ensure_ir_drop_color_cache", None)
            if ensure_fn is not None:
                ensure_fn()
            report = getattr(self._viewer, "_ir_drop_data", None)
            selected_hbin, _ = self._get_selected_hbin_info(report)
            name_to_bin = getattr(self._viewer, "_ir_drop_name_to_bin", None)
            name_to_hbin = getattr(self._viewer, "_ir_drop_name_to_hbin", None)
            records = getattr(report, "records_by_instance", {}) if report else {}
            if name_to_bin is None and resolve_fn is None and resolve_both_fn is None:
                name_to_bin = {k: report.color_index(v[0]) for k, v in records.items()} if report else {}
            if name_to_hbin is None and resolve_both_fn is None and report and hasattr(report, "histogram_bin_index"):
                name_to_hbin = {k: report.histogram_bin_index(v[0]) for k, v in records.items()}
            leaf_to_bin = getattr(self._viewer, "_ir_drop_leaf_to_bin", {})
            leaf_to_hbin = getattr(self._viewer, "_ir_drop_leaf_to_hbin", {})

            bin_pens = []
            bin_brushes = []
            for c_hex in IR_DROP_PALETTE:
                c = QColor(c_hex)
                pen = QPen(c.lighter(125), 0)
                pen.setCosmetic(True)
                bin_pens.append(pen)
                bin_brushes.append(QBrush(c))
        else:
            name_to_bin = {}
            name_to_hbin = {}
            leaf_to_bin = {}
            leaf_to_hbin = {}
            bin_pens = []
            bin_brushes = []

        last_mode = None  # "macro", "cell", or ("ir_cell", bin_idx)
        std_stride = 1 if (ir_drop_active and selected_hbin is not None) else max(1, len(insts) // 8000)

        for idx, inst in enumerate(insts):
            if idx % 1000 == 0 and self._restart:
                break
            master = inst.getMaster()
            is_macro = master.isMacro()

            if is_macro:
                if not show_macros:
                    continue
                xfm = QTransform(initial_xfm)
                self.addInstTransform(xfm, inst.getTransform())
                painter.setTransform(xfm)
                painter.setPen(macro_pen)
                painter.setBrush(macro_brush)
                last_mode = "macro"
                mbox = master.getPlacementBoundary()
                painter.drawRect(mbox.xMin(), mbox.yMin(), mbox.dx(), mbox.dy())

                # Corner orientation tag
                mw = master.getWidth()
                mh = master.getHeight()
                tag_w = min(0.25 * mw, 0.125 * mh)
                tag_x = mbox.xMin() + tag_w
                tag_y = mbox.yMin() + tag_w * 2
                painter.drawLine(QPointF(tag_x, mbox.yMin()), QPointF(mbox.xMin(), tag_y))
            else:
                if not show_std_cells:
                    continue
                if std_stride > 1 and (idx % std_stride) != 0:
                    continue

                bbox = inst.getBBox().getBox()
                if ir_drop_active:
                    name = inst.getName()
                    if resolve_both_fn is not None:
                        bin_idx, hbin_idx = resolve_both_fn(name)
                    elif resolve_fn is not None:
                        bin_idx = resolve_fn(name)
                        hbin_idx = name_to_hbin.get(name, -1) if name_to_hbin else -1
                    else:
                        bin_idx = name_to_bin.get(name) if name_to_bin else None
                        if bin_idx is None and leaf_to_bin:
                            leaf = name.rsplit("/", 1)[-1] if "/" in name else name
                            bin_idx = leaf_to_bin.get(leaf)
                        hbin_idx = name_to_hbin.get(name) if name_to_hbin else None
                        if hbin_idx is None and leaf_to_hbin:
                            leaf = name.rsplit("/", 1)[-1] if "/" in name else name
                            hbin_idx = leaf_to_hbin.get(leaf)
                    if bin_idx is not None and bin_idx < 0:
                        bin_idx = None
                    if selected_hbin is not None and hbin_idx != selected_hbin:
                        bin_idx = None

                    current_mode = ("ir_cell", bin_idx)
                    if last_mode != current_mode:
                        painter.setTransform(initial_xfm)
                        if bin_idx is not None:
                            painter.setPen(bin_pens[bin_idx])
                            painter.setBrush(bin_brushes[bin_idx])
                        else:
                            painter.setPen(cell_pen)
                            painter.setBrush(Qt.NoBrush)
                        last_mode = current_mode

                    painter.drawRect(bbox.xMin(), bbox.yMin(), bbox.dx(), bbox.dy())
                else:
                    if last_mode != "cell":
                        painter.setTransform(initial_xfm)
                        painter.setPen(cell_pen)
                        painter.setBrush(Qt.NoBrush)
                        last_mode = "cell"

                    painter.drawRect(bbox.xMin(), bbox.yMin(), bbox.dx(), bbox.dy())

                mh = master.getHeight()
                if mh >= min_tag_height:
                    xfm = QTransform(initial_xfm)
                    self.addInstTransform(xfm, inst.getTransform())
                    painter.setTransform(xfm)
                    mbox = master.getPlacementBoundary()
                    mw = master.getWidth()
                    tag_w = min(0.25 * mw, 0.125 * mh)
                    tag_x = mbox.xMin() + tag_w
                    tag_y = mbox.yMin() + tag_w * 2
                    painter.drawLine(QPointF(tag_x, mbox.yMin()), QPointF(mbox.xMin(), tag_y))
                    painter.setTransform(initial_xfm)
                    last_mode = None

        painter.setTransform(initial_xfm)

    # Ported from: gui/src/renderThread.cpp:957 drawLayer
    def drawLayer(
        self,
        painter: QPainter,
        block: dbBlock,
        layer: dbTechLayer,
        insts: List[dbInst],
        bounds: Rect,
        gui_painter: GuiPainter,
    ) -> None:
        options = self._viewer.getOptions()
        if not options.isVisible(layer):
            return

        shape_limit = self._viewer.shapeSizeLimit()
        layer_color = options.color(layer)
        layer_pattern = options.pattern(layer)

        # 1. Draw cell instance shapes (pins and OBS) on this layer (L978)
        self.drawInstanceShapes(layer, painter, insts, bounds)

        # 2. Obstructions on this layer (L981)
        if options.areObstructionsVisible():
            self.drawObstructions(block, layer, painter, bounds)

        # 3. Routing shapes & vias (L992-1020)
        if options.areRoutingSegmentsVisible() or options.areRoutingViasVisible():
            search = self._viewer.getSearch()
            routes = search.searchBoxShapes(
                block,
                layer,
                bounds.xMin(),
                bounds.yMin(),
                bounds.xMax(),
                bounds.yMax(),
                shape_limit,
            )
            if routes:
                painter.setPen(QPen(layer_color, 0))
                painter.setBrush(QBrush(layer_color, layer_pattern))
                for rect, is_via in routes:
                    if self._restart:
                        break
                    painter.drawRect(rect.xMin(), rect.yMin(), rect.dx(), rect.dy())

        # 4. Routing tracks (L1111)
        if options.areTracksVisible() and (options.arePrefTracksVisible() or options.areNonPrefTracksVisible()):
            self.drawTracks(layer, painter, block, bounds)

    # Ported from: gui/src/renderThread.cpp:562 drawInstanceShapes
    def drawInstanceShapes(
        self,
        layer: dbTechLayer,
        painter: QPainter,
        insts: List[dbInst],
        bounds: Rect,
    ) -> None:
        options = self._viewer.getOptions()
        show_obs = options.areInstanceBlockagesVisible()
        show_pins = options.areInstancePinsVisible()
        show_std_cells = options.areStandardCellsVisible()
        show_macros = options.areMacrosVisible()
        if not show_std_cells and not show_macros:
            return

        ppd = self._viewer.pixels_per_dbu
        min_height = self._viewer.nominalViewableResolution()
        initial_xfm = painter.transform()
        color = options.color(layer)
        pattern = options.pattern(layer)

        obs_brush = QBrush(color.lighter(130))
        pin_brush = QBrush(color, pattern)

        for idx, inst in enumerate(insts):
            if idx % 200 == 0 and self._restart:
                break
            is_macro = self.isMacro(inst)
            if is_macro and not show_macros:
                continue
            if not is_macro and not show_std_cells:
                continue

            master = inst.getMaster()
            mh = master.getHeight()
            if not is_macro and (mh * ppd < 8.0 or mh < min_height):
                continue
            elif is_macro and mh < min_height:
                continue

            boxes = self._viewer.boxesByLayer(master, layer)
            if boxes is None:
                continue

            xfm = QTransform(initial_xfm)
            self.addInstTransform(xfm, inst.getTransform())
            painter.setTransform(xfm)
            painter.setPen(Qt.NoPen)

            # Draw cell obstructions (OBS)
            if show_obs and boxes.get("obs"):
                painter.setBrush(obs_brush)
                for poly in boxes["obs"]:
                    painter.drawPolygon(poly)

            # Draw cell pins (MTerms)
            if show_pins and boxes.get("mterms"):
                painter.setBrush(pin_brush)
                for poly in boxes["mterms"]:
                    painter.drawPolygon(poly)

        painter.setTransform(initial_xfm)

    # Ported from: gui/src/renderThread.cpp:888 drawObstructions
    def drawObstructions(
        self,
        block: dbBlock,
        layer: dbTechLayer,
        painter: QPainter,
        bounds: Rect,
    ) -> None:
        options = self._viewer.getOptions()
        color = options.color(layer).darker(150)
        pattern = options.pattern(layer)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color, pattern))

        search = self._viewer.getSearch()
        obs_list = search.searchObstructions(
            block,
            layer,
            bounds.xMin(),
            bounds.yMin(),
            bounds.xMax(),
            bounds.yMax(),
        )
        for obs in obs_list:
            if self._restart:
                break
            b = obs.getBox()
            painter.drawRect(b.xMin(), b.yMin(), b.dx(), b.dy())

    # Ported from: gui/src/renderThread.cpp:844 drawBlockages
    def drawBlockages(
        self,
        painter: QPainter,
        block: dbBlock,
        bounds: Rect,
        insts: List[dbInst],
    ) -> None:
        options = self._viewer.getOptions()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(options.placementBlockageColor(), options.placementBlockagePattern()))

        search = self._viewer.getSearch()
        blockages = search.searchBlockages(
            block,
            bounds.xMin(),
            bounds.yMin(),
            bounds.xMax(),
            bounds.yMax(),
        )
        for b in blockages:
            if self._restart:
                break
            box = b.getBox()
            painter.drawRect(box.xMin(), box.yMin(), box.dx(), box.dy())

    # Ported from: gui/src/renderThread.cpp:324 drawTracks
    def drawTracks(
        self,
        layer: dbTechLayer,
        painter: QPainter,
        block: dbBlock,
        bounds: Rect,
    ) -> None:
        grid = block.findTrackGrid(layer)
        if grid is None:
            return

        die = block.getDieArea()
        if not die.intersects(bounds):
            return

        draw_bounds = die.intersect(bounds)
        options = self._viewer.getOptions()
        pen = QPen(options.color(layer))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        ppd = self._viewer.pixels_per_dbu
        is_horiz = layer.getDirection() == dbTechLayerDir.HORIZONTAL

        # Vertical tracks (GridX)
        if (not is_horiz and options.arePrefTracksVisible()) or (is_horiz and options.areNonPrefTracksVisible()):
            grid_x = grid.getGridX()
            if len(grid_x) >= 2:
                pitch_x_px = abs(grid_x[1] - grid_x[0]) * ppd
                if pitch_x_px >= 3.0:
                    i_start = bisect_left(grid_x, draw_bounds.xMin())
                    i_end = bisect_right(grid_x, draw_bounds.xMax())
                    for idx in range(i_start, i_end):
                        if (idx - i_start) % 100 == 0 and self._restart:
                            break
                        x = grid_x[idx]
                        painter.drawLine(x, draw_bounds.yMin(), x, draw_bounds.yMax())

        # Horizontal tracks (GridY)
        if (is_horiz and options.arePrefTracksVisible()) or (not is_horiz and options.areNonPrefTracksVisible()):
            grid_y = grid.getGridY()
            if len(grid_y) >= 2:
                pitch_y_px = abs(grid_y[1] - grid_y[0]) * ppd
                if pitch_y_px >= 3.0:
                    j_start = bisect_left(grid_y, draw_bounds.yMin())
                    j_end = bisect_right(grid_y, draw_bounds.yMax())
                    for idx in range(j_start, j_end):
                        if (idx - j_start) % 100 == 0 and self._restart:
                            break
                        y = grid_y[idx]
                        painter.drawLine(draw_bounds.xMin(), y, draw_bounds.xMax(), y)

    # Ported from: gui/src/renderThread.cpp:407 drawRows
    def drawRows(self, painter: QPainter, block: dbBlock, bounds: Rect) -> None:
        options = self._viewer.getOptions()
        if not options.areSitesVisible():
            return

        pen = QPen(options.siteColor())
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        search = self._viewer.getSearch()
        rows = search.searchRows(
            block,
            bounds.xMin(),
            bounds.yMin(),
            bounds.xMax(),
            bounds.yMax(),
            self.min_viewable_resolution(),
        )
        for row in rows:
            if self._restart:
                break
            rb = row.getBBox()
            painter.drawRect(rb.xMin(), rb.yMin(), rb.dx(), rb.dy())

    def drawIOPins(self, painter: QPainter, block: dbBlock, bounds: Rect) -> None:
        options = self._viewer.getOptions()
        if not options.areIOPinsVisible():
            return

        die_rect = block.getDieArea()
        if die_rect.area() <= 0:
            die_rect = block.getBBox()
        if die_rect.area() <= 0:
            return

        ppd = self._viewer.pixels_per_dbu
        if ppd <= 0:
            return

        tech = block.getTech()
        dbu_per_micron = tech.getDbuPerMicron() if tech else 1000
        min_pin_dbu = 6.0 / ppd
        min_axis_dbu = 1.5 / ppd
        pin_color = options.ioPinColor()
        if ppd * dbu_per_micron < 4.0:
            painter.setPen(Qt.NoPen)
        else:
            painter.setPen(QPen(pin_color.darker(140), max(0.4, 0.8 / ppd)))
        painter.setBrush(QBrush(pin_color))
        max_pin_w = max(die_rect.dx() * 0.02, min_pin_dbu)
        max_pin_h = max(die_rect.dy() * 0.02, min_pin_dbu)

        show_names = (
            options.areIOPinNamesVisible()
            and self._viewer.nominalViewableResolution() <= 1000
            and ppd * dbu_per_micron >= 3.5
        )
        font = QFont("Segoe UI", 8, QFont.Medium)
        metrics = QFontMetrics(font)
        drawn_label_rects = []
        orientation_edges = {
            "R0": "top",
            "MY": "top",
            "R180": "bottom",
            "MX": "bottom",
            "R90": "left",
            "MYR90": "left",
            "R270": "right",
            "MXR90": "right",
        }

        for bterm in block.getBTerms():
            if self._restart:
                break
            if not bterm.isIOPin():
                continue

            for bpin in bterm.getBPins():
                pin_shapes = [box for _, box in bpin.getBoxes()]
                pin_shapes.extend(poly.getEnclosingRect() for _, poly in bpin.getPolygons())
                if not pin_shapes and bpin.hasLoc():
                    loc = bpin.getLoc()
                    pin_shapes.append(Rect(loc.x - 140, loc.y - 140, loc.x + 140, loc.y + 140))

                pin_orient = bpin.getOrient()
                edge = orientation_edges.get(pin_orient.name if pin_orient else "")
                for shape in pin_shapes:
                    if self._restart:
                        break
                    if shape.area() <= 0:
                        continue

                    expand = int(min_pin_dbu)
                    if not Rect(shape.xMin() - expand, shape.yMin() - expand,
                                shape.xMax() + expand, shape.yMax() + expand).intersects(bounds):
                        continue

                    cx = (shape.xMin() + shape.xMax()) / 2.0
                    cy = (shape.yMin() + shape.yMax()) / 2.0
                    shape_edge = edge
                    if shape_edge is None:
                        distances = {
                            "left": abs(cx - die_rect.xMin()),
                            "right": abs(cx - die_rect.xMax()),
                            "bottom": abs(cy - die_rect.yMin()),
                            "top": abs(cy - die_rect.yMax()),
                        }
                        shape_edge = min(distances, key=distances.get)

                    if shape_edge in ("bottom", "top"):
                        pin_w = min(max(shape.dx(), min(min_pin_dbu, min_axis_dbu)), max_pin_w)
                        pin_h = min(max(shape.dy(), min_pin_dbu), max_pin_h)
                    else:
                        pin_w = min(max(shape.dx(), min_pin_dbu), max_pin_w)
                        pin_h = min(max(shape.dy(), min(min_pin_dbu, min_axis_dbu)), max_pin_h)
                    painter.drawRect(QRectF(cx - pin_w / 2, cy - pin_h / 2, pin_w, pin_h))

                    if not show_names:
                        continue

                    name = bterm.getName().split("/")[-1]
                    if len(name) > 16:
                        name = name[:14] + ".."
                    text_w = metrics.horizontalAdvance(name)
                    text_h = metrics.height()
                    gap = 6.0 / ppd
                    label_point = {
                        "bottom": QPointF(cx, cy - pin_h / 2 - gap),
                        "top": QPointF(cx, cy + pin_h / 2 + gap),
                        "left": QPointF(cx - pin_w / 2 - gap, cy),
                        "right": QPointF(cx + pin_w / 2 + gap, cy),
                    }[shape_edge]
                    screen_point = painter.transform().map(label_point)

                    if shape_edge in ("bottom", "top"):
                        label_rect = QRectF(screen_point.x() - text_h / 2,
                                            screen_point.y() - text_w if shape_edge == "top" else screen_point.y(),
                                            text_h, text_w)
                    else:
                        label_rect = QRectF(screen_point.x() - text_w if shape_edge == "left" else screen_point.x(),
                                            screen_point.y() - text_h / 2, text_w, text_h)
                    if any(label_rect.intersects(previous) for previous in drawn_label_rects):
                        continue
                    drawn_label_rects.append(label_rect)

                    painter.save()
                    painter.setFont(font)
                    painter.setPen(QPen(options.instanceNameColor(), 0))
                    painter.translate(label_point)
                    painter.scale(1.0 / ppd, -1.0 / ppd)
                    if shape_edge == "bottom":
                        painter.rotate(90)
                        painter.drawText(0, text_h // 3, name)
                    elif shape_edge == "top":
                        painter.rotate(-90)
                        painter.drawText(0, text_h // 3, name)
                    elif shape_edge == "left":
                        painter.drawText(-text_w, text_h // 3, name)
                    else:
                        painter.drawText(0, text_h // 3, name)
                    painter.restore()

    # Legacy implementation retained temporarily for comparison while keeping the public renderer stable.
    def _drawIOPinsLegacy(self, painter: QPainter, block: dbBlock, bounds: Rect) -> None:
        options = self._viewer.getOptions()
        if not options.areIOPinsVisible():
            return

        die_rect = block.getDieArea()
        if die_rect.area() <= 0:
            die_rect = block.getBBox()
        if die_rect.area() <= 0:
            return

        ppd = self._viewer.pixels_per_dbu
        if ppd <= 0:
            return
        scale_adjust = 1.0 / ppd

        die_w = max(die_rect.dx(), 1)
        die_h = max(die_rect.dy(), 1)

        # Clear, prominent EDA marker dimensions in screen pixels (16px length, 6px half-width)
        marker_h = max(int(16.0 * scale_adjust), 4)
        marker_w = max(int(6.0 * scale_adjust), 2)

        pin_color = options.ioPinColor()
        marker_pen = QPen(pin_color.darker(140), 1)
        marker_pen.setCosmetic(True)
        marker_brush = QBrush(pin_color)

        box_pen = QPen(pin_color, 1)
        box_pen.setCosmetic(True)
        box_brush = QBrush(pin_color)

        # Standard cell name matching algorithm:
        # Hide names when zoomed out (nominalViewableResolution > 1000 DBU), identical to standard cells
        min_size = self._viewer.nominalViewableResolution()
        show_names = (
            (options.areInstanceNamesVisible() or options.areIOPinNamesVisible())
            and min_size <= 1000
        )
        drawn_label_rects = []
        if show_names:
            font_cell = QFont("Segoe UI", 8)
            fm_cell = QFontMetrics(font_cell)

        for bterm in block.getBTerms():
            if self._restart:
                break
            if not bterm.isIOPin():
                continue

            io_type = bterm.getIoType()
            lname = bterm.getName().lower()
            is_input = (
                io_type == dbIoType.INPUT
                or (
                    io_type == dbIoType.INOUT
                    and (
                        lname.startswith("in_")
                        or lname.startswith("i_")
                        or lname.endswith("_in")
                        or lname.endswith("_i")
                        or "clk" in lname
                        or "rst" in lname
                        or "reset" in lname
                        or lname.startswith("req_")
                    )
                )
            )
            is_output = (
                io_type == dbIoType.OUTPUT
                or (
                    io_type == dbIoType.INOUT
                    and not is_input
                    and (
                        lname.startswith("out_")
                        or lname.startswith("o_")
                        or lname.endswith("_out")
                        or lname.endswith("_o")
                        or lname.startswith("resp_")
                    )
                )
            )

            for bpin in bterm.getBPins():
                if self._restart:
                    break

                boxes = bpin.getBoxes()
                if not boxes and bpin.hasLoc():
                    loc = bpin.getLoc()
                    d = 140
                    boxes = [(None, Rect(loc.x - d, loc.y - d, loc.x + d, loc.y + d))]

                for layer, box in boxes:
                    # Ignore unplaced or empty boxes
                    if box.area() <= 0:
                        continue

                    # Check visibility against query bounds (with margin for marker)
                    expand_m = int(marker_h * 2)
                    query_box = Rect(
                        box.xMin() - expand_m,
                        box.yMin() - expand_m,
                        box.xMax() + expand_m,
                        box.yMax() + expand_m,
                    )
                    if not query_box.intersects(bounds):
                        continue

                    pin_center = Point(
                        (box.xMin() + box.xMax()) // 2,
                        (box.yMin() + box.yMax()) // 2,
                    )
                    cx, cy = pin_center.x, pin_center.y

                    # Compute normalized distances to the 4 boundaries
                    d_left = abs(box.xMin() - die_rect.xMin())
                    d_right = abs(box.xMax() - die_rect.xMax())
                    d_bot = abs(box.yMin() - die_rect.yMin())
                    d_top = abs(box.yMax() - die_rect.yMax())

                    is_vert = box.dy() > box.dx()
                    is_horiz = box.dx() > box.dy()

                    nd_left = d_left / float(die_w)
                    nd_right = d_right / float(die_w)
                    nd_top = d_top / float(die_h)
                    nd_bot = d_bot / float(die_h)

                    # Bias by track geometry to prevent corner misclassification
                    if is_vert:
                        nd_left += 0.5
                        nd_right += 0.5
                    elif is_horiz:
                        nd_top += 0.5
                        nd_bot += 0.5

                    ndists = [nd_left, nd_right, nd_top, nd_bot]
                    arg_min = ndists.index(min(ndists))

                    # Construct exact directional marker polygon
                    qpoly = QPolygonF()
                    bx, by = cx, cy

                    if arg_min == 3:  # Bottom edge
                        by = die_rect.yMin() if d_bot <= marker_h * 4 else cy
                        if is_input:
                            # Arrow points UP into core
                            qpoly.append(QPointF(cx, by))
                            qpoly.append(QPointF(cx - marker_w, by - marker_h))
                            qpoly.append(QPointF(cx + marker_w, by - marker_h))
                        elif is_output:
                            # Arrow points DOWN out of core
                            qpoly.append(QPointF(cx, by - marker_h))
                            qpoly.append(QPointF(cx - marker_w, by))
                            qpoly.append(QPointF(cx + marker_w, by))
                        else:
                            # Diamond
                            qpoly.append(QPointF(cx, by))
                            qpoly.append(QPointF(cx - marker_w, by - marker_h // 2))
                            qpoly.append(QPointF(cx, by - marker_h))
                            qpoly.append(QPointF(cx + marker_w, by - marker_h // 2))

                    elif arg_min == 2:  # Top edge
                        by = die_rect.yMax() if d_top <= marker_h * 4 else cy
                        if is_input:
                            # Arrow points DOWN into core
                            qpoly.append(QPointF(cx, by))
                            qpoly.append(QPointF(cx - marker_w, by + marker_h))
                            qpoly.append(QPointF(cx + marker_w, by + marker_h))
                        elif is_output:
                            # Arrow points UP out of core
                            qpoly.append(QPointF(cx, by + marker_h))
                            qpoly.append(QPointF(cx - marker_w, by))
                            qpoly.append(QPointF(cx + marker_w, by))
                        else:
                            # Diamond
                            qpoly.append(QPointF(cx, by))
                            qpoly.append(QPointF(cx - marker_w, by + marker_h // 2))
                            qpoly.append(QPointF(cx, by + marker_h))
                            qpoly.append(QPointF(cx + marker_w, by + marker_h // 2))

                    elif arg_min == 0:  # Left edge
                        bx = die_rect.xMin() if d_left <= marker_h * 4 else cx
                        if is_input:
                            # Arrow points RIGHT into core
                            qpoly.append(QPointF(bx, cy))
                            qpoly.append(QPointF(bx - marker_h, cy - marker_w))
                            qpoly.append(QPointF(bx - marker_h, cy + marker_w))
                        elif is_output:
                            # Arrow points LEFT out of core
                            qpoly.append(QPointF(bx - marker_h, cy))
                            qpoly.append(QPointF(bx, cy - marker_w))
                            qpoly.append(QPointF(bx, cy + marker_w))
                        else:
                            # Diamond
                            qpoly.append(QPointF(bx, cy))
                            qpoly.append(QPointF(bx - marker_h // 2, cy - marker_w))
                            qpoly.append(QPointF(bx - marker_h, cy))
                            qpoly.append(QPointF(bx - marker_h // 2, cy + marker_w))

                    else:  # Right edge
                        bx = die_rect.xMax() if d_right <= marker_h * 4 else cx
                        if is_input:
                            # Arrow points LEFT into core
                            qpoly.append(QPointF(bx, cy))
                            qpoly.append(QPointF(bx + marker_h, cy - marker_w))
                            qpoly.append(QPointF(bx + marker_h, cy + marker_w))
                        elif is_output:
                            # Arrow points RIGHT out of core
                            qpoly.append(QPointF(bx + marker_h, cy))
                            qpoly.append(QPointF(bx, cy - marker_w))
                            qpoly.append(QPointF(bx, cy + marker_w))
                        else:
                            # Diamond
                            qpoly.append(QPointF(bx, cy))
                            qpoly.append(QPointF(bx + marker_h // 2, cy - marker_w))
                            qpoly.append(QPointF(bx + marker_h, cy))
                            qpoly.append(QPointF(bx + marker_h // 2, cy + marker_w))

                    # 1. Draw marker polygon
                    painter.setPen(marker_pen)
                    painter.setBrush(marker_brush)
                    painter.drawPolygon(qpoly)

                    # 2. Draw physical pin geometry (clamp to prevent huge power rails or macro pad overlay artifacts)
                    max_pin_span = min(int(10000 * (die_w / 1000000.0 + 1)), int(die_w * 0.02))
                    if box.dx() <= max_pin_span and box.dy() <= max_pin_span:
                        painter.setPen(box_pen)
                        painter.setBrush(box_brush)
                        painter.drawRect(box.xMin(), box.yMin(), box.dx(), box.dy())

                    # 3. Draw pin name (same algorithm and font as standard cell names)
                    if show_names:
                        name = bterm.getName()
                        tw = fm_cell.horizontalAdvance(name)
                        th = fm_cell.height()
                        gap = int(4.0 * scale_adjust)

                        # Determine screen-space bounding box to prevent overlapping text collision
                        # Left (arg_min == 0) & Right (arg_min == 1): horizontal text
                        # Top (arg_min == 2) & Bottom (arg_min == 3): vertical rotated text (prevents side-by-side collisions)
                        if arg_min == 0:  # Left edge (horizontal text extending left)
                            screen_pt = painter.transform().map(QPointF(bx - marker_h - gap, cy))
                            label_rect = QRectF(screen_pt.x() - tw, screen_pt.y() - th * 0.7, tw, th)
                        elif arg_min == 1:  # Right edge (horizontal text extending right)
                            screen_pt = painter.transform().map(QPointF(bx + marker_h + gap, cy))
                            label_rect = QRectF(screen_pt.x(), screen_pt.y() - th * 0.7, tw, th)
                        elif arg_min == 2:  # Top edge (vertical text extending upwards away from chip)
                            screen_pt = painter.transform().map(QPointF(cx, by + marker_h + gap))
                            label_rect = QRectF(screen_pt.x() - th * 0.5, screen_pt.y() - tw, th, tw)
                        else:  # Bottom edge (vertical text extending downwards away from chip)
                            screen_pt = painter.transform().map(QPointF(cx, by - marker_h - gap))
                            label_rect = QRectF(screen_pt.x() - th * 0.5, screen_pt.y(), th, tw)

                        # Check collision against previously rendered labels
                        collides = False
                        for prev_rect in drawn_label_rects:
                            if label_rect.intersects(prev_rect):
                                collides = True
                                break

                        if not collides:
                            drawn_label_rects.append(label_rect)
                            painter.save()
                            painter.setFont(font_cell)
                            painter.setPen(QPen(options.instanceNameColor(), 0))

                            if arg_min == 0:  # Left
                                painter.translate(bx - marker_h - gap, cy)
                                painter.scale(scale_adjust, -scale_adjust)
                                painter.drawText(-tw, th // 3, name)
                            elif arg_min == 1:  # Right
                                painter.translate(bx + marker_h + gap, cy)
                                painter.scale(scale_adjust, -scale_adjust)
                                painter.drawText(0, th // 3, name)
                            elif arg_min == 2:  # Top (rotated 90 deg, extending up away from chip)
                                painter.translate(cx, by + marker_h + gap)
                                painter.scale(scale_adjust, -scale_adjust)
                                painter.rotate(-90)
                                painter.drawText(0, th // 3, name)
                            else:  # Bottom (rotated -90 deg, extending down away from chip)
                                painter.translate(cx, by - marker_h - gap)
                                painter.scale(scale_adjust, -scale_adjust)
                                painter.rotate(90)
                                painter.drawText(0, th // 3, name)

                            painter.restore()

    # Ported from: gui/src/renderThread.cpp:659 drawInstanceNames
    def drawInstanceNames(self, painter: QPainter, insts: List[dbInst]) -> None:
        options = self._viewer.getOptions()
        if not options.areInstanceNamesVisible():
            return

        initial_xfm = painter.transform()
        font_cell = QFont("Segoe UI", 8)
        font_macro = QFont("Segoe UI", 9, QFont.Bold)
        fm_cell = QFontMetrics(font_cell)
        fm_macro = QFontMetrics(font_macro)

        ppd = self._viewer.pixels_per_dbu
        if ppd <= 0:
            return
        scale_adjust = 1.0 / ppd
        min_size = self._viewer.nominalViewableResolution()

        show_std_cells = options.areStandardCellsVisible()
        show_macros = options.areMacrosVisible()
        if not show_std_cells and not show_macros:
            return

        for inst in insts:
            if self._restart:
                break
            is_macro = self.isMacro(inst)
            if is_macro and not show_macros:
                continue
            if not is_macro and not show_std_cells:
                continue

            master = inst.getMaster()
            mh = master.getHeight()
            mw = master.getWidth()

            if not is_macro and mh < min_size:
                continue

            bbox = inst.getBBox().getBox()
            box_w_px = bbox.dx() * ppd
            box_h_px = bbox.dy() * ppd

            if not is_macro and (box_w_px < 35 or box_h_px < 14):
                continue

            name = inst.getName()

            painter.save()
            if is_macro:
                if box_w_px < 25 or box_h_px < 14:
                    continue
                painter.setFont(font_macro)
                elided = fm_macro.elidedText(name, Qt.ElideRight, int(box_w_px - 8))
                if elided:
                    pad_dbu = int(50 * scale_adjust)
                    painter.translate(bbox.xMin() + pad_dbu, bbox.yMin() + bbox.dy() - pad_dbu)
                    painter.scale(scale_adjust, -scale_adjust)  # Invert Y back upright!
                    painter.setPen(QPen(QColor(255, 255, 255, 240), 0))
                    painter.drawText(2, 0, elided)
            else:
                painter.setFont(font_cell)
                elided = fm_cell.elidedText(name, Qt.ElideRight, int(box_w_px - 4))
                if elided:
                    painter.translate(bbox.xMin() + 50, bbox.yMin() + bbox.dy() - 50)
                    painter.scale(scale_adjust, -scale_adjust)  # Invert Y back upright!
                    painter.setPen(QPen(options.instanceNameColor(), 0))
                    painter.drawText(2, 0, elided)
            painter.restore()

        painter.setTransform(initial_xfm)

    def min_viewable_resolution(self) -> int:
        return self._viewer.fineViewableResolution()
