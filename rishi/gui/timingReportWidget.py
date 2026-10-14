"""Cadence Innovus / Tempus Timing Report & Debug Widget.

A modular, independent EDA timing debug interface matching reportTimingWidget.png:
- Top bar with report file selector, browse button, and reload.
- Path Histogram: interactive bar chart of slack distribution with click-to-filter.
- Category Summary: WNS, TNS, passing/failing path metrics.
- Path Category Table: timing group breakdown.
- Path List Table: 11 columns matching Cadence GUI with pagination, sortable columns,
  multi-path highlight checkboxes, and zoom-to-path navigation.
- Optimization Failure Reason Table: violation breakdown.
- Independent operation: operates standalone or connects to LayoutViewer when DEF is loaded.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rishi.timing.tarpt_parser import (
    CategoryStats,
    HistogramBin,
    TarptParser,
    TimingPath,
    TimingReportData,
)


# ==============================================================================
# 1. Path Histogram Widget (Slack Distribution Bar Chart)
# ==============================================================================

class PathHistogramWidget(QWidget):
    """Interactive bar chart displaying slack distribution across bins."""

    bin_selected = Signal(object)  # Emits selected HistogramBin or None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._bins: List[HistogramBin] = []
        self._selected_bin: Optional[HistogramBin] = None
        self._hover_bin: Optional[HistogramBin] = None
        self._hover_pos: Optional[QPointF] = None

        self.setMinimumHeight(150)
        self.setMinimumWidth(260)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_bins(self, bins: List[HistogramBin]) -> None:
        self._bins = bins
        self._selected_bin = None
        self._hover_bin = None
        self.update()

    def get_selected_bin(self) -> Optional[HistogramBin]:
        return self._selected_bin

    def clear_selection(self) -> None:
        self._selected_bin = None
        self.update()
        self.bin_selected.emit(None)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        try:
            w = self.width()
            h = self.height()

            # Background & border
            painter.fillRect(0, 0, w, h, QColor("#16181D"))
            painter.setPen(QPen(QColor("#2B2E38"), 1))
            painter.drawRect(0, 0, w - 1, h - 1)

            if not self._bins:
                painter.setPen(QColor("#707888"))
                painter.setFont(QFont("Segoe UI", 9))
                painter.drawText(self.rect(), Qt.AlignCenter, "No Timing Histogram Data")
                return

            # Plot layout metrics
            pad_left = 38
            pad_right = 16
            pad_top = 22
            pad_bottom = 24

            plot_w = w - pad_left - pad_right
            plot_h = h - pad_top - pad_bottom

            if plot_w <= 10 or plot_h <= 10:
                return

            max_count = max((b.count for b in self._bins), default=1)
            if max_count == 0:
                max_count = 1

            # Grid lines and Y-axis labels
            painter.setFont(QFont("Segoe UI", 7))
            grid_pen = QPen(QColor("#252830"), 1, Qt.DashLine)
            painter.setPen(grid_pen)

            num_y_ticks = 4
            for i in range(num_y_ticks + 1):
                y_val = int(max_count * i / float(num_y_ticks))
                y_pos = int(pad_top + plot_h - (plot_h * i / float(num_y_ticks)))
                painter.setPen(grid_pen)
                painter.drawLine(pad_left, y_pos, pad_left + plot_w, y_pos)
                painter.setPen(QColor("#707888"))
                painter.drawText(2, y_pos + 4, f"{y_val:>4}")

            # Draw bars
            n_bins = len(self._bins)
            bar_gap = 2
            bar_w = max(2.0, (plot_w - (n_bins - 1) * bar_gap) / float(n_bins))

            for i, b in enumerate(self._bins):
                bx = pad_left + i * (bar_w + bar_gap)
                bar_h_px = (b.count / float(max_count)) * plot_h
                by = pad_top + plot_h - bar_h_px

                is_selected = (self._selected_bin == b)
                is_hovered = (self._hover_bin == b)

                # Color: Red for failing bins, Green for passing
                if b.is_failing:
                    base_color = QColor("#E53935") if not is_hovered else QColor("#FF5252")
                    grad_color = QColor("#B71C1C")
                else:
                    base_color = QColor("#388E3C") if not is_hovered else QColor("#4CAF50")
                    grad_color = QColor("#1B5E20")

                grad = QLinearGradient(bx, by, bx, by + bar_h_px)
                grad.setColorAt(0.0, base_color)
                grad.setColorAt(1.0, grad_color)

                bar_rect = QRectF(bx, by, bar_w, max(bar_h_px, 1.0))
                painter.setBrush(QBrush(grad))

                if is_selected:
                    painter.setPen(QPen(QColor("#FFE600"), 2))
                elif is_hovered:
                    painter.setPen(QPen(QColor("#FFFFFF"), 1))
                else:
                    painter.setPen(QPen(QColor("#1A1D24"), 1))

                painter.drawRect(bar_rect)

            # X-axis base line
            painter.setPen(QPen(QColor("#3A4050"), 1))
            painter.drawLine(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h)

            # X-axis slack range labels
            painter.setPen(QColor("#8A92A4"))
            min_slack = self._bins[0].slack_min
            max_slack = self._bins[-1].slack_max
            painter.drawText(pad_left, h - 8, f"{min_slack:+.3f} ns")
            mid_text = "0.000 ns"
            mid_w = painter.fontMetrics().horizontalAdvance(mid_text)
            painter.drawText(pad_left + int(plot_w / 2.0) - int(mid_w / 2.0), h - 8, mid_text)
            max_text = f"{max_slack:+.3f} ns"
            max_w = painter.fontMetrics().horizontalAdvance(max_text)
            painter.drawText(w - pad_right - max_w, h - 8, max_text)

            # Interactive Tooltip HUD Card
            if self._hover_bin and self._hover_pos:
                b = self._hover_bin
                tt_text = f"Slack: [{b.slack_min:+.4f}, {b.slack_max:+.4f}] ns | Paths: {b.count}"
                fm = painter.fontMetrics()
                tt_w = fm.horizontalAdvance(tt_text) + 14
                tt_h = fm.height() + 8
                tt_x = min(max(self._hover_pos.x() - tt_w / 2.0, 10.0), w - tt_w - 10.0)
                tt_y = max(self._hover_pos.y() - tt_h - 10.0, 5.0)

                painter.setPen(QPen(QColor("#454D60"), 1))
                painter.setBrush(QColor(16, 20, 26, 235))
                painter.drawRoundedRect(QRectF(tt_x, tt_y, tt_w, tt_h), 4, 4)

                painter.setPen(QColor("#E2E8F0"))
                painter.drawText(QRectF(tt_x, tt_y, tt_w, tt_h), Qt.AlignCenter, tt_text)

        finally:
            painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        old_hover = self._hover_bin
        self._hover_bin = self._hit_test_bin(pos)
        self._hover_pos = pos
        if self._hover_bin != old_hover:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_bin is not None:
            self._hover_bin = None
            self._hover_pos = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            hit = self._hit_test_bin(event.position())
            if hit is not None:
                if self._selected_bin == hit:
                    self._selected_bin = None
                    self.bin_selected.emit(None)
                else:
                    self._selected_bin = hit
                    self.bin_selected.emit(hit)
                self.update()
        super().mousePressEvent(event)

    def _hit_test_bin(self, pos: QPointF) -> Optional[HistogramBin]:
        if not self._bins:
            return None

        w = self.width()
        h = self.height()
        pad_left = 38
        pad_right = 16
        pad_top = 22
        pad_bottom = 24

        plot_w = w - pad_left - pad_right
        plot_h = h - pad_top - pad_bottom

        if not (pad_left <= pos.x() <= pad_left + plot_w and pad_top <= pos.y() <= pad_top + plot_h):
            return None

        n_bins = len(self._bins)
        bar_gap = 2
        bar_w = max(2.0, (plot_w - (n_bins - 1) * bar_gap) / float(n_bins))

        rel_x = pos.x() - pad_left
        idx = int(rel_x / (bar_w + bar_gap))
        if 0 <= idx < n_bins:
            return self._bins[idx]
        return None


# ==============================================================================
# 1b. Slack vs. Logic Depth Scatter Plot Widget (Bubble Chart)
# ==============================================================================

class SlackScatterPlotWidget(QWidget):
    """Interactive 2D scatter plot plotting Slack vs. Logic Depth."""

    path_selected = Signal(object, bool)  # (TimingPath, zoom_bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._paths: List[TimingPath] = []
        self._hover_path: Optional[TimingPath] = None
        self._hover_pt: Optional[QPointF] = None
        self._selected_path: Optional[TimingPath] = None
        self.setMouseTracking(True)
        self.setMinimumHeight(120)

    def set_paths(self, paths: List[TimingPath]) -> None:
        self._paths = list(paths)
        self._hover_path = None
        self._hover_pt = None
        self.update()

    def set_selected_path(self, path: Optional[TimingPath]) -> None:
        self._selected_path = path
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            w = self.width()
            h = self.height()

            # Background & border
            painter.fillRect(0, 0, w, h, QColor("#16181D"))
            painter.setPen(QPen(QColor("#2B2E38"), 1))
            painter.drawRect(0, 0, w - 1, h - 1)

            if not self._paths:
                painter.setPen(QColor("#707888"))
                painter.setFont(QFont("Segoe UI", 9))
                painter.drawText(self.rect(), Qt.AlignCenter, "No Timing Paths Loaded")
                return

            pad_left = 44
            pad_right = 20
            pad_top = 22
            pad_bottom = 26

            plot_w = w - pad_left - pad_right
            plot_h = h - pad_top - pad_bottom
            if plot_w <= 20 or plot_h <= 20:
                return

            max_logic = max(max((p.logic_level for p in self._paths), default=10), 10)
            min_slack = min((p.slack for p in self._paths), default=-1.0)
            max_slack = max((p.slack for p in self._paths), default=1.0)
            slack_span = max(max_slack - min_slack, 0.2)
            slack_pad = slack_span * 0.1
            s_min = min_slack - slack_pad
            s_max = max_slack + slack_pad
            s_range = max(s_max - s_min, 1e-4)

            def to_screen(logic: int, slack: float) -> QPointF:
                sx = pad_left + (logic / float(max_logic)) * plot_w
                sy = pad_top + plot_h - ((slack - s_min) / float(s_range)) * plot_h
                return QPointF(sx, sy)

            grid_pen = QPen(QColor("#222630"), 1, Qt.DashLine)
            painter.setPen(grid_pen)
            painter.setFont(QFont("Segoe UI", 7))

            # Y-axis ticks
            num_y = 4
            for i in range(num_y + 1):
                y_val = s_min + (i / float(num_y)) * s_range
                sy = pad_top + plot_h - (i / float(num_y)) * plot_h
                painter.setPen(grid_pen)
                painter.drawLine(pad_left, int(sy), pad_left + plot_w, int(sy))
                painter.setPen(QColor("#707888"))
                painter.drawText(2, int(sy) + 3, f"{y_val:>5.2f}")

            # X-axis ticks
            num_x = 4
            for i in range(num_x + 1):
                x_val = int((i / float(num_x)) * max_logic)
                sx = pad_left + (i / float(num_x)) * plot_w
                painter.setPen(grid_pen)
                painter.drawLine(int(sx), pad_top, int(sx), pad_top + plot_h)
                painter.setPen(QColor("#707888"))
                painter.drawText(int(sx) - 8, h - 8, f"{x_val:>2}")

            # Zero-slack line
            if s_min <= 0.0 <= s_max:
                y0 = pad_top + plot_h - ((0.0 - s_min) / float(s_range)) * plot_h
                painter.setPen(QPen(QColor("#FF5252"), 1.2, Qt.DashLine))
                painter.drawLine(pad_left, int(y0), pad_left + plot_w, int(y0))

                # Quadrant helper watermark
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(QColor(255, 82, 82, 55))
                painter.drawText(pad_left + 8, int(min(y0 + 16, h - 35)), "Placement Bound")
                painter.drawText(pad_left + plot_w - 90, int(min(y0 + 16, h - 35)), "RTL Depth Bound")

            # Draw scatter points
            for p in self._paths:
                pt = to_screen(p.logic_level, p.slack)
                is_sel = (self._selected_path and self._selected_path.id == p.id)

                if p.slack < 0:
                    base_col = QColor("#FF5252")
                elif p.slack <= 0.15:
                    base_col = QColor("#FFB74D")
                else:
                    base_col = QColor("#66BB6A")

                radius = 3.5
                if p.sum_wire_length and p.sum_wire_length > 0:
                    radius = min(max(3.5 + (p.sum_wire_length / 2000.0), 3.5), 7.5)

                if is_sel:
                    painter.setPen(QPen(QColor("#FFE600"), 2))
                    painter.setBrush(base_col)
                    painter.drawEllipse(pt, radius + 2.0, radius + 2.0)
                else:
                    painter.setPen(QPen(QColor("#1A1D24"), 0.5))
                    painter.setBrush(base_col)
                    painter.drawEllipse(pt, radius, radius)

            # Hover crosshair and tooltip card
            if self._hover_path and self._hover_pt:
                hp = self._hover_path
                spt = to_screen(hp.logic_level, hp.slack)

                painter.setPen(QPen(QColor(0, 229, 255, 160), 1, Qt.DotLine))
                painter.drawLine(pad_left, int(spt.y()), pad_left + plot_w, int(spt.y()))
                painter.drawLine(int(spt.x()), pad_top, int(spt.x()), pad_top + plot_h)

                wire_str = f" | Wire: {hp.sum_wire_length:,.0f} µm" if hp.sum_wire_length else ""
                tt_text = f"Path {hp.id} | Slack: {hp.slack:+.4f} ns | Logic: {hp.logic_level}{wire_str}"
                fm = painter.fontMetrics()
                tt_w = fm.horizontalAdvance(tt_text) + 16
                tt_h = fm.height() + 8
                tt_x = min(max(spt.x() - tt_w / 2.0, 10.0), w - tt_w - 10.0)
                tt_y = max(spt.y() - tt_h - 10.0, 6.0)

                painter.setPen(QPen(QColor("#00E5FF"), 1))
                painter.setBrush(QColor(15, 20, 28, 240))
                painter.drawRoundedRect(QRectF(tt_x, tt_y, tt_w, tt_h), 4, 4)

                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRectF(tt_x, tt_y, tt_w, tt_h), Qt.AlignCenter, tt_text)

            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.setPen(QColor("#A0A8B8"))
            painter.drawText(pad_left, 14, "Slack (ns)")
            painter.drawText(pad_left + plot_w - 55, h - 8, "Logic Depth")
        finally:
            painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        old_hover = self._hover_path
        self._hover_path, self._hover_pt = self._hit_test(pos)
        if self._hover_path != old_hover:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_path is not None:
            self._hover_path = None
            self._hover_pt = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            hit, _ = self._hit_test(event.position())
            if hit is not None:
                self._selected_path = hit
                self.path_selected.emit(hit, False)
                self.update()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            hit, _ = self._hit_test(event.position())
            if hit is not None:
                self._selected_path = hit
                self.path_selected.emit(hit, True)
                self.update()
        super().mouseDoubleClickEvent(event)

    def _hit_test(self, pos: QPointF) -> Tuple[Optional[TimingPath], Optional[QPointF]]:
        if not self._paths:
            return None, None
        w = self.width()
        h = self.height()
        pad_left = 44
        pad_right = 20
        pad_top = 22
        pad_bottom = 26
        plot_w = w - pad_left - pad_right
        plot_h = h - pad_top - pad_bottom
        if plot_w <= 0 or plot_h <= 0:
            return None, None

        max_logic = max(max((p.logic_level for p in self._paths), default=10), 10)
        min_slack = min((p.slack for p in self._paths), default=-1.0)
        max_slack = max((p.slack for p in self._paths), default=1.0)
        slack_span = max(max_slack - min_slack, 0.2)
        slack_pad = slack_span * 0.1
        s_min = min_slack - slack_pad
        s_range = max(max_slack + slack_pad - s_min, 1e-4)

        best_p = None
        best_dist = 12.0
        best_pt = None

        for p in self._paths:
            sx = pad_left + (p.logic_level / float(max_logic)) * plot_w
            sy = pad_top + plot_h - ((p.slack - s_min) / float(s_range)) * plot_h
            d = math.hypot(pos.x() - sx, pos.y() - sy)
            if d < best_dist:
                best_dist = d
                best_p = p
                best_pt = QPointF(sx, sy)

        return best_p, best_pt


# ==============================================================================
# 1c. Critical Endpoint Pareto Chart (Top Violators Bar Chart)
# ==============================================================================

class EndpointParetoWidget(QWidget):
    """Horizontal ranked bar chart showing Top Bottleneck Endpoints by WNS."""

    endpoint_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._endpoints: List[Dict[str, Any]] = []
        self._hover_idx: int = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(120)

    def set_paths(self, paths: List[TimingPath]) -> None:
        ep_map: Dict[str, Dict[str, Any]] = {}
        for p in paths:
            ep = p.endpoint or "Unknown"
            leaf = ep.rsplit("/", 1)[-1]
            if leaf not in ep_map:
                ep_map[leaf] = {"name": leaf, "full_name": ep, "count": 0, "failing": 0, "wns": 999.0}
            ep_map[leaf]["count"] += 1
            if p.slack < 0:
                ep_map[leaf]["failing"] += 1
            if p.slack < ep_map[leaf]["wns"]:
                ep_map[leaf]["wns"] = p.slack

        sorted_eps = sorted(ep_map.values(), key=lambda e: (e["wns"], -e["count"]))
        self._endpoints = sorted_eps[:10]
        self._hover_idx = -1
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            w = self.width()
            h = self.height()
            painter.fillRect(0, 0, w, h, QColor("#16181D"))
            painter.setPen(QPen(QColor("#2B2E38"), 1))
            painter.drawRect(0, 0, w - 1, h - 1)

            if not self._endpoints:
                painter.setPen(QColor("#707888"))
                painter.setFont(QFont("Segoe UI", 9))
                painter.drawText(self.rect(), Qt.AlignCenter, "No Endpoint Data")
                return

            pad_left = 130
            pad_right = 100
            pad_top = 18
            pad_bottom = 10

            plot_w = w - pad_left - pad_right
            n = len(self._endpoints)
            row_h = max(min((h - pad_top - pad_bottom) / float(n), 20.0), 11.0)
            bar_h = max(row_h - 4.0, 5.0)

            max_mag = max(max(abs(e["wns"]) for e in self._endpoints), 0.1)

            painter.setFont(QFont("Segoe UI", 7))
            for i, e in enumerate(self._endpoints):
                y = pad_top + i * row_h
                is_hover = (i == self._hover_idx)

                painter.setPen(QColor("#FFFFFF" if is_hover else "#A0A8B8"))
                label_rect = QRectF(6, y, pad_left - 12, row_h)
                painter.drawText(label_rect, Qt.AlignRight | Qt.AlignVCenter, e["name"][:18])

                mag = abs(e["wns"])
                bar_len = (mag / float(max_mag)) * plot_w
                bar_rect = QRectF(pad_left, y + 2, bar_len, bar_h)

                if e["wns"] < 0:
                    grad = QLinearGradient(pad_left, y, pad_left + bar_len, y)
                    grad.setColorAt(0.0, QColor("#D32F2F"))
                    grad.setColorAt(1.0, QColor("#EF5350"))
                    painter.setBrush(grad)
                else:
                    painter.setBrush(QColor("#43A047"))

                painter.setPen(QPen(QColor("#00E5FF" if is_hover else "#2B2E38"), 1))
                painter.drawRoundedRect(bar_rect, 2, 2)

                val_str = f"{e['wns']:+.3f} ns [{e['count']}p]"
                painter.setPen(QColor("#E2E8F0"))
                painter.drawText(QRectF(pad_left + bar_len + 6, y, pad_right - 10, row_h), Qt.AlignLeft | Qt.AlignVCenter, val_str)

        finally:
            painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        idx = self._hit_test_row(event.position().y())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            idx = self._hit_test_row(event.position().y())
            if 0 <= idx < len(self._endpoints):
                self.endpoint_selected.emit(self._endpoints[idx]["name"])
        super().mousePressEvent(event)

    def _hit_test_row(self, y: float) -> int:
        if not self._endpoints:
            return -1
        pad_top = 18
        pad_bottom = 10
        n = len(self._endpoints)
        row_h = max(min((self.height() - pad_top - pad_bottom) / float(n), 20.0), 11.0)
        idx = int((y - pad_top) / row_h)
        if 0 <= idx < n:
            return idx
        return -1


# ==============================================================================
# 1d. Clock Domain Crossing (CDC) Matrix Widget
# ==============================================================================

class ClockMatrixWidget(QWidget):
    """Interactive Launch Clock vs Capture Clock Crossing (CDC) Matrix."""

    clock_pair_selected = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._matrix: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._launch_clks: List[str] = []
        self._capture_clks: List[str] = []
        self._hover_cell: Optional[Tuple[int, int]] = None
        self.setMouseTracking(True)
        self.setMinimumHeight(120)

    def set_paths(self, paths: List[TimingPath]) -> None:
        l_set = set()
        c_set = set()
        matrix: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for p in paths:
            l = p.launch_clock or "clk_in"
            c = p.capture_clock or "clk_out"
            l_set.add(l)
            c_set.add(c)
            key = (l, c)
            if key not in matrix:
                matrix[key] = {"launch": l, "capture": c, "count": 0, "failing": 0, "wns": 999.0}
            matrix[key]["count"] += 1
            if p.slack < 0:
                matrix[key]["failing"] += 1
            if p.slack < matrix[key]["wns"]:
                matrix[key]["wns"] = p.slack

        self._launch_clks = sorted(list(l_set))[:5]
        self._capture_clks = sorted(list(c_set))[:5]
        self._matrix = matrix
        self._hover_cell = None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            w = self.width()
            h = self.height()
            painter.fillRect(0, 0, w, h, QColor("#16181D"))
            painter.setPen(QPen(QColor("#2B2E38"), 1))
            painter.drawRect(0, 0, w - 1, h - 1)

            if not self._launch_clks or not self._capture_clks:
                painter.setPen(QColor("#707888"))
                painter.setFont(QFont("Segoe UI", 9))
                painter.drawText(self.rect(), Qt.AlignCenter, "No Clock Domains Detected")
                return

            pad_left = 90
            pad_top = 28
            n_rows = len(self._launch_clks)
            n_cols = len(self._capture_clks)

            cell_w = max((w - pad_left - 10) / float(n_cols), 45.0)
            cell_h = max((h - pad_top - 10) / float(n_rows), 18.0)

            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.setPen(QColor("#A0A8B8"))
            for j, c in enumerate(self._capture_clks):
                cx = pad_left + j * cell_w
                painter.drawText(QRectF(cx, 8, cell_w, 18), Qt.AlignCenter, c[:10])

            for i, l in enumerate(self._launch_clks):
                ry = pad_top + i * cell_h
                painter.setPen(QColor("#A0A8B8"))
                painter.drawText(QRectF(6, ry, pad_left - 10, cell_h), Qt.AlignRight | Qt.AlignVCenter, l[:12])

                for j, c in enumerate(self._capture_clks):
                    cx = pad_left + j * cell_w
                    cell_rect = QRectF(cx + 1, ry + 1, cell_w - 2, cell_h - 2)
                    entry = self._matrix.get((l, c))
                    is_hover = (self._hover_cell == (i, j))

                    if entry:
                        if entry["failing"] > 0:
                            bg = QColor("#5A1818") if not is_hover else QColor("#802424")
                            text_col = QColor("#FF8A80")
                        else:
                            bg = QColor("#17381E") if not is_hover else QColor("#22522C")
                            text_col = QColor("#81C784")
                        painter.fillRect(cell_rect, bg)
                        painter.setPen(QPen(QColor("#00E5FF" if is_hover else "#2B2E38"), 1))
                        painter.drawRect(cell_rect)

                        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                        painter.setPen(text_col)
                        txt = f"{entry['count']}p | {entry['wns']:+.2f}"
                        painter.drawText(cell_rect, Qt.AlignCenter, txt)
                    else:
                        painter.fillRect(cell_rect, QColor("#1C1F26"))
                        painter.setPen(QPen(QColor("#2B2E38"), 1))
                        painter.drawRect(cell_rect)

        finally:
            painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cell = self._hit_test_cell(event.position())
        if cell != self._hover_cell:
            self._hover_cell = cell
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_cell is not None:
            self._hover_cell = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            cell = self._hit_test_cell(event.position())
            if cell:
                i, j = cell
                if 0 <= i < len(self._launch_clks) and 0 <= j < len(self._capture_clks):
                    self.clock_pair_selected.emit(self._launch_clks[i], self._capture_clks[j])
        super().mousePressEvent(event)

    def _hit_test_cell(self, pos: QPointF) -> Optional[Tuple[int, int]]:
        pad_left = 90
        pad_top = 28
        if pos.x() < pad_left or pos.y() < pad_top:
            return None
        n_rows = len(self._launch_clks)
        n_cols = len(self._capture_clks)
        if n_rows == 0 or n_cols == 0:
            return None
        cell_w = max((self.width() - pad_left - 10) / float(n_cols), 45.0)
        cell_h = max((self.height() - pad_top - 10) / float(n_rows), 18.0)
        j = int((pos.x() - pad_left) / cell_w)
        i = int((pos.y() - pad_top) / cell_h)
        if 0 <= i < n_rows and 0 <= j < n_cols:
            return (i, j)
        return None


# ==============================================================================
# 1e. Selected Path Delay Waterfall Inspector Widget
# ==============================================================================

class PathDelayWaterfallWidget(QWidget):
    """Horizontal stacked delay waterfall timeline for the selected timing path."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._path: Optional[TimingPath] = None
        self.setFixedHeight(28)

    def set_path(self, path: Optional[TimingPath]) -> None:
        self._path = path
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            w = self.width()
            h = self.height()
            painter.fillRect(0, 0, w, h, QColor("#181B22"))
            painter.setPen(QPen(QColor("#2B2E38"), 1))
            painter.drawRect(0, 0, w - 1, h - 1)

            if self._path is None:
                painter.setPen(QColor("#707888"))
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.drawText(self.rect(), Qt.AlignCenter, "Select a path in table to inspect Gate vs. Wire Delay Waterfall")
                return

            p = self._path
            total_delay = max(p.arrival_time, 0.05)
            est_cell_delay = min(p.logic_level * 0.045, total_delay * 0.75) if p.logic_level > 0 else total_delay * 0.4
            est_wire_delay = max(total_delay - est_cell_delay, 0.01)
            cell_pct = int((est_cell_delay / total_delay) * 100)
            wire_pct = 100 - cell_pct

            pad_x = 6
            pad_y = 5
            bar_w = w - 2 * pad_x
            bar_h = h - 2 * pad_y

            cell_w = (cell_pct / 100.0) * bar_w
            wire_w = bar_w - cell_w

            # Cell delay segment (Purple)
            painter.fillRect(QRectF(pad_x, pad_y, cell_w, bar_h), QColor("#7C4DFF"))
            # Wire delay segment (Orange)
            painter.fillRect(QRectF(pad_x + cell_w, pad_y, wire_w, bar_h), QColor("#FF9100"))

            painter.setPen(QPen(QColor("#1A1D24"), 1))
            painter.drawRect(QRectF(pad_x, pad_y, bar_w, bar_h))

            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.setPen(QColor("#FFFFFF"))
            if cell_w > 90:
                painter.drawText(QRectF(pad_x + 6, pad_y, cell_w - 12, bar_h), Qt.AlignLeft | Qt.AlignVCenter, f"Gate Delay: {cell_pct}% ({est_cell_delay:.2f}ns)")
            if wire_w > 90:
                painter.drawText(QRectF(pad_x + cell_w + 6, pad_y, wire_w - 12, bar_h), Qt.AlignLeft | Qt.AlignVCenter, f"Wire Delay: {wire_pct}% ({est_wire_delay:.2f}ns)")

        finally:
            painter.end()


