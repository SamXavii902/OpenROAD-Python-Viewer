"""Cadence Innovus / Tempus Timing Report (.tarpt, .btarpt, .rpt) Parser.

High-performance streaming parser that extracts:
- All timing paths with path ID, slack, required time, arrival time, clocks,
  startpoint, endpoint, analysis view, timing group, and failure reason.
- Data path logic levels (combinational cell count) and net lists.
- Group-level category statistics (Total, Passing, Failing, WNS, TNS, Mean, Sigma).
- Dynamic slack histogram distribution bins.
- Sum of routed wire lengths when integrated with an OpenROAD dbBlock.
"""

from __future__ import annotations

import gzip
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class TimingPin:
    """A timing point pin in the clock or data path."""
    name: str
    cell_type: str = ""
    is_net: bool = False
    edge: str = ""  # 'R' or 'F'
    delay: float = 0.0
    arrival: float = 0.0


@dataclass
class TimingPath:
    """Detailed timing path object representing one analyzed data path."""
    id: int
    status: str = "MET"  # "VIOLATED" or "MET"
    slack: float = 0.0
    required_time: float = 0.0
    arrival_time: float = 0.0
    group: str = "all"
    view: str = ""
    startpoint: str = ""
    startpoint_edge: str = ""
    endpoint: str = ""
    endpoint_edge: str = ""
    launch_clock: str = ""
    capture_clock: str = ""
    failure_reason: str = ""
    logic_level: int = 0
    cells: List[Tuple[str, str]] = field(default_factory=list)  # [(cell_master, pin_name), ...]
    nets: List[str] = field(default_factory=list)  # [net_name, ...]
    sum_wire_length: Optional[float] = None  # In microns (computed via dbBlock/dbNet)
    is_highlighted: bool = False
    highlight_color: str = "#FFE600"  # Yellow flightline color matching Cadence GUI

    @property
    def is_violation(self) -> bool:
        return self.slack < 0.0 or self.status == "VIOLATED"


@dataclass
class CategoryStats:
    """Summary metrics aggregated per timing group or for all paths."""
    name: str
    total_path: int = 0
    passing_path: int = 0
    failing_path: int = 0
    wns_mean: float = 0.0
    wns_sigma: float = 0.0
    percentile: float = 100.0  # Percentage of passing paths
    tns: float = 0.0
    wns: float = 0.0


@dataclass
class HistogramBin:
    """A single bucket in the path slack distribution histogram."""
    bin_index: int
    slack_min: float
    slack_max: float
    count: int = 0
    path_ids: List[int] = field(default_factory=list)
    is_failing: bool = False


@dataclass
class TimingReportData:
    """Complete structured timing report data model."""
    file_path: str = ""
    design_name: str = ""
    generated_by: str = ""
    generated_on: str = ""
    command: str = ""
    paths: List[TimingPath] = field(default_factory=list)
    categories: Dict[str, CategoryStats] = field(default_factory=dict)
    failure_reasons: List[Dict[str, Any]] = field(default_factory=list)
    histogram_bins: List[HistogramBin] = field(default_factory=list)

    def filter_paths(
        self,
        category: Optional[str] = None,
        slack_range: Optional[Tuple[float, float]] = None,
        search_text: str = "",
        only_failing: bool = False,
        path_ids: Optional[List[int]] = None,
    ) -> List[TimingPath]:
        """Filters paths based on category, slack range, query text, or path IDs."""
        result = self.paths

        if path_ids is not None:
            id_set = set(path_ids)
            result = [p for p in result if p.id in id_set]

        if category and category.lower() != "all":
            cat_lower = category.lower()
            result = [p for p in result if p.group.lower() == cat_lower]

        if slack_range is not None:
            s_min, s_max = slack_range
            result = [p for p in result if s_min <= p.slack <= s_max]

        if only_failing:
            result = [p for p in result if p.slack < 0.0]

        if search_text:
            st = search_text.strip().lower()
            result = [
                p for p in result
                if st in str(p.id)
                or st in p.startpoint.lower()
                or st in p.endpoint.lower()
                or st in p.view.lower()
                or st in p.failure_reason.lower()
                or st in p.launch_clock.lower()
            ]

        return result

    def compute_wire_lengths(self, chip: Any) -> None:
        """Computes sum of routed wire lengths in microns for each path using dbBlock."""
        if not chip:
            return
        if hasattr(chip, "getBlock"):
            block = chip.getBlock()
        else:
            block = chip
        if not block:
            return

        tech = getattr(chip, "getTech", lambda: getattr(block, "getTech", lambda: None)())()
        dbu_per_um = tech.getDbuPerMicron() if (tech and hasattr(tech, "getDbuPerMicron")) else 1000

        # Cache net wire lengths to avoid redundant calculations across paths
        net_lengths: Dict[str, float] = {}

        for path in self.paths:
            total_um = 0.0
            for net_name in path.nets:
                if net_name in net_lengths:
                    total_um += net_lengths[net_name]
                    continue

                net = block.findNet(net_name)
                length_um = 0.0
                if net:
                    # Sum routed wire segment lengths
                    wire_shapes = getattr(net, "getWireShapes", lambda: [])()
                    for ws in wire_shapes:
                        if not getattr(ws, "is_via", False):
                            box = ws.box
                            length_um += max(box.dx(), box.dy()) / float(dbu_per_um)

                    # If not routed yet, fallback to half-perimeter / Manhattan bounding box of terms
                    if length_um == 0.0:
                        iterms = getattr(net, "getITerms", lambda: [])()
                        if len(iterms) >= 2:
                            pts = []
                            for it in iterms:
                                inst = it.getInst()
                                if inst and inst.isPlaced():
                                    b = inst.getBBox().getBox()
                                    pts.append((b.center().x, b.center().y))
                            if len(pts) >= 2:
                                xs = [p[0] for p in pts]
                                ys = [p[1] for p in pts]
                                hpwl = ((max(xs) - min(xs)) + (max(ys) - min(ys))) / float(dbu_per_um)
                                length_um = hpwl

                net_lengths[net_name] = length_um
                total_um += length_um

            path.sum_wire_length = round(total_um, 3)


