"""Independent IR-drop report dock with hotspot analysis, high-speed filtering, and layout navigation."""

from __future__ import annotations

import csv
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rishi.irdrop.report import (
    IR_DROP_PALETTE,
    IRDropBin,
    IRDropParser,
    IRDropReportData,
    parse_range_spec,
)


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
                self.setToolTip(f"{item.minimum_mv:.2f} - {item.maximum_mv:.2f} mV | {item.count:,} instances\nClick to filter")
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
    bin_filter_changed = Signal(object)

    PAGE_SIZE = 100

    def __init__(self, parent: Optional[QWidget] = None, layout_viewer: Any = None):
        super().__init__(parent)
        self._report: Optional[IRDropReportData] = None
        self._layout_viewer: Any = layout_viewer
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

        self._map_toggle = QCheckBox("IR-Drop Map")
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

        # 4. Histogram Binning Controls Toolbar
        bin_ctrls = QHBoxLayout()
        bin_ctrls.setSpacing(6)

        bin_label = QLabel("Binning:")
        bin_label.setStyleSheet("color: #8E9AA5; font-size: 8pt; font-weight: bold;")
        bin_ctrls.addWidget(bin_label)

        self._bin_mode_combo = QComboBox()
        self._bin_mode_combo.addItems(["Auto (24 Bins)", "Step Size (mV)", "Custom Ranges"])
        self._bin_mode_combo.setToolTip("Choose how histogram voltage drop ranges are grouped")
        self._bin_mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #151821;
                color: #E2E8F0;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 3px 8px;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QComboBox QAbstractItemView {
                background-color: #1A1D24;
                color: #E2E8F0;
                selection-background-color: #00E5FF;
                selection-color: #000000;
            }
        """)
        self._bin_mode_combo.currentIndexChanged.connect(self._on_bin_mode_changed)
        bin_ctrls.addWidget(self._bin_mode_combo)

        self._bin_step_spin = QDoubleSpinBox()
        self._bin_step_spin.setRange(0.1, 10000.0)
        self._bin_step_spin.setDecimals(1)
        self._bin_step_spin.setSuffix(" mV")
        self._bin_step_spin.setValue(10.0)
        self._bin_step_spin.setToolTip("Divide histogram into equal steps of this size (mV)")
        self._bin_step_spin.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #151821;
                color: #E2E8F0;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 3px 6px;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
        """)
        self._bin_step_spin.hide()
        bin_ctrls.addWidget(self._bin_step_spin)

        self._bin_ranges_edit = QLineEdit()
        self._bin_ranges_edit.setPlaceholderText("e.g. 20, 40, 60, 80 or 0-25, 25-50, 50-75, 75+")
        self._bin_ranges_edit.setToolTip("Enter comma-separated cutoffs (e.g. 20, 40, 60) or range pairs (e.g. 0-25, 25-50, 50-75)")
        self._bin_ranges_edit.setStyleSheet("""
            QLineEdit {
                background-color: #151821;
                color: #E2E8F0;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 3px 8px;
                font-family: 'Segoe UI';
                font-size: 8pt;
            }
            QLineEdit:focus {
                border: 1px solid #00E5FF;
            }
        """)
        self._bin_ranges_edit.returnPressed.connect(self._on_apply_bins)
        self._bin_ranges_edit.hide()
        bin_ctrls.addWidget(self._bin_ranges_edit, 1)

        self._apply_bins_btn = QPushButton("Apply Bins")
        self._apply_bins_btn.setToolTip("Recalculate histogram distribution with the chosen binning parameters")
        self._apply_bins_btn.setStyleSheet("""
            QPushButton {
                background-color: #262B38;
                color: #00E5FF;
                border: 1px solid #00E5FF;
                border-radius: 3px;
                padding: 3px 10px;
                font-weight: bold;
                font-size: 8pt;
            }
            QPushButton:hover {
                background-color: #00E5FF;
                color: #000000;
            }
        """)
        self._apply_bins_btn.clicked.connect(self._on_apply_bins)
        self._apply_bins_btn.hide()
        bin_ctrls.addWidget(self._apply_bins_btn)

        self._reset_bins_btn = QPushButton("Reset Bins")
        self._reset_bins_btn.setToolTip("Revert histogram to standard 24 uniform bins")
        self._reset_bins_btn.setStyleSheet("""
            QPushButton {
                background-color: #1A1D24;
                color: #A0A8B8;
                border: 1px solid #282C37;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 8pt;
            }
            QPushButton:hover {
                background-color: #282C37;
                color: #E2E8F0;
            }
        """)
        self._reset_bins_btn.clicked.connect(self._on_reset_bins)
        bin_ctrls.addWidget(self._reset_bins_btn)

        root.addLayout(bin_ctrls)

        # 5. Interactive Distribution Histogram
        self._histogram = IRDropHistogramWidget()
        self._histogram.bin_selected.connect(self._on_bin_selected)
        root.addWidget(self._histogram)

        # 6. Search, Threshold, & Export Filter Bar
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

        self._threshold_toggle = QCheckBox("Threshold >=")
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

        self._export_btn = QPushButton("Export List...")
        self._export_btn.setToolTip("Export the resultant filtered cells to CSV or Excel (.xlsx) including coordinates")
        self._export_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #38BDF8;
                border: 1px solid #38BDF8;
                border-radius: 3px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 8pt;
            }
            QPushButton:hover {
                background-color: #38BDF8;
                color: #0F172A;
            }
        """)
        export_menu = QMenu(self)
        export_csv_action = export_menu.addAction("Export to CSV (*.csv)...")
        export_csv_action.triggered.connect(lambda: self._export_data(file_format="csv"))
        export_xlsx_action = export_menu.addAction("Export to Excel (*.xlsx)...")
        export_xlsx_action.triggered.connect(lambda: self._export_data(file_format="xlsx"))
        self._export_btn.setMenu(export_menu)
        controls.addWidget(self._export_btn)

        root.addLayout(controls)

        # 7. Tabbed Tables (Hotspots Table, Cell Types Table)
        self._tabs = QTabWidget()
        self._instance_table = self._create_table(("Drop (mV)", "Cell Type", "Instance Name"))
        self._instance_table.cellClicked.connect(self._on_instance_row_clicked)
        self._instance_table.cellDoubleClicked.connect(self._on_instance_row_double_clicked)
        self._tabs.addTab(self._instance_table, "Hotspots")

        self._cell_table = self._create_table(("Cell Type", "Instances", "Mean (mV)", "Worst (mV)", "Worst Instance"))
        self._cell_table.cellClicked.connect(self._on_cell_type_row_clicked)
        self._cell_table.cellDoubleClicked.connect(self._on_cell_type_row_double_clicked)
        self._tabs.addTab(self._cell_table, "Cell Types")
        root.addWidget(self._tabs, 1)

        # 7. Pagination Toolbar
        paging = QHBoxLayout()
        self._result_count = QLabel("No report loaded")
        self._result_count.setStyleSheet("color: #8E9AA5; font-size: 8pt;")
        paging.addWidget(self._result_count, 1)

        self._status = QLabel("Drop = ideal_voltage - min_pg_sim")
        self._status.setStyleSheet("color: #707888; font-size: 7.5pt; font-style: italic;")
        paging.addWidget(self._status)

        self._prev_button = QPushButton("Previous")
        self._prev_button.clicked.connect(self._previous_page)
        paging.addWidget(self._prev_button)

        self._page_label = QLabel("Page 0 / 0")
        self._page_label.setStyleSheet("color: #CBD5E1; font-weight: bold; font-size: 8pt; padding: 0 4px;")
        paging.addWidget(self._page_label)

        self._next_button = QPushButton("Next")
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

        self._bin_mode_combo.blockSignals(True)
        self._bin_mode_combo.setCurrentIndex(0)
        self._bin_mode_combo.blockSignals(False)
        self._bin_step_spin.hide()
        self._bin_ranges_edit.hide()
        self._apply_bins_btn.hide()
        span = report.maximum_mv - report.minimum_mv
        self._bin_step_spin.setValue(max(round(span / 10.0, 1), 1.0) if span > 0 else 10.0)

        palette_count = len(self._map_legend_labels)
        for index, label in enumerate(self._map_legend_labels):
            low = report.minimum_mv + span * index / palette_count
            high = report.minimum_mv + span * (index + 1) / palette_count
            label.setText(f"{low:.1f}-{high:.1f}")

        self._status.setText(
            f"{report.record_count:,} rows | {report.instance_count:,} cells | drop = ideal - min_pg_sim"
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
        self._bin_mode_combo.blockSignals(True)
        self._bin_mode_combo.setCurrentIndex(0)
        self._bin_mode_combo.blockSignals(False)
        self._bin_step_spin.hide()
        self._bin_ranges_edit.hide()
        self._apply_bins_btn.hide()
        self._map_toggle.setChecked(False)
        for label in self._metric_labels.values():
            label.setText("-")
        self._status.setText("Drop = ideal_voltage - min_pg_sim")
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
            if checked and self._report is not None and getattr(self._layout_viewer, "_ir_drop_data", None) is not self._report:
                self._layout_viewer.setIRDropData(self._report)
            self._layout_viewer.setIRDropMapVisible(checked)

    def _sync_map_data(self, force_rebuild: bool = False) -> None:
        if self._layout_viewer is not None:
            if hasattr(self._layout_viewer, "setIRDropData"):
                self._layout_viewer.setIRDropData(self._report, force_rebuild=force_rebuild)
            if hasattr(self._layout_viewer, "setIRDropSelectedBin"):
                self._layout_viewer.setIRDropSelectedBin(self._selected_bin)
            self._layout_viewer.setIRDropMapVisible(self._map_toggle.isChecked())

    def _on_bin_mode_changed(self, index: int) -> None:
        if index == 0:
            self._bin_step_spin.hide()
            self._bin_ranges_edit.hide()
            self._apply_bins_btn.hide()
            self._on_reset_bins()
        elif index == 1:
            self._bin_step_spin.show()
            self._bin_ranges_edit.hide()
            self._apply_bins_btn.show()
            self._bin_step_spin.setFocus()
        elif index == 2:
            self._bin_step_spin.hide()
            self._bin_ranges_edit.show()
            self._apply_bins_btn.show()
            self._bin_ranges_edit.setFocus()

    def _on_apply_bins(self) -> None:
        if self._report is None:
            self._status.setText("Load a report first to configure histogram bins")
            return
        mode = self._bin_mode_combo.currentIndex()
        try:
            if mode == 1:
                step = self._bin_step_spin.value()
                if step <= 0.0:
                    self._status.setText("Step size must be greater than 0 mV")
                    return
                ok = self._report.set_step_size(step)
                if not ok:
                    self._status.setText("Could not calculate step bins")
                    return
                self._histogram.set_bins(self._report.bins)
                self._selected_bin = None
                self._sync_map_data(force_rebuild=True)
                self._refresh_tables()
                self._status.setText(f"Applied step size: {step:.1f} mV ({len(self._report.bins)} bins)")
            elif mode == 2:
                text = self._bin_ranges_edit.text().strip()
                if not text:
                    self._status.setText("Please enter comma-separated cutoffs (e.g. 20, 40, 60) or ranges")
                    return
                ranges = parse_range_spec(text, self._report.minimum_mv, self._report.maximum_mv)
                ok = self._report.set_custom_ranges(ranges)
                if not ok:
                    self._status.setText("Could not apply custom ranges")
                    return
                self._histogram.set_bins(self._report.bins)
                self._selected_bin = None
                self._sync_map_data(force_rebuild=True)
                self._refresh_tables()
                self._status.setText(f"Applied {len(self._report.bins)} custom ranges")
        except Exception as exc:
            self._status.setText(f"Error configuring bins: {exc}")

    def _on_reset_bins(self) -> None:
        if self._report is None:
            return
        self._report.reset_uniform_bins(24)
        self._histogram.set_bins(self._report.bins)
        self._selected_bin = None
        self._sync_map_data(force_rebuild=True)
        self._refresh_tables()
        self._status.setText("Histogram reset to default 24 uniform bins")

    def _export_data(
        self,
        file_path: Optional[str] = None,
        file_format: Optional[str] = None,
        show_dialog: bool = True,
    ) -> Optional[str]:
        """Exports the resultant filtered list of cells to CSV or Excel (.xlsx) including coordinates."""
        if self._report is None or not self._filtered_instances:
            if show_dialog:
                QMessageBox.information(self, "Export", "No cell instances match the current filters to export.")
            return None

        active_tab = self._tabs.currentIndex()
        default_name = "ir_drop_hotspots.csv" if active_tab == 0 else "ir_drop_cell_types.csv"
        if file_format == "xlsx":
            default_name = os.path.splitext(default_name)[0] + ".xlsx"

        path = file_path
        if not path and show_dialog:
            filter_str = (
                "CSV Spreadsheet (*.csv);;All Files (*.*)"
                if file_format == "csv"
                else (
                    "Excel Workbook (*.xlsx);;All Files (*.*)"
                    if file_format == "xlsx"
                    else "CSV Spreadsheet (*.csv);;Excel Workbook (*.xlsx);;All Files (*.*)"
                )
            )
            path, _ = QFileDialog.getSaveFileName(self, "Export Hotspots", default_name, filter_str)

        if not path:
            return None

        is_excel = path.lower().endswith(".xlsx")

        if active_tab == 0:
            headers = [
                "Instance Name",
                "Voltage Drop (mV)",
                "Cell Type",
                "X (um)",
                "Y (um)",
                "Placement Status",
                "IR-Drop Range (mV)",
            ]
            rows: List[List[Any]] = []
            records = self._report.records_by_instance
            bins = getattr(self._report, "bins", [])
            has_hbin_fn = hasattr(self._report, "histogram_bin_index")
            loc_fn = getattr(self._layout_viewer, "getInstanceLocation", None) if self._layout_viewer else None

            for inst_name in self._filtered_instances:
                rec = records.get(inst_name)
                drop_mv = rec[0] if rec else 0.0
                cell_type = rec[1] if rec else ""

                bin_range_str = ""
                if bins and has_hbin_fn:
                    h_idx = self._report.histogram_bin_index(drop_mv)
                    if 0 <= h_idx < len(bins):
                        b = bins[h_idx]
                        bin_range_str = f"{b.minimum_mv:.2f} - {b.maximum_mv:.2f}"

                x_val, y_val, status_val = "", "", "N/A"
                if loc_fn:
                    loc = loc_fn(inst_name)
                    if loc:
                        x_val, y_val, status_val = loc

                rows.append([inst_name, round(drop_mv, 4), cell_type, x_val, y_val, status_val, bin_range_str])
            sheet_title = "Hotspot Cells"
        else:
            headers = ["Cell Type", "Instance Count", "Mean Drop (mV)", "Worst Drop (mV)", "Worst Instance"]
            rows = []
            stats = getattr(self._report, "cell_type_stats", {})
            for name, (count, mean_drop, worst_drop, worst_inst) in stats.items():
                rows.append([name, count, round(mean_drop, 4), round(worst_drop, 4), worst_inst])
            sheet_title = "Cell Type Stats"

        try:
            if is_excel:
                self._write_excel(path, headers, rows, sheet_title=sheet_title)
            else:
                self._write_csv(path, headers, rows)
            self._status.setText(f"Exported {len(rows):,} rows to {os.path.basename(path)}")
            if show_dialog:
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Successfully exported {len(rows):,} rows to:\n{path}",
                )
            return path
        except Exception as exc:
            self._status.setText(f"Export failed: {exc}")
            if show_dialog:
                QMessageBox.critical(self, "Export Error", f"Failed to export file:\n{exc}")
            raise

    @staticmethod
    def _write_csv(path: str, headers: List[str], rows: List[List[Any]]) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

    @staticmethod
    def _write_excel(path: str, headers: List[str], rows: List[List[Any]], sheet_title: str = "IR Drop Cells") -> None:
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.utils import get_column_letter

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = sheet_title

            ws.append(headers)
            header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
            header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
            header_align = Alignment(horizontal="center", vertical="center")

            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_align

            for row in rows:
                ws.append(row)

            ws.freeze_panes = "A2"

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)

            wb.save(path)
        except ImportError:
            fallback_csv = os.path.splitext(path)[0] + ".csv"
            IRDropWidget._write_csv(fallback_csv, headers, rows)
            raise RuntimeError(f"openpyxl module is not available. Exported as CSV instead: {fallback_csv}")

    def _on_bin_selected(self, selected: Optional[IRDropBin]) -> None:
        """Instant O(1) bin filtering without scanning the entire design."""
        self._selected_bin = selected
        if self._layout_viewer is not None and hasattr(self._layout_viewer, "setIRDropSelectedBin"):
            self._layout_viewer.setIRDropSelectedBin(selected)
        self.bin_filter_changed.emit(selected)
        self._page = 0
        self._refresh_tables()

    def _reset_filters(self) -> None:
        self._selected_bin = None
        self._histogram.clear_selection()
        if self._layout_viewer is not None and hasattr(self._layout_viewer, "setIRDropSelectedBin"):
            self._layout_viewer.setIRDropSelectedBin(None)
        self.bin_filter_changed.emit(None)
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
            f"{len(self._filtered_instances):,} matching instances | {self._report.instance_count:,} total"
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
                self._last_nav_inst = (inst_name, time.monotonic())
                self.instance_selected.emit(inst_name)

    def _on_instance_row_double_clicked(self, row: int, column: int) -> None:
        item = self._instance_table.item(row, 2)
        if item is not None:
            inst_name = str(item.data(Qt.UserRole) or item.text())
            last = getattr(self, "_last_nav_inst", None)
            if last and last[0] == inst_name and (time.monotonic() - last[1]) < 0.35:
                return
        self._on_instance_row_clicked(row, column)

    def _on_cell_type_row_clicked(self, row: int, _column: int) -> None:
        """Navigates layout canvas to worst hotspot instance for the selected cell type."""
        item = self._cell_table.item(row, 4)
        if item is not None:
            inst_name = str(item.data(Qt.UserRole) or item.text())
            if inst_name:
                self._last_nav_inst = (inst_name, time.monotonic())
                self.instance_selected.emit(inst_name)

    def _on_cell_type_row_double_clicked(self, row: int, column: int) -> None:
        item = self._cell_table.item(row, 4)
        if item is not None:
            inst_name = str(item.data(Qt.UserRole) or item.text())
            last = getattr(self, "_last_nav_inst", None)
            if last and last[0] == inst_name and (time.monotonic() - last[1]) < 0.35:
                return
        self._on_cell_type_row_clicked(row, column)

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
    bin_filter_changed = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("IR-Drop Analysis", parent)
        self.setObjectName("IRDropDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setWidget(IRDropWidget(self))
        self._widget: IRDropWidget = self.widget()
        self._widget.instance_selected.connect(self.instance_selected.emit)
        self._widget.map_visibility_changed.connect(self.map_visibility_changed.emit)
        self._widget.bin_filter_changed.connect(self.bin_filter_changed.emit)

    def get_widget(self) -> IRDropWidget:
        return self._widget

    def setLayoutViewer(self, viewer: Any) -> None:
        self._widget.setLayoutViewer(viewer)

    def load_file(self, file_path: str) -> None:
        self._widget.load_file(file_path)

    def clear(self) -> None:
        self._widget.clear()