# ==============================================================================
# 2. Category Summary Table
# ==============================================================================

class CategorySummaryWidget(QWidget):
    """Card displaying aggregated statistics (WNS, TNS, passing/failing paths)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._table = QTableWidget(8, 2)
        self._table.setHorizontalHeaderLabels(["Metric", "Value"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 110)
        self._table.setColumnWidth(1, 140)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setShowGrid(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1A1D24;
                color: #D6DCE5;
                gridline-color: #282C37;
                border: 1px solid #282C37;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QHeaderView::section {
                background-color: #232732;
                color: #A0A8B8;
                font-weight: bold;
                border: 1px solid #282C37;
                padding: 2px 4px;
            }
        """)

        metrics = [
            "Name", "Total Path", "Passing Path", "Failing Path",
            "WNS Mean", "WNS Sigma", "Percentile", "TNS"
        ]
        for row, name in enumerate(metrics):
            item_name = QTableWidgetItem(name)
            item_name.setFont(QFont("Segoe UI", 8, QFont.Bold))
            item_val = QTableWidgetItem("-")
            self._table.setItem(row, 0, item_name)
            self._table.setItem(row, 1, item_val)
            self._table.setRowHeight(row, 18)

        layout.addWidget(self._table)

    def set_stats(self, stats: Optional[CategoryStats]) -> None:
        if stats is None:
            for r in range(8):
                self._table.item(r, 1).setText("-")
            return

        values = [
            stats.name,
            f"{stats.total_path:,}",
            f"{stats.passing_path:,}",
            f"{stats.failing_path:,}",
            f"{stats.wns_mean:+.4f} ns",
            f"{stats.wns_sigma:.4f}",
            f"{stats.percentile:.1f}%",
            f"{stats.tns:+.4f} ns",
        ]

        for row, val_str in enumerate(values):
            item = self._table.item(row, 1)
            item.setText(val_str)
            # Highlight failing slacks in red, passing in green
            if row == 2 and stats.passing_path > 0:
                item.setForeground(QColor("#81C784"))
            elif row == 3 and stats.failing_path > 0:
                item.setForeground(QColor("#E57373"))
            elif row in (4, 7) and ("-" in val_str and val_str != "-"):
                item.setForeground(QColor("#E57373"))
            elif row in (4, 7):
                item.setForeground(QColor("#81C784"))
            else:
                item.setForeground(QColor("#D6DCE5"))


