"""RenderThread ported from RISHI gui/src/renderThread.cpp."""

from typing import TYPE_CHECKING, List, Dict, Tuple, Optional
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
        if ir_drop_active:
            ppd = getattr(self._viewer, "pixels_per_dbu", 1.0)
            inst_limit = max(int(0.5 / max(ppd, 1e-6)), 0) if ppd > 0 else 0
        else:
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
        # DEBUG
        # print(f"DEBUG: drawChip bounds={bounds}, inst_limit={inst_limit}, found {len(insts)} insts")

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

        if self._viewer._ir_drop_map_visible and self._viewer._ir_drop_data is not None:
            self.drawIRDropOverlay(painter, insts)

        if self._restart:
            return

        # 6. Draw rows & sites (L1280)
        if options.areRowsVisible():
            self.drawRows(painter, block, bounds)

        # 7. Re-draw Die & Polygon outlines on top of blockages/macros so boundaries remain unbroken
        self.drawBoundaries(painter, block)

        # 8. Draw instance names (L1273)
        if options.areInstanceNamesVisible():
            self.drawInstanceNames(painter, insts)

        # 9. Draw IO pins (L1233)
        if options.areIOPinsVisible():
            self.drawIOPins(painter, block, bounds)

    def drawIRDropOverlay(self, painter: QPainter, insts: List[dbInst]) -> None:
        """Draws a distinct translucent IR-drop range color over standard-cell footprints."""
        if not insts or getattr(self._viewer, "pixels_per_dbu", 1.0) <= 0:
            return
        report = getattr(self._viewer, "_ir_drop_data", None)
        if report is None:
            return

        name_to_bin = getattr(self._viewer, "_ir_drop_name_to_bin", None)
        if name_to_bin is None:
            records = getattr(report, "records_by_instance", {})
            name_to_bin = {k: report.color_index(v[0]) for k, v in records.items()}
        leaf_to_bin = getattr(self._viewer, "_ir_drop_leaf_to_bin", {})

        brushes = []
        pens = []
        for color_hex in IR_DROP_PALETTE:
            color = QColor(color_hex)
            pen = QPen(color.lighter(125), 0)
            pen.setCosmetic(True)
            pens.append(pen)
            color.setAlpha(175)
            brushes.append(QBrush(color))

        painter.save()
        last_idx = None
        for index, inst in enumerate(insts):
            if index % 2000 == 0 and self._restart:
                break
            if inst.getMaster().isMacro():
                continue
            name = inst.getName()
            idx = name_to_bin.get(name)
            if idx is None and leaf_to_bin:
                leaf = name.rsplit("/", 1)[-1] if "/" in name else name
                idx = leaf_to_bin.get(leaf)
            if idx is None:
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

        if ir_drop_active:
            name_to_bin = getattr(self._viewer, "_ir_drop_name_to_bin", None)
            if name_to_bin is None:
                report = getattr(self._viewer, "_ir_drop_data", None)
                records = getattr(report, "records_by_instance", {}) if report else {}
                name_to_bin = {k: report.color_index(v[0]) for k, v in records.items()} if report else {}
            leaf_to_bin = getattr(self._viewer, "_ir_drop_leaf_to_bin", {})

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
            leaf_to_bin = {}
            bin_pens = []
            bin_brushes = []

        last_mode = None  # "macro", "cell", or ("ir_cell", bin_idx)

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

                bbox = inst.getBBox().getBox()
                if ir_drop_active:
                    name = inst.getName()
                    bin_idx = name_to_bin.get(name)
                    if bin_idx is None and leaf_to_bin:
                        leaf = name.rsplit("/", 1)[-1] if "/" in name else name
                        bin_idx = leaf_to_bin.get(leaf)

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
