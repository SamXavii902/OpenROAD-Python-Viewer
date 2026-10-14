"""Spatial index implementation ported from RISHI gui/src/search.cpp."""

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

    def build(self, block: dbBlock, callback: Optional[Callable[[str, int, int], None]] = None) -> None:
        """Indexes all block objects for fast viewport querying."""
        self._block = block
        self._insts = list(block.getInsts())
        n_insts = len(self._insts)

        if callback:
            callback("Instances", 0, max(n_insts, 1))

        # Index instances
        if self._insts:
            boxes = []
            is_macro_list = []
            for idx, inst in enumerate(self._insts):
                if callback and idx > 0 and idx % 20000 == 0:
                    callback("Instances", idx, n_insts)
                bbox = inst.getBBox().getBox()
                boxes.append([bbox.xMin(), bbox.yMin(), bbox.xMax(), bbox.yMax()])
                master = inst.getMaster()
                name_l = master.getName().lower()
                is_m = (
                    master.isBlock()
                    or master.isPad()
                    or master.getWidth() > 15000
                    or master.getHeight() > 15000
                    or any(k in name_l for k in ("ram", "sram", "rom", "fakeram", "pll", "fifo", "mem"))
                )
                is_macro_list.append(is_m)
            self._inst_boxes = np.array(boxes, dtype=np.int32)
            self._inst_is_macro = np.array(is_macro_list, dtype=bool)
            self._inst_sizes = np.maximum(
                self._inst_boxes[:, 2] - self._inst_boxes[:, 0],
                self._inst_boxes[:, 3] - self._inst_boxes[:, 1],
            )
        else:
            self._inst_boxes = np.empty((0, 4), dtype=np.int32)
            self._inst_is_macro = np.empty((0,), dtype=bool)
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
            boxes = [[s.box.xMin(), s.box.yMin(), s.box.xMax(), s.box.yMax(), 1 if s.is_via else 0] for s in shapes]
            arr = np.array(boxes, dtype=np.int32)
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
            boxes = [[o.getBox().xMin(), o.getBox().yMin(), o.getBox().xMax(), o.getBox().yMax()] for o in obs_list]
            self._obs_boxes_by_layer[lname] = np.array(boxes, dtype=np.int32)

        # Index blockages
        self._blockages = list(block.getBlockages())
        if self._blockages:
            boxes = [[b.getBox().xMin(), b.getBox().yMin(), b.getBox().xMax(), b.getBox().yMax()] for b in self._blockages]
            self._blockage_boxes = np.array(boxes, dtype=np.int32)
        else:
            self._blockage_boxes = np.empty((0, 4), dtype=np.int32)

        # Index rows
        self._rows = list(block.getRows())
        if self._rows:
            boxes = []
            for r in self._rows:
                rb = r.getBBox()
                boxes.append([rb.xMin(), rb.yMin(), rb.xMax(), rb.yMax()])
            self._row_boxes = np.array(boxes, dtype=np.int32)
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