# ==============================================================================
# 3. Path Category Table
# ==============================================================================

class PathCategoryTable(QWidget):
    """Table listing groups (all, reg2reg, etc.) and category statistics."""

    category_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._table = QTableWidget()
        headers = [
            "Cate", "H", "Category Name", "Correction",
            "WNS Mean", "WNS Sigma", "TNS", "#Failing Path"
        ]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1A1D24;
                color: #D6DCE5;
                gridline-color: #282C37;
                border: 1px solid #282C37;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QHeaderView::section {
                background-color: #232732;
                color: #A0A8B8;
                font-weight: bold;
                border: 1px solid #282C37;
                padding: 2px 4px;
            }
            QTableWidget::item:selected {
                background-color: #1E3A5F;
                color: #FFFFFF;
            }
        """)

        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        cat_widths = {0: 45, 1: 30, 2: 130, 3: 75, 4: 85, 5: 80, 6: 85, 7: 90}
        for col, w in cat_widths.items():
            self._table.setColumnWidth(col, w)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

    def set_categories(self, categories: Dict[str, CategoryStats]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(categories))

        for row, (name, stats) in enumerate(categories.items()):
            # Cate index
            it_idx = QTableWidgetItem(str(row + 1))
            it_idx.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 0, it_idx)

            # H Checkbox indicator
            it_h = QTableWidgetItem()
            it_h.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_h.setCheckState(Qt.Unchecked)
            self._table.setItem(row, 1, it_h)

            # Category Name
            it_name = QTableWidgetItem(stats.name)
            self._table.setItem(row, 2, it_name)

            # Correction
            it_corr = QTableWidgetItem("-")
            it_corr.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 3, it_corr)

            # WNS Mean
            it_wns = QTableWidgetItem(f"{stats.wns_mean:+.4f}")
            it_wns.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if stats.wns_mean < 0:
                it_wns.setForeground(QColor("#E57373"))
            self._table.setItem(row, 4, it_wns)

            # WNS Sigma
            it_sig = QTableWidgetItem(f"{stats.wns_sigma:.4f}")
            it_sig.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 5, it_sig)

            # TNS
            it_tns = QTableWidgetItem(f"{stats.tns:+.4f}")
            it_tns.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if stats.tns < 0:
                it_tns.setForeground(QColor("#E57373"))
            self._table.setItem(row, 6, it_tns)

            # Failing Path Count
            it_fail = QTableWidgetItem(str(stats.failing_path))
            it_fail.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if stats.failing_path > 0:
                it_fail.setForeground(QColor("#E57373"))
            self._table.setItem(row, 7, it_fail)

            self._table.setRowHeight(row, 18)

        self._table.blockSignals(False)

    def _on_selection_changed(self) -> None:
        sel = self._table.selectedItems()
        if not sel:
            self.category_selected.emit("all")
            return
        row = sel[0].row()
        name_item = self._table.item(row, 2)
        if name_item:
            self.category_selected.emit(name_item.text())


# ==============================================================================
# 4. Optimization Failure Reason Table
# ==============================================================================

class OptimizationFailureReasonTable(QWidget):
    """Table summarizing violation reasons and path counts."""

    reason_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._table = QTableWidget()
        headers = ["Cate", "H", "Failure Reason", "Count", "WNS"]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1A1D24;
                color: #D6DCE5;
                gridline-color: #282C37;
                border: 1px solid #282C37;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QHeaderView::section {
                background-color: #232732;
                color: #A0A8B8;
                font-weight: bold;
                border: 1px solid #282C37;
                padding: 2px 4px;
            }
            QTableWidget::item:selected {
                background-color: #1E3A5F;
                color: #FFFFFF;
            }
        """)

        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        reason_widths = {0: 45, 1: 30, 2: 200, 3: 75, 4: 85}
        for col, w in reason_widths.items():
            self._table.setColumnWidth(col, w)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

    def set_reasons(self, reasons: List[Dict[str, Any]]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(reasons))

        for row, entry in enumerate(reasons):
            it_idx = QTableWidgetItem(str(row + 1))
            it_idx.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 0, it_idx)

            it_h = QTableWidgetItem()
            it_h.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_h.setCheckState(Qt.Unchecked)
            self._table.setItem(row, 1, it_h)

            it_reason = QTableWidgetItem(str(entry.get("reason", "Violation")))
            self._table.setItem(row, 2, it_reason)

            it_count = QTableWidgetItem(str(entry.get("count", 0)))
            it_count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 3, it_count)

            wns = entry.get("wns", 0.0)
            it_wns = QTableWidgetItem(f"{wns:+.4f}")
            it_wns.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if wns < 0:
                it_wns.setForeground(QColor("#E57373"))
            self._table.setItem(row, 4, it_wns)

            self._table.setRowHeight(row, 18)

        self._table.blockSignals(False)

    def _on_selection_changed(self) -> None:
        sel = self._table.selectedItems()
        if not sel:
            self.reason_selected.emit("")
            return
        row = sel[0].row()
        item = self._table.item(row, 2)
        if item:
            self.reason_selected.emit(item.text())


