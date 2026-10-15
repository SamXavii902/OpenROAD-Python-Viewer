"""Spatial index implementation ported from RISHI gui/src/search.cpp."""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Dict, Optional, Callable
import numpy as np
from rishi.odb.geom import Rect
from rishi.odb.tech import dbTechLayer
from rishi.odb.block import (
    dbBlock,
    dbInst,
    dbObstruction,
    dbBlockage,
    dbFill,
    dbRow,
    RouteShape,
)


class SpatialSearch:
    """Provides fast spatial queries for instances, routes, obstructions, and rows

    matching RISHI gui::Search.
    """

    def __init__(self):
        self._block: Optional[dbBlock] = None
        # Instance bounding boxes: [x1, y1, x2, y2]
        self._insts: List[dbInst] = []
        self._inst_boxes: Optional[np.ndarray] = None
        self._inst_is_macro: Optional[np.ndarray] = None
        self._inst_is_filler: Optional[np.ndarray] = None

        # Per-layer routing shapes: [x1, y1, x2, y2, is_via, shape_idx]
        self._route_shapes_by_layer: Dict[str, List[RouteShape]] = {}
        self._route_boxes_by_layer: Dict[str, np.ndarray] = {}

        # Per-layer obstructions
        self._obs_by_layer: Dict[str, List[dbObstruction]] = {}
        self._obs_boxes_by_layer: Dict[str, np.ndarray] = {}

        # Placement blockages
        self._blockages: List[dbBlockage] = []
        self._blockage_boxes: Optional[np.ndarray] = None

        # Rows
        self._rows: List[dbRow] = []
        self._row_boxes: Optional[np.ndarray] = None

    def clear(self) -> None:
        """Clears all indexed objects and frees numpy arrays and database references from memory."""
        self._block = None
        self._insts.clear()
        self._inst_boxes = None
        self._inst_is_macro = None
        self._inst_is_filler = None
        self._route_shapes_by_layer.clear()
        self._route_boxes_by_layer.clear()
        self._obs_by_layer.clear()
        self._obs_boxes_by_layer.clear()
        self._blockages.clear()
        self._blockage_boxes = None
        self._rows.clear()
        self._row_boxes = None

    def build(self, block: dbBlock, callback: Optional[Callable[[str, int, int], None]] = None) -> None:
        """Indexes all block objects for fast viewport querying utilizing all available CPU cores."""
        self._block = block
        self._insts = list(block.getInsts())
        n_insts = len(self._insts)

        if callback:
            callback("Instances", 0, max(n_insts, 1))

        # Index instances
        if self._insts:
            boxes = np.empty((n_insts, 4), dtype=np.int32)
            is_macro_list = np.empty(n_insts, dtype=bool)
            is_filler_list = np.empty(n_insts, dtype=bool)

            num_workers = min(16, max(1, os.cpu_count() or 1))
            chunk_size = max(25000, (n_insts + num_workers - 1) // num_workers)

            def _process_inst_chunk(start_idx: int, end_idx: int):
                for i in range(start_idx, end_idx):
                    inst = self._insts[i]
                    b = inst.getBBox().getBox()
                    boxes[i, 0] = b.xMin()
                    boxes[i, 1] = b.yMin()
                    boxes[i, 2] = b.xMax()
                    boxes[i, 3] = b.yMax()
                    m = inst.getMaster()
                    is_macro_list[i] = m.isMacro()
                    is_filler_list[i] = m.isFiller()

            if n_insts > 30000 and num_workers > 1:
                with ThreadPoolExecutor(max_workers=num_workers) as pool:
                    futures = []
                    for c_start in range(0, n_insts, chunk_size):
                        c_end = min(c_start + chunk_size, n_insts)
                        futures.append(pool.submit(_process_inst_chunk, c_start, c_end))
                    for f in futures:
                        f.result()
            else:
                _process_inst_chunk(0, n_insts)

            self._inst_boxes = boxes
            self._inst_is_macro = is_macro_list
            self._inst_is_filler = is_filler_list
            self._inst_sizes = np.maximum(
                self._inst_boxes[:, 2] - self._inst_boxes[:, 0],
                self._inst_boxes[:, 3] - self._inst_boxes[:, 1],
            )
        else:
            self._inst_boxes = np.empty((0, 4), dtype=np.int32)
            self._inst_is_macro = np.empty((0,), dtype=bool)
            self._inst_is_filler = np.empty((0,), dtype=bool)
            self._inst_sizes = np.empty((0,), dtype=np.int32)

        if callback:
            callback("Instances", n_insts, max(n_insts, 1))

        # Per-layer routing shapes: [x1, y1, x2, y2, is_via, shape_idx]
        self._route_shapes_by_layer.clear()
        self._route_boxes_by_layer.clear()
        self._route_sizes_by_layer: Dict[str, np.ndarray] = {}
        layer_shapes: Dict[str, List[RouteShape]] = {}

        nets = list(block.getNets())
        n_nets = len(nets)
        if callback:
            callback("Routing Nets", 0, max(n_nets, 1))

        for idx, net in enumerate(nets):
            if callback and idx > 0 and idx % 20000 == 0:
                callback("Routing Nets", idx, n_nets)
            for shape in net.getWireShapes():
                lname = shape.layer.getName().upper()
                layer_shapes.setdefault(lname, []).append(shape)
            for shape in net.getSpecialWireShapes():
                lname = shape.layer.getName().upper()
                layer_shapes.setdefault(lname, []).append(shape)

        if callback:
            callback("Routing Nets", n_nets, max(n_nets, 1))

        n_layers = len(layer_shapes)
        for l_idx, (lname, shapes) in enumerate(layer_shapes.items()):
            if callback:
                callback(f"Layer {lname} ({len(shapes):,} shapes)", l_idx, max(n_layers, 1))
            self._route_shapes_by_layer[lname] = shapes
            n_shapes = len(shapes)
            arr = np.empty((n_shapes, 5), dtype=np.int32)
            for s_i, s in enumerate(shapes):
                b = s.box
                arr[s_i, 0] = b.xMin()
                arr[s_i, 1] = b.yMin()
                arr[s_i, 2] = b.xMax()
                arr[s_i, 3] = b.yMax()
                arr[s_i, 4] = 1 if s.is_via else 0
            self._route_boxes_by_layer[lname] = arr
            self._route_sizes_by_layer[lname] = np.maximum(arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1])

        if callback:
            callback("Layers", n_layers, max(n_layers, 1))

        # Index obstructions by layer
        self._obs_by_layer.clear()
        self._obs_boxes_by_layer.clear()
        layer_obs: Dict[str, List[dbObstruction]] = {}
        for obs in block.getObstructions():
            lname = obs.getTechLayer().getName().upper()
            layer_obs.setdefault(lname, []).append(obs)

        for lname, obs_list in layer_obs.items():
            self._obs_by_layer[lname] = obs_list
            n_obs = len(obs_list)
            arr = np.empty((n_obs, 4), dtype=np.int32)
            for o_i, o in enumerate(obs_list):
                b = o.getBox()
                arr[o_i, 0] = b.xMin()
                arr[o_i, 1] = b.yMin()
                arr[o_i, 2] = b.xMax()
                arr[o_i, 3] = b.yMax()
            self._obs_boxes_by_layer[lname] = arr

        # Index blockages
        self._blockages = list(block.getBlockages())
        if self._blockages:
            n_blk = len(self._blockages)
            arr = np.empty((n_blk, 4), dtype=np.int32)
            for b_i, b in enumerate(self._blockages):
                box = b.getBox()
                arr[b_i, 0] = box.xMin()
                arr[b_i, 1] = box.yMin()
                arr[b_i, 2] = box.xMax()
                arr[b_i, 3] = box.yMax()
            self._blockage_boxes = arr
        else:
            self._blockage_boxes = np.empty((0, 4), dtype=np.int32)

        # Index rows
        self._rows = list(block.getRows())
        if self._rows:
            n_rows = len(self._rows)
            arr = np.empty((n_rows, 4), dtype=np.int32)
            for r_i, r in enumerate(self._rows):
                rb = r.getBBox()
                arr[r_i, 0] = rb.xMin()
                arr[r_i, 1] = rb.yMin()
                arr[r_i, 2] = rb.xMax()
                arr[r_i, 3] = rb.yMax()
            self._row_boxes = arr
        else:
            self._row_boxes = np.empty((0, 4), dtype=np.int32)

    def searchInsts(
        self,
        block: dbBlock,
        xMin: int,
        yMin: int,
        xMax: int,
        yMax: int,
        min_size: int = 0,
        show_std_cells: bool = True,
        show_macros: bool = True,
    ) -> List[dbInst]:
        """Finds instances overlapping the query bounds with size >= min_size."""
        if self._inst_boxes is None or len(self._inst_boxes) == 0:
            return []

        # Vectorized AABB intersection
        boxes = self._inst_boxes
        mask = (
            (boxes[:, 2] >= xMin)
            & (boxes[:, 0] <= xMax)
            & (boxes[:, 3] >= yMin)
            & (boxes[:, 1] <= yMax)
        )
        if not show_std_cells and not show_macros:
            return []
        elif not show_std_cells:
            mask &= self._inst_is_macro
        elif not show_macros:
            mask &= (~self._inst_is_macro)
            if min_size > 0:
                mask &= (self._inst_sizes >= min_size)
        else:
            # Both visible: macros always pass regardless of min_size, standard cells must meet min_size
            if min_size > 0:
                mask &= (self._inst_is_macro | (self._inst_sizes >= min_size))

        indices = np.where(mask)[0]
        return [self._insts[i] for i in indices]

    def searchBoxShapes(
        self,
        block: dbBlock,
        layer: dbTechLayer,
        xMin: int,
        yMin: int,
        xMax: int,
        yMax: int,
        shape_limit: int = 0,
    ) -> List[Tuple[Rect, bool]]:
        """Finds routing shapes (wires and vias) on layer overlapping query bounds."""
        lname = layer.getName().upper()
        if lname not in self._route_boxes_by_layer:
            return []

        boxes = self._route_boxes_by_layer[lname]
        mask = (
            (boxes[:, 2] >= xMin)
            & (boxes[:, 0] <= xMax)
            & (boxes[:, 3] >= yMin)
            & (boxes[:, 1] <= yMax)
        )
        if shape_limit > 0 and lname in self._route_sizes_by_layer:
            mask &= (self._route_sizes_by_layer[lname] >= shape_limit)

        indices = np.where(mask)[0]
        results = []
        for i in indices:
            row = boxes[i]
            rect = Rect(int(row[0]), int(row[1]), int(row[2]), int(row[3]))
            is_via = bool(row[4])
            results.append((rect, is_via))
        return results

    def searchObstructions(
        self,
        block: dbBlock,
        layer: dbTechLayer,
        xMin: int,
        yMin: int,
        xMax: int,
        yMax: int,
        shape_limit: int = 0,
    ) -> List[dbObstruction]:
        lname = layer.getName().upper()
        if lname not in self._obs_boxes_by_layer:
            return []

        boxes = self._obs_boxes_by_layer[lname]
        mask = (
            (boxes[:, 2] >= xMin)
            & (boxes[:, 0] <= xMax)
            & (boxes[:, 3] >= yMin)
            & (boxes[:, 1] <= yMax)
        )
        indices = np.where(mask)[0]
        obs_list = self._obs_by_layer[lname]
        return [obs_list[i] for i in indices]

    def searchBlockages(
        self,
        block: dbBlock,
        xMin: int,
        yMin: int,
        xMax: int,
        yMax: int,
        shape_limit: int = 0,
    ) -> List[dbBlockage]:
        if self._blockage_boxes is None or len(self._blockage_boxes) == 0:
            return []

        boxes = self._blockage_boxes
        mask = (
            (boxes[:, 2] >= xMin)
            & (boxes[:, 0] <= xMax)
            & (boxes[:, 3] >= yMin)
            & (boxes[:, 1] <= yMax)
        )
        indices = np.where(mask)[0]
        return [self._blockages[i] for i in indices]

    def searchRows(
        self,
        block: dbBlock,
        xMin: int,
        yMin: int,
        xMax: int,
        yMax: int,
        min_size: int = 0,
    ) -> List[dbRow]:
        if self._row_boxes is None or len(self._row_boxes) == 0:
            return []

        boxes = self._row_boxes
        mask = (
            (boxes[:, 2] >= xMin)
            & (boxes[:, 0] <= xMax)
            & (boxes[:, 3] >= yMin)
            & (boxes[:, 1] <= yMax)
        )
        indices = np.where(mask)[0]
        return [self._rows[i] for i in indices]
