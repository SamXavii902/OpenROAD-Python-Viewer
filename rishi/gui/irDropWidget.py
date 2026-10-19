"""Independent IR-drop report dock with hotspot analysis, high-speed filtering, and layout navigation."""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rishi.irdrop.report import IR_DROP_PALETTE, IRDropBin, IRDropParser, IRDropReportData


class IRDropLoadThread(QThread):
    progress = Signal(int, int)
    loaded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, file_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._file_path = file_path

    def run(self) -> None:
        try:
            def on_progress(current: int, total: int) -> None:
                if self.isInterruptionRequested():
                    raise InterruptedError("IR-drop report loading cancelled")
                self.progress.emit(current, total)

            report = IRDropParser().parse_file(self._file_path, callback=on_progress)
            self.loaded.emit(report)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class IRDropHistogramWidget(QWidget):
    """Clickable distribution histogram for per-instance voltage drop with instant selection."""

    bin_selected = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._bins: List[IRDropBin] = []
        self._selected_index: Optional[int] = None
        self._hover_index: Optional[int] = None
        self.setMinimumHeight(135)
        self.setMouseTracking(True)

    def set_bins(self, bins: List[IRDropBin]) -> None:
        self._bins = bins
        self._selected_index = None
        self._hover_index = None
        self.update()

    def clear_selection(self) -> None:
        self._selected_index = None
        self._hover_index = None
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Polished EDA background and border
        painter.fillRect(self.rect(), QColor("#16181D"))
        painter.setPen(QPen(QColor("#282C37"), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        if not self._bins:
            painter.setPen(QColor("#707888"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(self.rect(), Qt.AlignCenter, "Load an IR-drop report to inspect the distribution")
            painter.end()
            return

        left, right, top, bottom = 48.0, 16.0, 14.0, 24.0
        plot_width = max(self.width() - left - right, 1.0)
        plot_height = max(self.height() - top - bottom, 1.0)
        max_count = max((item.count for item in self._bins), default=1) or 1
        bar_gap = 2.0
        bar_width = max((plot_width - bar_gap * (len(self._bins) - 1)) / len(self._bins), 1.0)

        # Subtle Y-axis gridlines and labels
        painter.setFont(QFont("Segoe UI", 7))
        grid_pen = QPen(QColor("#232732"), 1, Qt.DashLine)
        for tick in range(4):
            fraction = tick / 3.0
            y = top + plot_height * (1.0 - fraction)
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(left, y), QPointF(left + plot_width, y))
            painter.setPen(QColor("#707888"))
            val_str = f"{round(max_count * fraction):,}"
            painter.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, val_str)

        # Histogram bars with smooth palette gradient and active selection glow
        for index, item in enumerate(self._bins):
            x = left + index * (bar_width + bar_gap)
            bar_height = plot_height * item.count / max_count
            rect = QRectF(x, top + plot_height - bar_height, bar_width, max(bar_height, 1.0))
            color_idx = min(index * len(IR_DROP_PALETTE) // len(self._bins), len(IR_DROP_PALETTE) - 1)
            color = QColor(IR_DROP_PALETTE[color_idx])

            is_selected = index == self._selected_index
            is_hover = index == self._hover_index

            if is_selected:
                color.setAlpha(245)
                painter.setPen(QPen(QColor("#00E5FF"), 2))
            elif is_hover:
                color.setAlpha(225)
                painter.setPen(QPen(QColor("#E2E8F0"), 1.5))
            else:
                color.setAlpha(175)
                painter.setPen(QPen(color.darker(130), 1))

            painter.setBrush(color)
            painter.drawRoundedRect(rect, 2, 2)

        # Min and Max mV labels at bottom
        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor("#A0A8B8"))
        painter.drawText(
            QRectF(left, self.height() - bottom + 2, plot_width, bottom - 2),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"{self._bins[0].minimum_mv:.1f} mV",
        )
        painter.drawText(
            QRectF(left, self.height() - bottom + 2, plot_width, bottom - 2),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{self._bins[-1].maximum_mv:.1f} mV",
        )
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        index = self._hit_test(event.position())
        if index != self._hover_index:
            self._hover_index = index
            if index is not None and index < len(self._bins):
                item = self._bins[index]
                self.setToolTip(f"{item.minimum_mv:.2f}–{item.maximum_mv:.2f} mV · {item.count:,} instances\nClick to filter")
            else:
                self.setToolTip("")
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            index = self._hit_test(event.position())
            if index is not None:
                self._selected_index = None if self._selected_index == index else index
                selected = self._bins[self._selected_index] if self._selected_index is not None else None
                self.bin_selected.emit(selected)
                self.update()
        super().mousePressEvent(event)

    def _hit_test(self, point: QPointF) -> Optional[int]:
        if not self._bins:
            return None
        left, right = 48.0, 16.0
        width = max(self.width() - left - right, 1.0)
        gap = 2.0
        bar_width = max((width - gap * (len(self._bins) - 1)) / len(self._bins), 1.0)
        relative = point.x() - left
        index = int(relative / (bar_width + gap))
        if relative < 0 or index < 0 or index >= len(self._bins):
            return None
        if relative - index * (bar_width + gap) > bar_width:
            return None
        return index


class IRDropWidget(QWidget):
    """Report controls, IR-drop insights, high-speed hotspot tables, and layout navigation."""

    instance_selected = Signal(str)
    map_visibility_changed = Signal(bool)

    PAGE_SIZE = 100

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._report: Optional[IRDropReportData] = None
        self._layout_viewer: Any = None
        self._loader: Optional[IRDropLoadThread] = None
        self._load_generation = 0
        self._filtered_instances: List[str] = []
        self._selected_bin: Optional[IRDropBin] = None
        self._page = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 1. Top File Open Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Select per-cell IR-drop report (*.rpt, *.ir, *.txt)...")
        self._file_edit.setStyleSheet("""
            QLineEdit {
                background-color: #151821;
                color: #E2E8F0;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QLineEdit:focus {
                border: 1px solid #00E5FF;
            }
        """)
        self._file_edit.setClearButtonEnabled(True)
        self._file_edit.returnPressed.connect(self._load_from_path)
        toolbar.addWidget(self._file_edit, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        toolbar.addWidget(browse_btn)

        self._load_button = QPushButton("Load Report")
        self._load_button.setStyleSheet("""
            QPushButton {
                background-color: #262B38;
                color: #00E5FF;
                border: 1px solid #00E5FF;
                border-radius: 3px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00E5FF;
                color: #000000;
            }
            QPushButton:disabled {
                border-color: #282C37;
                color: #64748B;
            }
        """)
        self._load_button.clicked.connect(self._load_from_path)
        toolbar.addWidget(self._load_button)

        self._map_toggle = QCheckBox("⚡ IR-Drop Layout Map")
        self._map_toggle.setToolTip("Overlay 2D IR-drop thermal heatmap and colored cell footprints on layout")
        self._map_toggle.setStyleSheet("QCheckBox { color: #E2E8F0; font-weight: bold; font-size: 8pt; }")
        self._map_toggle.toggled.connect(self._on_map_toggled)
        toolbar.addWidget(self._map_toggle)
        root.addLayout(toolbar)

        # 2. Legend Pill Bar
        self._map_legend = QHBoxLayout()
        self._map_legend.setSpacing(6)
        legend_title = QLabel("Color Bins:")
        legend_title.setStyleSheet("color: #707888; font-size: 8pt; font-weight: bold;")
        self._map_legend.addWidget(legend_title)

        self._map_legend_labels: List[QLabel] = []
        for color in IR_DROP_PALETTE:
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(f"background-color: {color}; border-radius: 3px; border: 1px solid #3B4356;")
            range_label = QLabel("—")
            range_label.setStyleSheet("color: #A0A8B8; font-size: 8pt; margin-right: 8px;")
            self._map_legend.addWidget(swatch)
            self._map_legend.addWidget(range_label)
            self._map_legend_labels.append(range_label)
        self._map_legend.addStretch()
        root.addLayout(self._map_legend)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet("QProgressBar::chunk { background-color: #00E5FF; }")
        self._progress.hide()
        root.addWidget(self._progress)

        # 3. Four Polished Summary Metric Cards (Instances, Mean Drop, P95 Drop, Worst Drop)
        summary = QHBoxLayout()
        summary.setSpacing(6)
        self._metric_labels = {}
        card_configs = [
            ("count", "TOTAL INSTANCES", "#00E5FF"),
            ("mean", "MEAN VOLTAGE DROP", "#81C784"),
            ("p95", "95TH PERCENTILE", "#FFB74D"),
            ("max", "WORST HOTSPOT DROP", "#FF5252"),
        ]
        for key, title, val_color in card_configs:
            frame = QFrame()
            frame.setStyleSheet("""
                QFrame {
                    background-color: #1A1D24;
                    border: 1px solid #282C37;
                    border-radius: 4px;
                }
                QFrame:hover {
                    border: 1px solid #3B4356;
                }
            """)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(2)

            title_label = QLabel(title)
            title_label.setStyleSheet("color: #8E9AA5; font-size: 7.5pt; font-weight: bold; border: none;")
            value_label = QLabel("—")
            value_label.setStyleSheet(f"color: {val_color}; font-size: 13pt; font-weight: bold; border: none;")
            layout.addWidget(title_label)
            layout.addWidget(value_label)
            summary.addWidget(frame, 1)
            self._metric_labels[key] = value_label
        root.addLayout(summary)

        # 4. Interactive Distribution Histogram
        self._histogram = IRDropHistogramWidget()
        self._histogram.bin_selected.connect(self._on_bin_selected)
        root.addWidget(self._histogram)

        # 5. Search & Threshold Filter Bar
        controls = QHBoxLayout()
        controls.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by instance name or cell type...")
        self._search.setStyleSheet("""
            QLineEdit {
                background-color: #151821;
                color: #E2E8F0;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QLineEdit:focus {
                border: 1px solid #00E5FF;
            }
        """)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_filter_changed)
        controls.addWidget(self._search, 1)

        self._threshold_toggle = QCheckBox("Threshold ≥")
        self._threshold_toggle.setStyleSheet("QCheckBox { color: #A0A8B8; font-size: 8pt; }")
        self._threshold_toggle.toggled.connect(self._on_filter_changed)
        controls.addWidget(self._threshold_toggle)

        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(-100000.0, 100000.0)
        self._threshold.setDecimals(1)
        self._threshold.setSuffix(" mV")
        self._threshold.setValue(50.0)
        self._threshold.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #151821;
                color: #E2E8F0;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 2px 4px;
            }
        """)
        self._threshold.valueChanged.connect(self._on_filter_changed)
        controls.addWidget(self._threshold)

        reset_btn = QPushButton("Reset Filters")
        reset_btn.setToolTip("Clear search, threshold, and active histogram bin selection")
        reset_btn.clicked.connect(self._reset_filters)
        controls.addWidget(reset_btn)
        root.addLayout(controls)

        # 6. Tabbed Tables (Hotspots Table, Cell Types Table)
        self._tabs = QTabWidget()
        self._instance_table = self._create_table(("Drop (mV)", "Cell Type", "Instance Name"))
        self._instance_table.cellClicked.connect(self._on_instance_row_clicked)
        self._instance_table.cellDoubleClicked.connect(self._on_instance_row_clicked)
        self._tabs.addTab(self._instance_table, "🔥 Hotspot Instances")

        self._cell_table = self._create_table(("Cell Type", "Instances", "Mean (mV)", "Worst (mV)", "Worst Instance"))
        self._cell_table.cellClicked.connect(self._on_cell_type_row_clicked)
        self._cell_table.cellDoubleClicked.connect(self._on_cell_type_row_clicked)
        self._tabs.addTab(self._cell_table, "📊 Cell Type Analysis")
        root.addWidget(self._tabs, 1)

        # 7. Pagination Toolbar
        paging = QHBoxLayout()
        self._result_count = QLabel("No report loaded")
        self._result_count.setStyleSheet("color: #8E9AA5; font-size: 8pt;")
        paging.addWidget(self._result_count, 1)

        self._status = QLabel("Drop = ideal_voltage − min_pg_sim")
        self._status.setStyleSheet("color: #707888; font-size: 7.5pt; font-style: italic;")
        paging.addWidget(self._status)

        self._prev_button = QPushButton("◀ Prev")
        self._prev_button.clicked.connect(self._previous_page)
        paging.addWidget(self._prev_button)

        self._page_label = QLabel("Page 0 / 0")
        self._page_label.setStyleSheet("color: #CBD5E1; font-weight: bold; font-size: 8pt; padding: 0 4px;")
        paging.addWidget(self._page_label)

        self._next_button = QPushButton("Next ▶")
        self._next_button.clicked.connect(self._next_page)
        paging.addWidget(self._next_button)
        root.addLayout(paging)

    @staticmethod
    def _create_table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #1A1D24;
                alternate-background-color: #151821;
                color: #D6DCE5;
                gridline-color: #282C37;
                border: 1px solid #282C37;
                font-family: 'Segoe UI';
                font-size: 8pt;
                selection-background-color: #00E5FF;
                selection-color: #000000;
            }
            QHeaderView::section {
                background-color: #232732;
                color: #A0A8B8;
                font-weight: bold;
                border: 1px solid #282C37;
                padding: 4px 6px;
                font-size: 8pt;
            }
        """)
        return table

    def setLayoutViewer(self, viewer: Any) -> None:
        self._layout_viewer = viewer
        self._sync_map_data()

    def load_file(self, file_path: str) -> None:
        if self._loader is not None and self._loader.isRunning():
            return
        if not os.path.isfile(file_path):
            self._status.setText(f"Report not found: {file_path}")
            return
        self._file_edit.setText(file_path)
        self._load_button.setEnabled(False)
        self._progress.setValue(0)
        self._progress.show()
        self._status.setText(f"Reading {os.path.basename(file_path)}...")
        self._load_generation += 1
        generation = self._load_generation
        self._loader = IRDropLoadThread(file_path, self)
        loader = self._loader
        loader.progress.connect(
            lambda current, total: self._on_progress(current, total)
            if generation == self._load_generation else None
        )
        loader.loaded.connect(
            lambda report: self.set_report_data(report)
            if generation == self._load_generation else None
        )
        loader.failed.connect(
            lambda message: self._on_load_failed(message)
            if generation == self._load_generation else None
        )
        loader.cancelled.connect(
            lambda: self._status.setText("Load cancelled")
            if generation == self._load_generation else None
        )
        loader.finished.connect(lambda: self._on_load_finished(loader, generation))
        loader.start()

    def set_report_data(self, report: IRDropReportData) -> None:
        self._report = report
        self._histogram.set_bins(report.bins)
        self._selected_bin = None
        self._metric_labels["count"].setText(f"{report.instance_count:,}")
        self._metric_labels["mean"].setText(f"{report.mean_mv:.1f} mV")
        self._metric_labels["p95"].setText(f"{report.percentile_95_mv:.1f} mV")
        self._metric_labels["max"].setText(f"{report.maximum_mv:.1f} mV")

        palette_count = len(self._map_legend_labels)
        span = report.maximum_mv - report.minimum_mv
        for index, label in enumerate(self._map_legend_labels):
            low = report.minimum_mv + span * index / palette_count
            high = report.minimum_mv + span * (index + 1) / palette_count
            label.setText(f"{low:.1f}–{high:.1f}")

        self._status.setText(
            f"{report.record_count:,} rows · {report.instance_count:,} cells · drop = ideal − min_pg_sim"
        )
        self._populate_cell_types()
        self._sync_map_data()
        self._page = 0
        self._refresh_tables()

    def set_map_visible(self, visible: bool) -> None:
        self._map_toggle.setChecked(visible)

    def stop_loading(self) -> None:
        if self._loader is not None and self._loader.isRunning():
            self._loader.requestInterruption()
            self._loader.wait()

    def clear(self) -> None:
        self._load_generation += 1
        self.stop_loading()
        self._report = None
        self._filtered_instances = []
        self._selected_bin = None
        self._histogram.set_bins([])
        self._instance_table.setRowCount(0)
        self._cell_table.setRowCount(0)
        self._file_edit.clear()
        self._search.clear()
        self._map_toggle.setChecked(False)
        for label in self._metric_labels.values():
            label.setText("—")
        self._status.setText("Drop = ideal_voltage − min_pg_sim")
        self._result_count.setText("No report loaded")
        self._page_label.setText("Page 0 / 0")
        self._sync_map_data()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open IR-Drop Report", "", "IR-Drop Reports (*.rpt *.ir *.txt);;All Files (*.*)"
        )
        if path:
            self.load_file(path)

    def _load_from_path(self) -> None:
        path = self._file_edit.text().strip()
        if path:
            self.load_file(path)

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setValue(min(int(current * 100 / max(total, 1)), 99))
        self._status.setText(f"Parsing: {current / (1024 * 1024):,.0f} / {total / (1024 * 1024):,.0f} MiB")

    def _on_load_failed(self, message: str) -> None:
        self._status.setText(f"Error loading report: {message}")

    def _on_load_finished(self, loader: IRDropLoadThread, generation: int) -> None:
        if generation == self._load_generation and loader is self._loader:
            self._progress.setValue(100)
            self._progress.hide()
            self._load_button.setEnabled(True)
            self._loader = None
        loader.deleteLater()

    def _on_map_toggled(self, checked: bool) -> None:
        self.map_visibility_changed.emit(checked)
        if self._layout_viewer is not None:
            self._layout_viewer.setIRDropMapVisible(checked)

    def _sync_map_data(self) -> None:
        if self._layout_viewer is not None:
            self._layout_viewer.setIRDropData(self._report)
            self._layout_viewer.setIRDropMapVisible(self._map_toggle.isChecked())

    def _on_bin_selected(self, selected: Optional[IRDropBin]) -> None:
        """Instant O(1) bin filtering without scanning the entire design."""
        self._selected_bin = selected
        self._page = 0
        self._refresh_tables()

    def _reset_filters(self) -> None:
        self._selected_bin = None
        self._histogram.clear_selection()
        self._search.clear()
        self._threshold_toggle.setChecked(False)
        self._page = 0
        self._refresh_tables()

    def _on_filter_changed(self, *_args) -> None:
        self._page = 0
        self._refresh_tables()

    def _refresh_tables(self, *_args) -> None:
        """Lightning-fast instance filtering leveraging precomputed bin indices."""
        if self._report is None:
            return

        query = self._search.text().strip().casefold()
        threshold_enabled = self._threshold_toggle.isChecked()
        threshold = self._threshold.value()
        selected_bin = self._selected_bin

        # 1. Determine candidate instances pool: precomputed bin list vs full ordered list
        if selected_bin is not None:
            bin_idx = getattr(selected_bin, "bin_index", None)
            if bin_idx is None and hasattr(self._report, "bins"):
                try:
                    bin_idx = self._report.bins.index(selected_bin)
                except ValueError:
                    bin_idx = None
            if bin_idx is not None and hasattr(self._report, "bin_instances") and bin_idx < len(self._report.bin_instances):
                candidate_pool = self._report.bin_instances[bin_idx]
            else:
                candidate_pool = self._report.ordered_instances
        else:
            candidate_pool = self._report.ordered_instances

        # 2. Fast paths
        if not query and not threshold_enabled:
            self._filtered_instances = candidate_pool
            page_count = math.ceil(len(self._filtered_instances) / self.PAGE_SIZE) if self._filtered_instances else 0
            self._page = min(self._page, max(page_count - 1, 0))
            self._populate_instance_page(page_count)
            return

        # 3. Filtered path (runs only over candidate pool, usually small & instant)
        records = self._report.records_by_instance
        filtered = []
        for instance in candidate_pool:
            rec = records.get(instance)
            if rec is None:
                continue
            value, cell_type = rec
            if threshold_enabled and value < threshold:
                continue
            if query and query not in instance.casefold() and query not in cell_type.casefold():
                continue
            filtered.append(instance)

        self._filtered_instances = filtered
        page_count = math.ceil(len(filtered) / self.PAGE_SIZE) if filtered else 0
        self._page = min(self._page, max(page_count - 1, 0))
        self._populate_instance_page(page_count)

    def _populate_instance_page(self, page_count: Optional[int] = None) -> None:
        if self._report is None:
            return
        if page_count is None:
            page_count = math.ceil(len(self._filtered_instances) / self.PAGE_SIZE) if self._filtered_instances else 0

        start = self._page * self.PAGE_SIZE
        visible = self._filtered_instances[start:start + self.PAGE_SIZE]

        self._instance_table.setUpdatesEnabled(False)
        self._instance_table.blockSignals(True)
        try:
            self._instance_table.setRowCount(len(visible))
            records = self._report.records_by_instance
            bold_font = QFont("Segoe UI", 8, QFont.Bold)
            mono_font = QFont("Consolas", 8)

            for row, instance in enumerate(visible):
                rec = records.get(instance)
                if rec is None:
                    continue
                drop, cell_type = rec

                item_drop = QTableWidgetItem(f"{drop:8.2f}")
                item_drop.setFont(bold_font)
                color_hex = IR_DROP_PALETTE[self._report.color_index(drop)]
                item_drop.setForeground(QColor(color_hex))
                item_drop.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._instance_table.setItem(row, 0, item_drop)

                item_cell = QTableWidgetItem(cell_type)
                item_cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self._instance_table.setItem(row, 1, item_cell)

                item_inst = QTableWidgetItem(instance)
                item_inst.setFont(mono_font)
                item_inst.setData(Qt.UserRole, instance)
                item_inst.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self._instance_table.setItem(row, 2, item_inst)
        finally:
            self._instance_table.blockSignals(False)
            self._instance_table.setUpdatesEnabled(True)

        self._result_count.setText(
            f"{len(self._filtered_instances):,} matching instances · {self._report.instance_count:,} total"
        )
        self._page_label.setText(f"Page {self._page + 1 if page_count else 0} / {page_count}")
        self._prev_button.setEnabled(self._page > 0)
        self._next_button.setEnabled(self._page + 1 < page_count)

    def _populate_cell_types(self) -> None:
        if self._report is None:
            return
        items = sorted(self._report.cell_type_stats.items(), key=lambda entry: entry[1][2], reverse=True)

        self._cell_table.setUpdatesEnabled(False)
        self._cell_table.blockSignals(True)
        try:
            self._cell_table.setRowCount(len(items))
            bold_font = QFont("Segoe UI", 8, QFont.Bold)
            mono_font = QFont("Consolas", 8)

            for row, (cell_type, (count, mean, worst, instance)) in enumerate(items):
                item_type = QTableWidgetItem(cell_type)
                item_type.setFont(bold_font)
                self._cell_table.setItem(row, 0, item_type)

                item_count = QTableWidgetItem(f"{count:,}")
                item_count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._cell_table.setItem(row, 1, item_count)

                item_mean = QTableWidgetItem(f"{mean:.2f}")
                item_mean.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._cell_table.setItem(row, 2, item_mean)

                item_worst = QTableWidgetItem(f"{worst:.2f}")
                item_worst.setFont(bold_font)
                color_hex = IR_DROP_PALETTE[self._report.color_index(worst)]
                item_worst.setForeground(QColor(color_hex))
                item_worst.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._cell_table.setItem(row, 3, item_worst)

                item_inst = QTableWidgetItem(instance)
                item_inst.setFont(mono_font)
                item_inst.setData(Qt.UserRole, instance)
                self._cell_table.setItem(row, 4, item_inst)
        finally:
            self._cell_table.blockSignals(False)
            self._cell_table.setUpdatesEnabled(True)

    def _on_instance_row_clicked(self, row: int, _column: int) -> None:
        """Navigates layout canvas directly to selected instance on single or double click."""
        item = self._instance_table.item(row, 2)
        if item is not None:
            inst_name = str(item.data(Qt.UserRole) or item.text())
            if inst_name:
                self.instance_selected.emit(inst_name)

    def _on_cell_type_row_clicked(self, row: int, _column: int) -> None:
        """Navigates layout canvas to worst hotspot instance for the selected cell type."""
        item = self._cell_table.item(row, 4)
        if item is not None:
            inst_name = str(item.data(Qt.UserRole) or item.text())
            if inst_name:
                self.instance_selected.emit(inst_name)

    def _previous_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._populate_instance_page()

    def _next_page(self) -> None:
        if (self._page + 1) * self.PAGE_SIZE < len(self._filtered_instances):
            self._page += 1
            self._populate_instance_page()


class IRDropDock(QDockWidget):
    """Dock wrapper for the independent IR-drop analysis widget."""

    instance_selected = Signal(str)
    map_visibility_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("IR-Drop Analysis", parent)
        self.setObjectName("IRDropDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setWidget(IRDropWidget(self))
        self._widget: IRDropWidget = self.widget()
        self._widget.instance_selected.connect(self.instance_selected.emit)
        self._widget.map_visibility_changed.connect(self.map_visibility_changed.emit)

    def get_widget(self) -> IRDropWidget:
        return self._widget

    def setLayoutViewer(self, viewer: Any) -> None:
        self._widget.setLayoutViewer(viewer)

    def load_file(self, file_path: str) -> None:
        self._widget.load_file(file_path)

    def clear(self) -> None:
        self._widget.clear()