# ==============================================================================
# 5. Path List Table (Main Table with Pagination & 11 Columns)
# ==============================================================================

class CopyableTableWidget(QTableWidget):
    """QTableWidget supporting Ctrl+C copy of selected cells to clipboard."""

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copy_selection_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self) -> None:
        sel = self.selectedItems()
        if not sel:
            return
        rows: Dict[int, Dict[int, str]] = {}
        for it in sel:
            r, c = it.row(), it.column()
            if r not in rows:
                rows[r] = {}
            rows[r][c] = it.text()
        lines = []
        for r in sorted(rows.keys()):
            cols = [rows[r][c] for c in sorted(rows[r].keys())]
            lines.append("\t".join(cols))
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)


class PathListTable(QWidget):
    """Sortable, paginated table listing timing paths with all 11 columns."""

    path_selected = Signal(object, bool)  # (TimingPath, zoom_bool)
    paths_highlighted = Signal(list)     # List[TimingPath]
    paths_cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._paths: List[TimingPath] = []
        self._page_size: int = 50
        self._page_index: int = 0
        self._highlighted_ids: set[int] = set()
        self._is_refreshing: bool = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        # 11 columns matching Cadence GUI in reportTimingWidget.png:
        # H, Path, Clock, ReqTime, Slack, Logic Level, Sum of Wire Length,
        # Startpoint Pin, Endpoint Pin, View, Failure Reason
        self._headers = [
            "H", "Path", "Clock", "ReqTime", "Slack",
            "Logic Level", "Sum of Wire Length", "Startpoint Pin",
            "Endpoint Pin", "View", "Failure Reason"
        ]

        self._table = CopyableTableWidget()
        self._table.setColumnCount(len(self._headers))
        self._table.setHorizontalHeaderLabels(self._headers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(False)  # Managed custom sorting for pagination
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1A1D24;
                color: #D6DCE5;
                gridline-color: #282C37;
                border: 1px solid #282C37;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QHeaderView::section {
                background-color: #232732;
                color: #A0A8B8;
                font-weight: bold;
                border: 1px solid #282C37;
                padding: 3px 6px;
            }
            QTableWidget::item:selected {
                background-color: #1E3A5F;
                color: #FFFFFF;
            }
        """)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        col_widths = {
            0: 32,   # H
            1: 55,   # Path
            2: 100,  # Clock
            3: 80,   # ReqTime
            4: 80,   # Slack
            5: 75,   # Logic Level
            6: 130,  # Sum of Wire Length
            7: 280,  # Startpoint Pin
            8: 280,  # Endpoint Pin
            9: 90,   # View
            10: 160, # Failure Reason
        }
        for col, w in col_widths.items():
            self._table.setColumnWidth(col, w)
        header.sectionClicked.connect(self._on_header_clicked)

        self._table.itemClicked.connect(self._on_item_clicked)
        self._table.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        self._layout.addWidget(self._table)

        # Pagination & Zoom Toolbar
        self._create_pagination_bar()

    def _create_pagination_bar(self) -> None:
        bar = QFrame()
        bar.setStyleSheet("background-color: #1E222B; border: 1px solid #2B2F3B; border-radius: 3px;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(6, 2, 6, 2)
        bar_layout.setSpacing(6)

        # Zoom navigation buttons
        zoom_label = QLabel("Zoom to Highlighted Path:")
        zoom_label.setStyleSheet("color: #A0A8B8; font-size: 8pt; font-weight: bold;")
        bar_layout.addWidget(zoom_label)

        self._btn_zoom_prev = QPushButton("<")
        self._btn_zoom_prev.setFixedSize(24, 20)
        self._btn_zoom_prev.setToolTip("Previous highlighted path")
        self._btn_zoom_prev.clicked.connect(self._zoom_prev_highlighted)
        bar_layout.addWidget(self._btn_zoom_prev)

        self._btn_zoom_next = QPushButton(">")
        self._btn_zoom_next.setFixedSize(24, 20)
        self._btn_zoom_next.setToolTip("Next highlighted path")
        self._btn_zoom_next.clicked.connect(self._zoom_next_highlighted)
        bar_layout.addWidget(self._btn_zoom_next)

        bar_layout.addSpacing(16)

        # Select all / Clear highlights
        btn_sel_all = QPushButton("Select All H")
        btn_sel_all.setFixedHeight(20)
        btn_sel_all.setStyleSheet("font-size: 7pt;")
        btn_sel_all.clicked.connect(self.select_all_highlights)
        bar_layout.addWidget(btn_sel_all)

        btn_clr_all = QPushButton("Clear All Highlights")
        btn_clr_all.setFixedHeight(20)
        btn_clr_all.setStyleSheet(
            "font-size: 7pt; font-weight: bold; background-color: #3A2328; color: #FF8A80; border: 1px solid #5C2D35; border-radius: 2px; padding: 0 4px;"
        )
        btn_clr_all.setToolTip("Clear all selected and highlighted timing paths")
        btn_clr_all.clicked.connect(self.clear_all_highlights)
        bar_layout.addWidget(btn_clr_all)

        bar_layout.addStretch()

        # Page size combobox
        page_size_lbl = QLabel("Rows:")
        page_size_lbl.setStyleSheet("color: #A0A8B8; font-size: 8pt;")
        bar_layout.addWidget(page_size_lbl)

        self._combo_page_size = QComboBox()
        self._combo_page_size.addItems(["50", "100", "200", "All"])
        self._combo_page_size.setFixedHeight(20)
        self._combo_page_size.setStyleSheet("font-size: 8pt;")
        self._combo_page_size.currentTextChanged.connect(self._on_page_size_changed)
        bar_layout.addWidget(self._combo_page_size)

        # Pagination controls
        self._btn_first = QPushButton("|<")
        self._btn_first.setFixedSize(24, 20)
        self._btn_first.clicked.connect(self._go_first_page)
        bar_layout.addWidget(self._btn_first)

        self._btn_prev = QPushButton("<")
        self._btn_prev.setFixedSize(24, 20)
        self._btn_prev.clicked.connect(self._go_prev_page)
        bar_layout.addWidget(self._btn_prev)

        self._lbl_page = QLabel("Page 1 of 1")
        self._lbl_page.setStyleSheet("color: #E2E8F0; font-size: 8pt; font-weight: bold;")
        bar_layout.addWidget(self._lbl_page)

        self._btn_next = QPushButton(">")
        self._btn_next.setFixedSize(24, 20)
        self._btn_next.clicked.connect(self._go_next_page)
        bar_layout.addWidget(self._btn_next)

        self._btn_last = QPushButton(">|")
        self._btn_last.setFixedSize(24, 20)
        self._btn_last.clicked.connect(self._go_last_page)
        bar_layout.addWidget(self._btn_last)

        self._layout.addWidget(bar)

    def set_paths(self, paths: List[TimingPath]) -> None:
        self._paths = paths
        self._page_index = 0
        self._refresh_page()

    def _get_path_at_row(self, row: int) -> Optional[TimingPath]:
        pid_item = self._table.item(row, 1)
        if pid_item:
            try:
                pid = int(pid_item.text())
                return next((p for p in self._paths if p.id == pid), None)
            except ValueError:
                pass
        return None

    def get_selected_path(self) -> Optional[TimingPath]:
        sel = self._table.selectedItems()
        if not sel:
            return None
        return self._get_path_at_row(sel[0].row())

    def _on_table_context_menu(self, pos: Any) -> None:
        item = self._table.itemAt(pos)
        if not item:
            return
        row = item.row()
        path = self._get_path_at_row(row)
        menu = QMenu(self)

        cell_text = item.text()
        trunc_cell = (cell_text[:35] + "...") if len(cell_text) > 35 else cell_text
        act_copy_cell = menu.addAction(f"Copy Cell Text (\"{trunc_cell}\")")
        act_copy_cell.triggered.connect(lambda: QApplication.clipboard().setText(cell_text))

        if path:
            s_pin = path.startpoint
            trunc_s = (s_pin[:35] + "...") if len(s_pin) > 35 else s_pin
            act_copy_start = menu.addAction(f"Copy Startpoint Pin (\"{trunc_s}\")")
            act_copy_start.triggered.connect(lambda: QApplication.clipboard().setText(s_pin))

            e_pin = path.endpoint
            trunc_e = (e_pin[:35] + "...") if len(e_pin) > 35 else e_pin
            act_copy_end = menu.addAction(f"Copy Endpoint Pin (\"{trunc_e}\")")
            act_copy_end.triggered.connect(lambda: QApplication.clipboard().setText(e_pin))

            menu.addSeparator()
            act_copy_row = menu.addAction("Copy Full Path Info (TSV)")
            wl_text = f"{path.sum_wire_length:,.2f} µm" if path.sum_wire_length is not None else "-"
            row_vals = [
                str(path.id), path.launch_clock, f"{path.required_time:.4f}",
                f"{path.slack:+.4f}", str(path.logic_level), wl_text,
                path.startpoint, path.endpoint, path.view, path.failure_reason
            ]
            act_copy_row.triggered.connect(lambda: QApplication.clipboard().setText("\t".join(row_vals)))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _refresh_page(self) -> None:
        self._is_refreshing = True
        self._table.blockSignals(True)
        try:
            total_items = len(self._paths)

            if self._page_size <= 0:
                start_idx = 0
                end_idx = total_items
                num_pages = 1
            else:
                num_pages = max(1, math.ceil(total_items / float(self._page_size)))
                self._page_index = max(0, min(self._page_index, num_pages - 1))
                start_idx = self._page_index * self._page_size
                end_idx = min(start_idx + self._page_size, total_items)

            current_slice = self._paths[start_idx:end_idx]
            self._table.setRowCount(len(current_slice))

            for row, p in enumerate(current_slice):
                # 0: H Checkbox
                it_h = QTableWidgetItem()
                it_h.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk = Qt.Checked if p.id in self._highlighted_ids else Qt.Unchecked
                it_h.setCheckState(chk)
                it_h.setToolTip("Toggle path highlight on layout canvas")
                self._table.setItem(row, 0, it_h)

                # 1: Path ID
                it_id = QTableWidgetItem(str(p.id))
                it_id.setTextAlignment(Qt.AlignCenter)
                it_id.setToolTip(f"Path ID: {p.id}")
                self._table.setItem(row, 1, it_id)

                # 2: Clock
                it_clk = QTableWidgetItem(p.launch_clock)
                it_clk.setToolTip(f"Launch Clock: {p.launch_clock}\nCapture Clock: {p.capture_clock}")
                self._table.setItem(row, 2, it_clk)

                # 3: ReqTime
                it_req = QTableWidgetItem(f"{p.required_time:.4f}")
                it_req.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_req.setToolTip(f"Required Time: {p.required_time:.4f} ns")
                self._table.setItem(row, 3, it_req)

                # 4: Slack (colored red if < 0, green if >= 0)
                it_slack = QTableWidgetItem(f"{p.slack:+.4f}")
                it_slack.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_slack.setFont(QFont("Segoe UI", 8, QFont.Bold))
                if p.slack < 0.0:
                    it_slack.setForeground(QColor("#FF5252"))
                else:
                    it_slack.setForeground(QColor("#66BB6A"))
                it_slack.setToolTip(f"Slack: {p.slack:+.4f} ns\nRequired: {p.required_time:.4f} ns\nArrival: {p.arrival_time:.4f} ns")
                self._table.setItem(row, 4, it_slack)

                # 5: Logic Level
                it_level = QTableWidgetItem(str(p.logic_level))
                it_level.setTextAlignment(Qt.AlignCenter)
                it_level.setToolTip(f"Logic Levels: {p.logic_level}")
                self._table.setItem(row, 5, it_level)

                # 6: Sum of Wire Length
                if p.sum_wire_length is not None:
                    wl_str = f"{p.sum_wire_length:,.2f} µm"
                else:
                    wl_str = "-"
                it_wl = QTableWidgetItem(wl_str)
                it_wl.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it_wl.setToolTip(f"Estimated / Routed Wire Length: {wl_str}")
                self._table.setItem(row, 6, it_wl)

                # 7: Startpoint Pin
                it_start = QTableWidgetItem(p.startpoint)
                it_start.setToolTip(p.startpoint)
                self._table.setItem(row, 7, it_start)

                # 8: Endpoint Pin
                it_end = QTableWidgetItem(p.endpoint)
                it_end.setToolTip(p.endpoint)
                self._table.setItem(row, 8, it_end)

                # 9: View
                it_view = QTableWidgetItem(p.view)
                it_view.setToolTip(f"View: {p.view}")
                self._table.setItem(row, 9, it_view)

                # 10: Failure Reason
                it_reason = QTableWidgetItem(p.failure_reason or p.status)
                it_reason.setToolTip(p.failure_reason or p.status)
                self._table.setItem(row, 10, it_reason)

                self._table.setRowHeight(row, 18)

            self._lbl_page.setText(f"Page {self._page_index + 1} of {num_pages} ({total_items:,} paths)")
            self._btn_first.setEnabled(self._page_index > 0)
            self._btn_prev.setEnabled(self._page_index > 0)
            self._btn_next.setEnabled(self._page_index < num_pages - 1)
            self._btn_last.setEnabled(self._page_index < num_pages - 1)
        finally:
            self._table.blockSignals(False)
            self._is_refreshing = False

    def _on_selection_changed(self) -> None:
        if self._is_refreshing or self._table.signalsBlocked():
            return
        path = self.get_selected_path()
        if path:
            self.path_selected.emit(path, False)

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            return  # Handled by itemChanged for checkbox
        row = item.row()
        pid_item = self._table.item(row, 1)
        if pid_item:
            pid = int(pid_item.text())
            path = next((p for p in self._paths if p.id == pid), None)
            if path:
                self.path_selected.emit(path, False)

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        pid_item = self._table.item(row, 1)
        if pid_item:
            pid = int(pid_item.text())
            path = next((p for p in self._paths if p.id == pid), None)
            if path:
                self.path_selected.emit(path, True)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._is_refreshing:
            return
        if item.column() == 0:
            row = item.row()
            pid_item = self._table.item(row, 1)
            if pid_item:
                pid = int(pid_item.text())
                if item.checkState() == Qt.Checked:
                    self._highlighted_ids.add(pid)
                else:
                    self._highlighted_ids.discard(pid)
                self._emit_highlights()

    def _emit_highlights(self) -> None:
        highlighted = [p for p in self._paths if p.id in self._highlighted_ids]
        self.paths_highlighted.emit(highlighted)

    def select_all_highlights(self) -> None:
        for p in self._paths:
            self._highlighted_ids.add(p.id)
        self._refresh_page()
        self._emit_highlights()

    def clear_all_highlights(self) -> None:
        self._highlighted_ids.clear()
        self._is_refreshing = True
        self._table.blockSignals(True)
        self._table.clearSelection()
        self._table.blockSignals(False)
        self._is_refreshing = False
        self._refresh_page()
        self.paths_highlighted.emit([])
        self.path_selected.emit(None, False)
        self.paths_cleared.emit()

    def _zoom_next_highlighted(self) -> None:
        if not self._highlighted_ids:
            return
        sorted_ids = sorted(self._highlighted_ids)
        cur = self.get_selected_path()
        cur_id = cur.id if cur else -1
        next_id = next((pid for pid in sorted_ids if pid > cur_id), sorted_ids[0])
        path = next((p for p in self._paths if p.id == next_id), None)
        if path:
            self.path_selected.emit(path, True)

    def _zoom_prev_highlighted(self) -> None:
        if not self._highlighted_ids:
            return
        sorted_ids = sorted(self._highlighted_ids, reverse=True)
        cur = self.get_selected_path()
        cur_id = cur.id if cur else 999999
        prev_id = next((pid for pid in sorted_ids if pid < cur_id), sorted_ids[0])
        path = next((p for p in self._paths if p.id == prev_id), None)
        if path:
            self.path_selected.emit(path, True)

    def _on_header_clicked(self, logical_index: int) -> None:
        # Sort paths by clicked column
        if logical_index == 1:  # Path ID
            self._paths.sort(key=lambda p: p.id)
        elif logical_index == 3:  # ReqTime
            self._paths.sort(key=lambda p: p.required_time)
        elif logical_index == 4:  # Slack (worst to best)
            self._paths.sort(key=lambda p: p.slack)
        elif logical_index == 5:  # Logic Level
            self._paths.sort(key=lambda p: p.logic_level, reverse=True)
        elif logical_index == 6:  # Wire length
            self._paths.sort(key=lambda p: (p.sum_wire_length or 0.0), reverse=True)
        elif logical_index == 7:  # Startpoint
            self._paths.sort(key=lambda p: p.startpoint)
        elif logical_index == 8:  # Endpoint
            self._paths.sort(key=lambda p: p.endpoint)
        self._refresh_page()

    def _on_page_size_changed(self, text: str) -> None:
        if text == "All":
            self._page_size = 0
        else:
            self._page_size = int(text)
        self._page_index = 0
        self._refresh_page()

    def _go_first_page(self) -> None:
        self._page_index = 0
        self._refresh_page()

    def _go_prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._refresh_page()

    def _go_next_page(self) -> None:
        self._page_index += 1
        self._refresh_page()

    def _go_last_page(self) -> None:
        total_items = len(self._paths)
        if self._page_size > 0:
            self._page_index = max(0, math.ceil(total_items / float(self._page_size)) - 1)
        self._refresh_page()


# ==============================================================================
# 6. Complete Timing Report Widget
# ==============================================================================

class TimingReportWidget(QWidget):
    """Integrated EDA timing debugger panel matching reportTimingWidget.png."""

    path_selected = Signal(object, bool)  # (TimingPath, zoom_bool)
    paths_highlighted = Signal(list)     # List[TimingPath]
    paths_cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._report_data: Optional[TimingReportData] = None
        self._chip: Any = None
        self._layout_viewer: Any = None
        self._parser = TarptParser()

        self._active_category: str = "all"
        self._active_slack_range: Optional[Tuple[float, float]] = None
        self._active_reason: str = ""
        self._active_search: str = ""

        self._setup_ui()

    def setLayoutViewer(self, viewer: Any) -> None:
        """Stores reference to LayoutViewer to reuse pre-indexed alias maps."""
        self._layout_viewer = viewer
        if self._report_data is not None and hasattr(viewer, "setTimingReportData"):
            viewer.setTimingReportData(self._report_data)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 1. Top File Selection Toolbar
        main_layout.addWidget(self._create_top_toolbar())

        # 2. Main Vertical Splitter
        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.setChildrenCollapsible(False)

        # Upper section (Histogram + Category Summary) with horizontal resizable splitter
        upper_splitter = QSplitter(Qt.Horizontal)
        upper_splitter.setChildrenCollapsible(False)
        upper_splitter.setStyleSheet("QSplitter::handle { background-color: #282C37; width: 3px; }")

        # Upper Left: Multi-View Timing Visualizer Deck
        viz_box = QFrame()
        viz_box.setStyleSheet("background-color: #1A1D24; border: 1px solid #282C37; border-radius: 4px;")
        viz_layout = QVBoxLayout(viz_box)
        viz_layout.setContentsMargins(4, 4, 4, 4)
        viz_layout.setSpacing(2)

        viz_header = QHBoxLayout()
        viz_header.setSpacing(3)

        self._btn_view_hist = QPushButton("Histogram")
        self._btn_view_scatter = QPushButton("Slack vs Logic")
        self._btn_view_pareto = QPushButton("Top Endpoints")
        self._btn_view_cdc = QPushButton("Clock Matrix")

        self._btn_view_hist.clicked.connect(lambda: self._set_viz_mode(0))
        self._btn_view_scatter.clicked.connect(lambda: self._set_viz_mode(1))
        self._btn_view_pareto.clicked.connect(lambda: self._set_viz_mode(2))
        self._btn_view_cdc.clicked.connect(lambda: self._set_viz_mode(3))

        for btn in (self._btn_view_hist, self._btn_view_scatter, self._btn_view_pareto, self._btn_view_cdc):
            btn.setFixedHeight(18)
            viz_header.addWidget(btn)

        viz_header.addStretch()

        self._btn_reset_hist = QPushButton("Reset Filter")
        self._btn_reset_hist.setFixedHeight(18)
        self._btn_reset_hist.setStyleSheet("font-size: 7pt; padding: 0 4px;")
        self._btn_reset_hist.clicked.connect(self._reset_histogram_filter)
        viz_header.addWidget(self._btn_reset_hist)
        viz_layout.addLayout(viz_header)

        # Multi-view deck
        self._viz_deck = QStackedWidget()

        self._hist_widget = PathHistogramWidget()
        self._hist_widget.bin_selected.connect(self._on_histogram_bin_selected)
        self._viz_deck.addWidget(self._hist_widget)

        self._scatter_widget = SlackScatterPlotWidget()
        self._scatter_widget.path_selected.connect(self._on_path_selected)
        self._viz_deck.addWidget(self._scatter_widget)

        self._pareto_widget = EndpointParetoWidget()
        self._pareto_widget.endpoint_selected.connect(self._on_endpoint_filter)
        self._viz_deck.addWidget(self._pareto_widget)

        self._clock_matrix_widget = ClockMatrixWidget()
        self._clock_matrix_widget.clock_pair_selected.connect(self._on_clock_pair_filter)
        self._viz_deck.addWidget(self._clock_matrix_widget)

        viz_layout.addWidget(self._viz_deck)
        upper_splitter.addWidget(viz_box)
        self._set_viz_mode(0)

        # Upper Right: Category Summary Card
        summary_box = QFrame()
        summary_box.setStyleSheet("background-color: #1A1D24; border: 1px solid #282C37; border-radius: 4px;")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(4, 4, 4, 4)
        summary_layout.setSpacing(2)

        summary_title = QLabel("Category Summary")
        summary_title.setStyleSheet("color: #E2E8F0; font-weight: bold; font-size: 8pt;")
        summary_layout.addWidget(summary_title)

        self._summary_widget = CategorySummaryWidget()
        summary_layout.addWidget(self._summary_widget)
        upper_splitter.addWidget(summary_box)

        upper_splitter.setSizes([460, 290])
        main_splitter.addWidget(upper_splitter)

        # Middle section: Tabbed Path Category & Optimization Failure Reason
        middle_tabs = QTabWidget()
        middle_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #282C37; background: #1A1D24; }
            QTabBar::tab {
                background: #232732; color: #A0A8B8; padding: 4px 10px;
                font-size: 8pt; font-weight: bold; border: 1px solid #282C37;
            }
            QTabBar::tab:selected { background: #1A1D24; color: #FFFFFF; border-bottom: 2px solid #00E5FF; }
        """)

        self._category_table = PathCategoryTable()
        self._category_table.category_selected.connect(self._on_category_selected)
        middle_tabs.addTab(self._category_table, "Path Category")

        self._reason_table = OptimizationFailureReasonTable()
        self._reason_table.reason_selected.connect(self._on_reason_selected)
        middle_tabs.addTab(self._reason_table, "Optimization Failure Reason")

        main_splitter.addWidget(middle_tabs)

        # Lower section: Path List Table & Delay Waterfall Inspector
        lower_box = QFrame()
        lower_box.setStyleSheet("background-color: #1A1D24; border: 1px solid #282C37; border-radius: 4px;")
        lower_layout = QVBoxLayout(lower_box)
        lower_layout.setContentsMargins(4, 4, 4, 4)
        lower_layout.setSpacing(4)

        lower_header = QHBoxLayout()
        list_title = QLabel("Path List")
        list_title.setStyleSheet("color: #E2E8F0; font-weight: bold; font-size: 8pt;")
        lower_header.addWidget(list_title)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter paths by pin, view, clock...")
        self._search_input.setFixedHeight(22)
        self._search_input.setStyleSheet("""
            QLineEdit {
                background-color: #232732; color: #FFFFFF; border: 1px solid #373D4D;
                border-radius: 3px; padding: 1px 6px; font-size: 8pt;
            }
        """)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        lower_header.addWidget(self._search_input)

        btn_reset_all = QPushButton("Reset All Filters")
        btn_reset_all.setFixedHeight(22)
        btn_reset_all.setStyleSheet("font-size: 8pt; padding: 0 6px;")
        btn_reset_all.clicked.connect(self.reset_all_filters)
        lower_header.addWidget(btn_reset_all)

        lower_layout.addLayout(lower_header)

        # Path Delay Waterfall Inspector Bar
        self._waterfall_widget = PathDelayWaterfallWidget()
        lower_layout.addWidget(self._waterfall_widget)

        self._path_list = PathListTable()
        self._path_list.path_selected.connect(self._on_path_selected)
        self._path_list.paths_highlighted.connect(self.paths_highlighted.emit)
        self._path_list.paths_cleared.connect(self.paths_cleared.emit)
        lower_layout.addWidget(self._path_list)

        main_splitter.addWidget(lower_box)

        # Initial splitter proportion (e.g. 200px visualizers, 120px categories, 330px path list)
        main_splitter.setSizes([190, 115, 335])
        main_layout.addWidget(main_splitter)

    def _create_top_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #1E222B; border: 1px solid #2B2F3B; border-radius: 4px;")
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)
        t_layout.setSpacing(6)

        lbl = QLabel("Report File(s):")
        lbl.setStyleSheet("color: #A0A8B8; font-weight: bold; font-size: 8pt;")
        t_layout.addWidget(lbl)

        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Select Cadence Innovus / Tempus timing report (.tarpt, .btarpt, .rpt)...")
        self._file_edit.setFixedHeight(24)
        self._file_edit.setStyleSheet("""
            QLineEdit {
                background-color: #14171E; color: #FFFFFF; border: 1px solid #373D4D;
                border-radius: 3px; padding: 2px 6px; font-size: 8pt;
            }
        """)
        self._file_edit.returnPressed.connect(self._on_reload_clicked)
        t_layout.addWidget(self._file_edit)

        btn_browse = QPushButton("...")
        btn_browse.setFixedSize(28, 24)
        btn_browse.setToolTip("Browse for timing report file")
        btn_browse.clicked.connect(self._browse_file_dialog)
        t_layout.addWidget(btn_browse)

        btn_reload = QPushButton("Reload")
        btn_reload.setFixedHeight(24)
        btn_reload.setToolTip("Reload timing report file")
        btn_reload.clicked.connect(self._on_reload_clicked)
        t_layout.addWidget(btn_reload)

        # Clear All Highlights prominent button
        btn_clear_paths = QPushButton("Clear All Highlights")
        btn_clear_paths.setFixedHeight(24)
        btn_clear_paths.setStyleSheet(
            "background-color: #3A2328; color: #FF8A80; border: 1px solid #5C2D35; "
            "border-radius: 3px; padding: 2px 10px; font-size: 8pt; font-weight: bold;"
        )
        btn_clear_paths.setToolTip("Remove all highlighted timing path flightlines and selection")
        btn_clear_paths.clicked.connect(self.clear_all_highlights)
        t_layout.addWidget(btn_clear_paths)

        t_layout.addSpacing(10)

        # Status badge chips
        self._badge_paths = QLabel("0 Paths")
        self._badge_paths.setStyleSheet(
            "background-color: #262B37; color: #E2E8F0; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: bold;"
        )
        t_layout.addWidget(self._badge_paths)

        self._badge_wns = QLabel("WNS: -")
        self._badge_wns.setStyleSheet(
            "background-color: #262B37; color: #E2E8F0; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: bold;"
        )
        t_layout.addWidget(self._badge_wns)

        self._badge_tns = QLabel("TNS: -")
        self._badge_tns.setStyleSheet(
            "background-color: #262B37; color: #E2E8F0; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: bold;"
        )
        t_layout.addWidget(self._badge_tns)

        return toolbar

    def clear_all_highlights(self) -> None:
        """Removes all highlighted paths and overlays from both the table and the layout canvas."""
        self._path_list.clear_all_highlights()

    def load_file(self, file_path: str, show_progress: bool = True) -> None:
        """Loads and parses a timing report file with clear loading time and progress bar."""
        if not os.path.exists(file_path):
            QMessageBox.critical(self, "File Not Found", f"Timing report not found:\n{file_path}")
            return

        self._file_edit.setText(file_path)
        base = os.path.basename(file_path)
        t_start = time.time()

        progress_dialog: Optional[QProgressDialog] = None
        if show_progress:
            progress_dialog = QProgressDialog(f"Loading timing report: {base}...", None, 0, 100, self)
            progress_dialog.setWindowTitle("Loading Timing Report")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            progress_dialog.show()
            QApplication.processEvents()

        def on_progress(stage: str, cur: int, total: int, detail: str) -> None:
            if progress_dialog is not None:
                pct = int((cur / max(total, 1)) * 100) if total > 0 else 50
                progress_dialog.setValue(min(pct, 99))
                progress_dialog.setLabelText(f"{stage}: {base}\n{detail} [{pct}%]")
                QApplication.processEvents()

        try:
            report = self._parser.parse_file(file_path, callback=on_progress if show_progress else None)
            if progress_dialog is not None:
                progress_dialog.setValue(100)
                QApplication.processEvents()
            self.set_report_data(report)
            elapsed = time.time() - t_start
            self._badge_paths.setToolTip(f"Loaded {len(report.paths):,} paths in {elapsed:.2f}s")
        except Exception as e:
            QMessageBox.critical(self, "Parse Error", f"Failed to parse timing report:\n{str(e)}")
        finally:
            if progress_dialog is not None:
                progress_dialog.close()

    def set_report_data(self, report: TimingReportData) -> None:
        """Sets structured report data and updates all sub-panels."""
        self._report_data = report

        # If a chip is already attached, calculate wire lengths
        if self._chip is not None:
            mbit_alias = None
            if self._layout_viewer and hasattr(self._layout_viewer, "_get_mbit_alias"):
                mbit_alias = self._layout_viewer._get_mbit_alias()
            self._report_data.compute_wire_lengths(self._chip, mbit_alias=mbit_alias)

        # Update Visualizers
        self._hist_widget.set_bins(report.histogram_bins)
        self._scatter_widget.set_paths(report.paths)
        self._pareto_widget.set_paths(report.paths)
        self._clock_matrix_widget.set_paths(report.paths)

        # Notify LayoutViewer to build timing connectivity index
        if self._layout_viewer and hasattr(self._layout_viewer, "setTimingReportData"):
            self._layout_viewer.setTimingReportData(report)

        # Update Summary
        stats_all = report.categories.get("all")
        self._summary_widget.set_stats(stats_all)

        # Update Categories table
        self._category_table.set_categories(report.categories)

        # Update Reasons table
        self._reason_table.set_reasons(report.failure_reasons)

        # Update Badges
        total = len(report.paths)
        wns = stats_all.wns if stats_all else 0.0
        tns = stats_all.tns if stats_all else 0.0

        self._badge_paths.setText(f"{total:,} Paths")

        wns_color = "#E57373" if wns < 0 else "#81C784"
        self._badge_wns.setText(f"WNS: {wns:+.4f} ns")
        self._badge_wns.setStyleSheet(
            f"background-color: #262B37; color: {wns_color}; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: bold;"
        )

        tns_color = "#E57373" if tns < 0 else "#81C784"
        self._badge_tns.setText(f"TNS: {tns:+.4f} ns")
        self._badge_tns.setStyleSheet(
            f"background-color: #262B37; color: {tns_color}; padding: 2px 8px; border-radius: 3px; font-size: 8pt; font-weight: bold;"
        )

        # Update Path List
        self._apply_filters()

    def setChip(self, chip: Any, layout_viewer: Any = None) -> None:
        """Attaches RISHI chip to calculate exact routed or Manhattan wire lengths."""
        self._chip = chip
        if layout_viewer is not None:
            self._layout_viewer = layout_viewer
        if chip is None:
            return
        if self._report_data is not None:
            mbit_alias = None
            if self._layout_viewer and hasattr(self._layout_viewer, "_get_mbit_alias"):
                mbit_alias = self._layout_viewer._get_mbit_alias()
            self._report_data.compute_wire_lengths(chip, mbit_alias=mbit_alias)
            self._apply_filters()

    def clear(self) -> None:
        """Clears all loaded timing report paths, statistics, visualizations, and input fields."""
        self._report_data = None
        self._chip = None
        self._layout_viewer = None
        self._file_edit.clear()
        self._search_input.clear()
        self._active_slack_range = None
        self._active_category = None
        self._active_reason = None
        self._hist_widget.set_bins([])
        self._scatter_widget.set_paths([])
        self._pareto_widget.set_paths([])
        self._clock_matrix_widget.set_paths([])
        self._waterfall_widget.set_path(None)
        self._summary_widget.set_stats(None)
        self._category_table.set_categories({})
        self._reason_table.set_reasons([])
        self._path_list.set_paths([])
        self._badge_paths.setText("0 Paths")
        self._badge_wns.setText("WNS: 0.0000 ns")
        self._badge_tns.setText("TNS: 0.0000 ns")
        self._badge_paths.setVisible(False)
        self._badge_wns.setVisible(False)
        self._badge_tns.setVisible(False)
        self.paths_cleared.emit()

    def _browse_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Timing Report",
            "",
            "Timing Reports (*.tarpt *.btarpt *.rpt *.tarpt.gz);;All Files (*.*)",
        )
        if path:
            self.load_file(path)

    def _on_reload_clicked(self) -> None:
        path = self._file_edit.text().strip()
        if path:
            self.load_file(path)

    def _on_histogram_bin_selected(self, bin_obj: Optional[HistogramBin]) -> None:
        if bin_obj:
            self._active_slack_range = (bin_obj.slack_min, bin_obj.slack_max)
        else:
            self._active_slack_range = None
        self._apply_filters()

    def _reset_histogram_filter(self) -> None:
        self._hist_widget.clear_selection()

    def _on_category_selected(self, cat_name: str) -> None:
        self._active_category = cat_name
        if self._report_data:
            stats = self._report_data.categories.get(cat_name)
            self._summary_widget.set_stats(stats)
        self._apply_filters()

    def _on_reason_selected(self, reason: str) -> None:
        self._active_reason = reason
        self._apply_filters()

    def _on_search_text_changed(self, text: str) -> None:
        self._active_search = text
        self._apply_filters()

    def reset_all_filters(self) -> None:
        self._active_category = "all"
        self._active_slack_range = None
        self._active_reason = ""
        self._active_search = ""
        self._search_input.clear()
        self._hist_widget.clear_selection()
        if self._report_data:
            self._summary_widget.set_stats(self._report_data.categories.get("all"))
        self._apply_filters()

    def _apply_filters(self) -> None:
        if not self._report_data:
            self._path_list.set_paths([])
            return

        filtered = self._report_data.filter_paths(
            category=self._active_category,
            slack_range=self._active_slack_range,
            search_text=self._active_search,
        )

        if self._active_reason:
            filtered = [
                p for p in filtered
                if self._active_reason.lower() in p.failure_reason.lower()
            ]

        self._path_list.set_paths(filtered)

    def _set_viz_mode(self, mode: int) -> None:
        self._viz_deck.setCurrentIndex(mode)
        buttons = [self._btn_view_hist, self._btn_view_scatter, self._btn_view_pareto, self._btn_view_cdc]
        for idx, btn in enumerate(buttons):
            if idx == mode:
                btn.setStyleSheet("background-color: #00E5FF; color: #000000; font-weight: bold; font-size: 7pt; border-radius: 2px; padding: 2px 6px;")
            else:
                btn.setStyleSheet("background-color: #232732; color: #A0A8B8; font-weight: bold; font-size: 7pt; border-radius: 2px; padding: 2px 6px;")

    def _on_endpoint_filter(self, ep_name: str) -> None:
        self._search_input.setText(ep_name)

    def _on_clock_pair_filter(self, launch_clk: str, capture_clk: str) -> None:
        self._search_input.setText(launch_clk)

    def _on_path_selected(self, path: TimingPath, zoom: bool) -> None:
        self._waterfall_widget.set_path(path)
        self._scatter_widget.set_selected_path(path)
        self.path_selected.emit(path, zoom)


# ==============================================================================
# 7. Timing Report Dock Widget Wrapper
# ==============================================================================

class TimingReportDock(QDockWidget):
    """Dockable container for TimingReportWidget."""

    path_selected = Signal(object, bool)
    paths_highlighted = Signal(list)
    paths_cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Timing Report & Debug", parent)
        self.setObjectName("TimingReportDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )

        self._widget = TimingReportWidget(self)
        self.setWidget(self._widget)

        # Forward signals
        self._widget.path_selected.connect(self.path_selected.emit)
        self._widget.paths_highlighted.connect(self.paths_highlighted.emit)
        self._widget.paths_cleared.connect(self.paths_cleared.emit)

    def get_widget(self) -> TimingReportWidget:
        return self._widget

    def load_file(self, file_path: str, show_progress: bool = True) -> None:
        self._widget.load_file(file_path, show_progress=show_progress)

    def setLayoutViewer(self, viewer: Any) -> None:
        self._widget.setLayoutViewer(viewer)

    def setChip(self, chip: Any, layout_viewer: Any = None) -> None:
        self._widget.setChip(chip, layout_viewer=layout_viewer)

    def clear(self) -> None:
        self._widget.clear()

