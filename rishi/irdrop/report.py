"""Streaming parser and compact analytics for per-instance IR-drop reports."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


IR_DROP_PALETTE = ("#39B7A5", "#419BC4", "#5E7DCE", "#8B68C6", "#D8588A")
IRDropRecord = tuple[float, str]


class _RecordValueView(Mapping[str, float]):
    def __init__(self, records: Dict[str, IRDropRecord]):
        self._records = records

    def __getitem__(self, instance: str) -> float:
        return self._records[instance][0]

    def __iter__(self) -> Iterator[str]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)


class _RecordCellTypeView(Mapping[str, str]):
    def __init__(self, records: Dict[str, IRDropRecord]):
        self._records = records

    def __getitem__(self, instance: str) -> str:
        return self._records[instance][1]

    def __iter__(self) -> Iterator[str]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)


@dataclass(frozen=True)
class IRDropBin:
    """An equal-width IR-drop range in millivolts."""

    minimum_mv: float
    maximum_mv: float
    count: int
    bin_index: int = 0


@dataclass
class IRDropReportData:
    """Per-instance worst-case voltage drop and summary statistics."""

    file_path: str = ""
    records_by_instance: Dict[str, IRDropRecord] = field(default_factory=dict)
    ordered_instances: List[str] = field(default_factory=list)
    cell_type_stats: Dict[str, tuple[int, float, float, str]] = field(default_factory=dict)
    bins: List[IRDropBin] = field(default_factory=list)
    bin_instances: List[List[str]] = field(default_factory=list)
    palette_bin_instances: List[List[str]] = field(default_factory=list)
    instances_by_cell_type: Dict[str, List[str]] = field(default_factory=dict)
    record_count: int = 0
    minimum_mv: float = 0.0
    mean_mv: float = 0.0
    percentile_95_mv: float = 0.0
    maximum_mv: float = 0.0

    @property
    def instance_count(self) -> int:
        return len(self.records_by_instance)

    @property
    def values_by_instance(self) -> Mapping[str, float]:
        return _RecordValueView(self.records_by_instance)

    @property
    def cell_type_by_instance(self) -> Mapping[str, str]:
        return _RecordCellTypeView(self.records_by_instance)

    def color_index(self, value_mv: float) -> int:
        if not self.bins:
            return 0
        if self.maximum_mv <= self.minimum_mv:
            return len(IR_DROP_PALETTE) // 2
        fraction = (value_mv - self.minimum_mv) / (self.maximum_mv - self.minimum_mv)
        return min(max(int(fraction * len(IR_DROP_PALETTE)), 0), len(IR_DROP_PALETTE) - 1)


class IRDropParser:
    """Parses reports with whitespace-separated min_pg_sim and ideal_voltage columns."""

    HISTOGRAM_BIN_COUNT = 24

    def parse_file(
        self,
        file_path: str,
        callback: Optional[Callable[[int, int], None]] = None,
    ) -> IRDropReportData:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"IR-drop report not found: {file_path}")

        total_bytes = os.path.getsize(file_path)
        records: Dict[str, IRDropRecord] = {}
        record_count = 0
        last_progress = 0
        bytes_read = 0

        with open(file_path, "rb") as report_file:
            for raw_line in report_file:
                bytes_read += len(raw_line)
                fields = raw_line.split()
                if len(fields) >= 10 and not fields[0].startswith(b"#"):
                    try:
                        simulated_voltage = float(fields[2])
                        ideal_voltage = float(fields[6])
                        cell_type = sys.intern(fields[8].decode("utf-8", errors="replace"))
                        instance = fields[9].decode("utf-8", errors="replace").strip()
                        if ":" in instance:
                            instance = instance.split(":", 1)[0]
                        inst_upper = instance.upper()
                        for pin_suffix in ("/VDD", "/VSS", "/GND", "/VPWR", "/VGND", "/VDDIO", "/VSSIO", "/VDD_CORE", "/VSS_CORE"):
                            if inst_upper.endswith(pin_suffix) and len(instance) > len(pin_suffix):
                                instance = instance[:-len(pin_suffix)]
                                break
                        drop_mv = round((ideal_voltage - simulated_voltage) * 1000.0, 6)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not instance:
                        continue
                    previous = records.get(instance)
                    if previous is None or drop_mv > previous[0]:
                        records[instance] = (drop_mv, cell_type)
                    record_count += 1

                if callback and bytes_read - last_progress >= 8 * 1024 * 1024:
                    callback(bytes_read, total_bytes)
                    last_progress = bytes_read

        data = IRDropReportData(
            file_path=file_path,
            records_by_instance=records,
            record_count=record_count,
        )
        self._compute_statistics(data)
        if callback:
            callback(total_bytes, total_bytes)
        return data

    def _compute_statistics(self, data: IRDropReportData) -> None:
        records = data.records_by_instance
        values = _RecordValueView(records)
        if not values:
            data.ordered_instances = []
            data.bins = []
            return

        data.ordered_instances = sorted(values, key=values.__getitem__, reverse=True)
        data.minimum_mv = min(values.values())
        data.maximum_mv = max(values.values())
        data.mean_mv = sum(values.values()) / len(values)

        bin_count = self.HISTOGRAM_BIN_COUNT
        span = data.maximum_mv - data.minimum_mv
        counts = [0] * bin_count
        bin_instances: List[List[str]] = [[] for _ in range(bin_count)]
        palette_instances: List[List[str]] = [[] for _ in range(len(IR_DROP_PALETTE))]
        instances_by_cell_type: Dict[str, List[str]] = {}

        if span == 0.0:
            counts[-1] = len(values)
            bin_instances[-1] = list(data.ordered_instances)
            palette_instances[len(IR_DROP_PALETTE) // 2] = list(data.ordered_instances)
            data.percentile_95_mv = data.maximum_mv
        else:
            for instance in data.ordered_instances:
                value = values[instance]
                idx = min(int((value - data.minimum_mv) / span * bin_count), bin_count - 1)
                counts[idx] += 1
                bin_instances[idx].append(instance)

                pal_idx = min(max(int((value - data.minimum_mv) / span * len(IR_DROP_PALETTE)), 0), len(IR_DROP_PALETTE) - 1)
                palette_instances[pal_idx].append(instance)

            rank = 0.95 * (len(values) - 1)
            lower_rank = int(rank)
            upper_rank = min(lower_rank + 1, len(values) - 1)
            lower_value = values[data.ordered_instances[len(values) - 1 - lower_rank]]
            upper_value = values[data.ordered_instances[len(values) - 1 - upper_rank]]
            data.percentile_95_mv = lower_value + (upper_value - lower_value) * (rank - lower_rank)

        data.bins = [
            IRDropBin(
                minimum_mv=data.minimum_mv + span * idx / bin_count,
                maximum_mv=data.minimum_mv + span * (idx + 1) / bin_count,
                count=counts[idx],
                bin_index=idx,
            )
            for idx in range(bin_count)
        ]
        data.bin_instances = bin_instances
        data.palette_bin_instances = palette_instances

        type_accumulators: Dict[str, List[object]] = {}
        for instance, (value, cell_type) in records.items():
            aggregate = type_accumulators.setdefault(cell_type, [0, 0.0, float("-inf"), ""])
            aggregate[0] += 1
            aggregate[1] += value
            if value > aggregate[2]:
                aggregate[2] = value
                aggregate[3] = instance
            instances_by_cell_type.setdefault(cell_type, []).append(instance)

        data.cell_type_stats = {
            name: (int(stats[0]), float(stats[1]) / int(stats[0]), float(stats[2]), str(stats[3]))
            for name, stats in type_accumulators.items()
        }
        data.instances_by_cell_type = instances_by_cell_type