class TarptParser:
    """High-performance streaming parser for Cadence timing reports."""

    def __init__(self):
        self._path_re = re.compile(
            r"^Path\s+(\d+):\s+(VIOLATED|MET)?\s*(?:\(([-+]?[0-9]*\.?[0-9]+)\s*ns\))?\s*(.*)$"
        )
        self._view_re = re.compile(r"^\s*View:\s*(\S+)")
        self._group_re = re.compile(r"^\s*Group:\s*(\S+)")
        self._start_re = re.compile(r"^\s*Startpoint:\s*(?:\(([RF])\)\s*)?(\S+)")
        self._end_re = re.compile(r"^\s*Endpoint:\s*(?:\(([RF])\)\s*)?(\S+)")
        self._clk_re = re.compile(r"^\s*Clock:\s*(?:\(([RF])\)\s*)?(\S+)")
        self._req_re = re.compile(r"^\s*Required Time:=\s*([-+]?[0-9]*\.?[0-9]+)")
        self._arr_re = re.compile(r"^\s*Arrival:=\s*([-+]?[0-9]*\.?[0-9]+)")
        self._slack_re = re.compile(r"^\s*Slack:=\s*([-+]?[0-9]*\.?[0-9]+)")

    def parse_file(
        self,
        file_path: str,
        callback: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> TimingReportData:
        """Parses a timing report file (.tarpt, .btarpt, .rpt, .tarpt.gz)."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Timing report file not found: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_path.endswith(".gz"):
            with gzip.open(file_path, "rt", encoding="utf-8", errors="ignore") as f:
                return self._parse_lines(f, file_path, file_size=file_size, callback=callback)
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return self._parse_lines(f, file_path, file_size=file_size, callback=callback)

    def parse_text(self, text: str, file_path: str = "") -> TimingReportData:
        """Parses a timing report from an in-memory string."""
        lines = text.splitlines()
        return self._parse_lines(lines, file_path, file_size=len(text))

    def _parse_lines(
        self,
        lines_iterable,
        file_path: str,
        file_size: int = 0,
        callback: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> TimingReportData:
        start_time = time.time()
        report = TimingReportData(file_path=file_path)
        paths: List[TimingPath] = []
        cur_path: Optional[TimingPath] = None

        in_header = True
        data_path_state = "BEFORE"

        pos_cell = 132
        pos_tp = 164
        pos_adj = -1

        bytes_read = 0
        last_callback_time = start_time

        for line in lines_iterable:
            bytes_read += len(line)
            now = time.time()
            if callback and (now - last_callback_time >= 0.05):
                last_callback_time = now
                elapsed = now - start_time
                detail = f"{len(paths)} paths parsed ({elapsed:.2f}s elapsed)"
                callback("Parsing timing report", bytes_read, file_size, detail)
            # File metadata header
            if in_header:
                if line.startswith("#"):
                    if "Generated by:" in line:
                        report.generated_by = line.split("Generated by:", 1)[1].strip()
                    elif "Generated on:" in line:
                        report.generated_on = line.split("Generated on:", 1)[1].strip()
                    elif "Design:" in line:
                        report.design_name = line.split("Design:", 1)[1].strip()
                    elif "Command:" in line:
                        report.command = line.split("Command:", 1)[1].strip()
                    continue
                else:
                    in_header = False

            # Check for Path header
            pm = self._path_re.match(line)
            if pm:
                if cur_path:
                    cur_path.logic_level = len(cur_path.cells)
                    paths.append(cur_path)

                pid = int(pm.group(1))
                status = pm.group(2) or "MET"
                hdr_slack = float(pm.group(3)) if pm.group(3) else 0.0
                reason = pm.group(4).strip() if pm.group(4) else ""

                cur_path = TimingPath(
                    id=pid,
                    status=status,
                    slack=hdr_slack,
                    failure_reason=reason,
                )
                in_table = False
                data_path_state = "BEFORE"
                continue

            if not cur_path:
                continue

            # Parsing path attributes before table
            if not in_table:
                vm = self._view_re.match(line)
                if vm:
                    cur_path.view = vm.group(1)
                    continue

                gm = self._group_re.match(line)
                if gm:
                    cur_path.group = gm.group(1)
                    continue

                sm = self._start_re.match(line)
                if sm:
                    cur_path.startpoint_edge = sm.group(1) or ""
                    cur_path.startpoint = sm.group(2)
                    continue

                em = self._end_re.match(line)
                if em:
                    cur_path.endpoint_edge = em.group(1) or ""
                    cur_path.endpoint = em.group(2)
                    continue

                cm = self._clk_re.match(line)
                if cm:
                    if not cur_path.launch_clock:
                        cur_path.launch_clock = cm.group(2)
                    elif not cur_path.capture_clock:
                        cur_path.capture_clock = cm.group(2)
                    continue

                rm = self._req_re.match(line)
                if rm:
                    cur_path.required_time = float(rm.group(1))
                    continue

                am = self._arr_re.match(line)
                if am and cur_path.arrival_time == 0.0:
                    cur_path.arrival_time = float(am.group(1))
                    continue

                slm = self._slack_re.match(line)
                if slm:
                    cur_path.slack = float(slm.group(1))
                    if cur_path.slack < 0.0:
                        cur_path.status = "VIOLATED"
                    continue

                if "Timing Point" in line and "Cell" in line:
                    pos_cell = line.find("Cell")
                    pos_tp = line.find("Timing Point")
                    pos_adj = line.find("Adjustment")
                    in_table = True
                    continue
            else:
                # Parsing rows inside Timing Path table
                if (
                    line.startswith("Other End Arrival Time:")
                    or line.startswith("Other End Path:")
                    or line.startswith("Path ")
                ):
                    in_table = False
                    continue

                if line.startswith("#") or not line.strip():
                    continue

                is_fixed_width = (pos_tp - pos_cell >= 20) and (pos_cell > 50)
                if is_fixed_width and len(line) > pos_tp:
                    cell = line[pos_cell:pos_tp].strip() if len(line) > pos_cell else ""
                    tp = (
                        (line[pos_tp:pos_adj].strip() if pos_adj != -1 else line[pos_tp:].strip())
                        if len(line) > pos_tp
                        else ""
                    )
                else:
                    parts = line.split()
                    if len(parts) >= 2:
                        tp = parts[-1]
                        cell = parts[-2]
                    else:
                        continue

                start_inst = (
                    cur_path.startpoint.rsplit("/", 1)[0]
                    if "/" in cur_path.startpoint
                    else cur_path.startpoint
                )
                end_inst = (
                    cur_path.endpoint.rsplit("/", 1)[0]
                    if "/" in cur_path.endpoint
                    else cur_path.endpoint
                )

                if data_path_state == "BEFORE":
                    if (
                        tp == cur_path.startpoint
                        or (start_inst and tp.startswith(start_inst + "/"))
                    ):
                        data_path_state = "IN_DATA"
                elif data_path_state == "IN_DATA":
                    if tp == cur_path.endpoint or (end_inst and tp == cur_path.endpoint):
                        data_path_state = "AFTER"
                    elif cell == "(net)":
                        cur_path.nets.append(tp)
                    elif start_inst and tp.startswith(start_inst + "/"):
                        # Launch register output pin (e.g. reg0/Q)
                        pass
                    else:
                        # Output pin of combinational logic gate
                        if any(
                            tp.endswith("/" + p)
                            for p in ("Z", "Y", "OUT", "QN", "Q", "X", "S", "CO", "CON", "SO")
                        ):
                            cur_path.cells.append((cell, tp))

        # Append last path
        if cur_path:
            cur_path.logic_level = len(cur_path.cells)
            paths.append(cur_path)

        report.paths = paths

        if callback:
            now = time.time()
            elapsed = now - start_time
            callback("Aggregating statistics", file_size, file_size, f"{len(paths)} paths ({elapsed:.2f}s elapsed)")

        # Calculate category statistics
        self._aggregate_statistics(report)

        # Build histogram bins
        self._build_histogram(report)

        # Build failure reasons table
        self._build_failure_reasons(report)

        if callback:
            now = time.time()
            elapsed = now - start_time
            callback("Complete", file_size, file_size, f"{len(paths)} paths loaded in {elapsed:.2f}s")

        return report

    def _aggregate_statistics(self, report: TimingReportData) -> None:
        """Aggregates CategoryStats for 'all' and each individual group."""
        groups: Dict[str, List[TimingPath]] = {}
        for p in report.paths:
            grp = p.group if p.group else "all"
            groups.setdefault(grp, []).append(p)

        def make_stats(name: str, p_list: List[TimingPath]) -> CategoryStats:
            if not p_list:
                return CategoryStats(name=name)

            total = len(p_list)
            failing = [p for p in p_list if p.slack < 0.0]
            passing = [p for p in p_list if p.slack >= 0.0]
            wns = min(p.slack for p in p_list)
            tns = sum(p.slack for p in failing)
            pct = round((len(passing) / float(total)) * 100.0, 1)

            slacks = [p.slack for p in p_list]
            mean_slack = sum(slacks) / float(total)
            variance = sum((s - mean_slack) ** 2 for s in slacks) / float(total)
            sigma = math.sqrt(variance)

            # In Cadence Tempus/Innovus:
            # WNS Mean is the worst slack of the group (or mean of failing slacks)
            return CategoryStats(
                name=name,
                total_path=total,
                passing_path=len(passing),
                failing_path=len(failing),
                wns=round(wns, 4),
                wns_mean=round(wns, 4),
                wns_sigma=round(sigma, 4),
                percentile=pct,
                tns=round(tns, 4),
            )

        report.categories["all"] = make_stats("all", report.paths)
        for grp, p_list in groups.items():
            report.categories[grp] = make_stats(grp, p_list)

    def _build_histogram(self, report: TimingReportData, num_bins: int = 15) -> None:
        """Computes equal-width slack distribution bins."""
        if not report.paths:
            report.histogram_bins = []
            return

        slacks = [p.slack for p in report.paths]
        min_slack = min(slacks)
        max_slack = max(slacks)

        if min_slack == max_slack:
            bin_obj = HistogramBin(
                bin_index=0,
                slack_min=min_slack - 0.01,
                slack_max=max_slack + 0.01,
                count=len(report.paths),
                path_ids=[p.id for p in report.paths],
                is_failing=(min_slack < 0.0),
            )
            report.histogram_bins = [bin_obj]
            return

        # Slight padding to include edge points cleanly
        span = max_slack - min_slack
        step = span / float(num_bins)

        bins: List[HistogramBin] = []
        for i in range(num_bins):
            b_min = min_slack + i * step
            b_max = min_slack + (i + 1) * step
            bins.append(
                HistogramBin(
                    bin_index=i,
                    slack_min=round(b_min, 4),
                    slack_max=round(b_max, 4),
                    count=0,
                    path_ids=[],
                    is_failing=(b_max <= 0.0 or (b_min < 0.0 and b_max <= 0.0001)),
                )
            )

        for p in report.paths:
            idx = int((p.slack - min_slack) / step)
            if idx >= num_bins:
                idx = num_bins - 1
            elif idx < 0:
                idx = 0
            bins[idx].count += 1
            bins[idx].path_ids.append(p.id)

        report.histogram_bins = bins

    def _build_failure_reasons(self, report: TimingReportData) -> None:
        """Groups failure reasons and violation counts."""
        reason_map: Dict[str, Dict[str, Any]] = {}
        for p in report.paths:
            # Extract simplified violation category from failure reason string
            raw = p.failure_reason or "Setup Check"
            if "Setup Check" in raw:
                r_key = "Setup Check"
            elif "Hold Check" in raw:
                r_key = "Hold Check"
            elif "Recovery Check" in raw:
                r_key = "Recovery Check"
            elif "Removal Check" in raw:
                r_key = "Removal Check"
            else:
                r_key = raw.split(" with Pin ")[0] if " with Pin " in raw else raw

            if r_key not in reason_map:
                reason_map[r_key] = {
                    "reason": r_key,
                    "count": 0,
                    "failing_count": 0,
                    "wns": 0.0,
                    "path_ids": [],
                }
            entry = reason_map[r_key]
            entry["count"] += 1
            if p.slack < 0:
                entry["failing_count"] += 1
                if entry["failing_count"] == 1 or p.slack < entry["wns"]:
                    entry["wns"] = round(p.slack, 4)
            entry["path_ids"].append(p.id)

        report.failure_reasons = list(reason_map.values())
