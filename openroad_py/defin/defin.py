"""DEF file parser ported from OpenROAD odb/src/defin/*."""

import os
from typing import Optional, List, Tuple, Callable
from openroad_py.lefin.tokenizer import tokenize_stream, TokenReader
from openroad_py.odb.geom import Rect, Polygon, Point
from openroad_py.odb.types import (
    dbOrientType,
    dbPlacementStatus,
    dbSigType,
    dbTechLayerDir,
    dbWireType,
)
from openroad_py.odb.tech import dbTech, dbTechLayer, dbTechVia, dbSite
from openroad_py.odb.lib import dbMaster, dbBox
from openroad_py.odb.block import (
    dbBlock,
    dbInst,
    dbNet,
    dbBTerm,
    dbBPin,
    dbRow,
    dbTrackGrid,
    dbObstruction,
    dbBlockage,
    dbFill,
    RouteShape,
)
from openroad_py.odb.database import dbDatabase, dbChip


class DefParser:
    """Parses standard DEF files (versions 5.5 - 5.8) into OpenDB dbBlock structures."""

    def __init__(self, db: dbDatabase):
        self._db: dbDatabase = db
        self._tech: Optional[dbTech] = db.getTech()
        if self._tech is None:
            self._tech = dbTech()
            db.setTech(self._tech)
        self._block: Optional[dbBlock] = None
        self._dbu: int = self._tech.getDbuPerMicron()

    def dbu(self, val: float) -> int:
        return round(float(val))

    def parse_file(self, filepath: str, callback: Optional[Callable] = None) -> dbBlock:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"DEF file not found: {filepath}")

        # Auto-resolve git symlinks on Windows
        if os.path.getsize(filepath) < 512:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
                if (first_line.startswith("../") or first_line.startswith("./")) and first_line.endswith(".def"):
                    resolved = os.path.normpath(os.path.join(os.path.dirname(filepath), first_line))
                    if os.path.exists(resolved):
                        filepath = resolved

        design_name = os.path.splitext(os.path.basename(filepath))[0]
        self._block = dbBlock(self._tech, design_name)
        chip = dbChip(self._db, self._block)
        self._db.setChip(chip)
        self._callback = callback

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = TokenReader(tokenize_stream(f))
            self._parse_top(reader)

        return self._block

    def _parse_top(self, reader: TokenReader) -> None:
        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "DESIGN":
                design_name = reader.next()
                self._block.setName(design_name)
                reader.read_until_semicolon()
            elif u == "UNITS":
                self._parse_units(reader)
            elif u == "DIEAREA":
                self._parse_diearea(reader)
            elif u == "ROW":
                self._parse_row(reader)
            elif u == "TRACKS":
                self._parse_tracks(reader)
            elif u == "VIAS":
                self._parse_vias(reader)
            elif u == "COMPONENTS":
                self._parse_components(reader)
            elif u == "PINS":
                self._parse_pins(reader)
            elif u == "NETS":
                self._parse_nets(reader, is_special=False)
            elif u == "SPECIALNETS":
                self._parse_nets(reader, is_special=True)
            elif u == "BLOCKAGES":
                self._parse_blockages(reader)
            elif u == "FILLS":
                self._parse_fills(reader)
            elif u in ("PROPERTYDEFINITIONS", "GROUPS", "REGIONS", "SCANCHAINS", "NONDEFAULTRULES", "STYLES", "SLOTS", "FENCES"):
                self._skip_section(reader, u)
            elif u in ("VERSION", "NAMESCASESENSITIVE", "DIVIDERCHAR", "BUSBITCHARS", "GCELLGRID"):
                reader.read_until_semicolon()
            elif u == "END":
                end_target = reader.next().upper() if reader.has_next() else ""
                if reader.peek() == ";":
                    reader.next()
                if end_target in ("DESIGN", self._block.getName().upper()):
                    break
            else:
                pass

    def _skip_section(self, reader: TokenReader, section_name: str) -> None:
        target = section_name.upper()
        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.has_next() and reader.peek().upper() == target:
                    reader.next()
                    if reader.peek() == ";":
                        reader.next()
                    break

    def _parse_units(self, reader: TokenReader) -> None:
        tokens = reader.read_until_semicolon()
        for i, t in enumerate(tokens):
            if t.upper() == "MICRONS" and i + 1 < len(tokens):
                dbu_val = int(tokens[i + 1])
                self._dbu = dbu_val
                break

    def _parse_diearea(self, reader: TokenReader) -> None:
        tokens = reader.read_until_semicolon()
        pts = []
        i = 0
        while i < len(tokens):
            if tokens[i] == "(":
                x = int(tokens[i + 1])
                y = int(tokens[i + 2])
                pts.append(Point(x, y))
                i += 4  # ( x y )
            else:
                i += 1

        if len(pts) == 2:
            self._block.setDieArea(Rect(pts[0].x, pts[0].y, pts[1].x, pts[1].y))
        elif len(pts) > 2:
            poly = Polygon(pts)
            self._block.setDieAreaPolygon(poly)

    def _parse_row(self, reader: TokenReader) -> None:
        row_name = reader.next()
        site_name = reader.next()
        site = self._tech.findSite(site_name)
        if site is None:
            site = dbSite(site_name)

        orig_x = int(reader.next())
        orig_y = int(reader.next())
        orient_str = reader.next()
        orient = dbOrientType.from_str(orient_str)

        direction = dbTechLayerDir.HORIZONTAL
        site_count = 1
        spacing = site.getWidth()

        tokens = reader.read_until_semicolon()
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx].upper()
            if tok == "DO":
                num_x = int(tokens[idx + 1])
                idx += 2
                if idx < len(tokens) and tokens[idx].upper() == "BY":
                    num_y = int(tokens[idx + 1])
                    idx += 2
                if idx < len(tokens) and tokens[idx].upper() == "STEP":
                    step_x = int(tokens[idx + 1])
                    step_y = int(tokens[idx + 2])
                    site_count = max(num_x, 1)
                    spacing = step_x if step_x > 0 else site.getWidth()
                    idx += 3
            else:
                idx += 1

        row = dbRow(self._block, row_name, site, Point(orig_x, orig_y), orient, direction, site_count, spacing)
        self._block.addRow(row)

    def _parse_tracks(self, reader: TokenReader) -> None:
        axis = reader.next().upper()  # X or Y
        start = int(reader.next())
        reader.expect("DO")
        count = int(reader.next())
        reader.expect("STEP")
        step = int(reader.next())

        tokens = reader.read_until_semicolon()
        idx = 0
        layers = []
        while idx < len(tokens):
            t = tokens[idx].upper()
            if t == "MASK":
                idx += 2  # skip 'MASK' and mask number
            elif t == "SAMEMASK":
                idx += 1  # skip 'SAMEMASK'
            elif t == "LAYER":
                idx += 1
                while idx < len(tokens) and tokens[idx].upper() not in ("MASK", "SAMEMASK", ";"):
                    layers.append(tokens[idx])
                    idx += 1
            else:
                idx += 1

        for layer_name in layers:
            layer = self._tech.findLayer(layer_name)
            if layer is None:
                layer = dbTechLayer(layer_name)
                self._tech.addLayer(layer)

            grid = self._block.findTrackGrid(layer)
            if grid is None:
                grid = dbTrackGrid(layer)
                self._block.setTrackGrid(layer, grid)

            if axis == "X":
                grid.addGridPatternX(start, count, step)
            else:
                grid.addGridPatternY(start, count, step)

    def _parse_vias(self, reader: TokenReader) -> None:
        reader.next()  # num vias
        if reader.peek() == ";":
            reader.next()

        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.peek().upper() == "VIAS":
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            if tok == "-":
                via_name = reader.next()
                via = dbTechVia(via_name)
                curr_layer = None
                tokens = reader.read_until_semicolon()
                idx = 0
                while idx < len(tokens):
                    t = tokens[idx].upper()
                    if t == "+":
                        idx += 1
                        continue
                    if t == "LAYER":
                        layer_name = tokens[idx + 1]
                        curr_layer = self._tech.findLayer(layer_name)
                        idx += 2
                    elif t == "RECT":
                        if curr_layer is not None and idx + 8 < len(tokens):
                            # RECT ( x1 y1 ) ( x2 y2 )
                            x1 = int(tokens[idx + 2])
                            y1 = int(tokens[idx + 3])
                            x2 = int(tokens[idx + 6])
                            y2 = int(tokens[idx + 7])
                            via.addBox(curr_layer, Rect(x1, y1, x2, y2))
                            idx += 9
                        else:
                            idx += 1
                    else:
                        idx += 1
                self._block.addVia(via)

    def _find_master(self, name: str) -> dbMaster:
        for lib in self._db.getLibs():
            m = lib.findMaster(name)
            if m:
                return m
        # Create dummy master if not found
        dummy = dbMaster(name)
        dummy.setWidth(1000)
        dummy.setHeight(1000)
        return dummy

    def _parse_components(self, reader: TokenReader) -> None:
        count_tok = reader.next()  # count
        total_count = int(count_tok) if count_tok.isdigit() else 0
        if reader.peek() == ";":
            reader.next()

        if self._callback:
            self._callback("Components", 0, total_count)

        comp_idx = 0
        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.peek().upper() == "COMPONENTS":
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            if tok == "-":
                comp_idx += 1
                if self._callback and comp_idx % 2000 == 0:
                    self._callback("Components", comp_idx, total_count)
                inst_name = reader.next()
                master_name = reader.next()
                master = self._find_master(master_name)
                inst = dbInst(self._block, master, inst_name)

                tokens = reader.read_until_semicolon()
                idx = 0
                while idx < len(tokens):
                    t = tokens[idx].upper()
                    if t in ("+PLACED", "+FIXED", "+COVER", "+FIRM", "+UNPLACED", "PLACED", "FIXED", "COVER", "FIRM", "UNPLACED"):
                        status_str = t.lstrip("+")
                        if status_str == "PLACED":
                            inst.setPlacementStatus(dbPlacementStatus.PLACED)
                        elif status_str == "FIXED":
                            inst.setPlacementStatus(dbPlacementStatus.FIXED)
                        elif status_str == "COVER":
                            inst.setPlacementStatus(dbPlacementStatus.COVER)

                        # Check for ( x y ) orient
                        if idx + 4 < len(tokens) and tokens[idx + 1] == "(":
                            x = int(tokens[idx + 2])
                            y = int(tokens[idx + 3])
                            inst.setOrigin(x, y)
                            orient_str = tokens[idx + 5]
                            inst.setOrient(dbOrientType.from_str(orient_str))
                            idx += 6
                        else:
                            idx += 1
                    elif t == "+":
                        idx += 1
                    elif t == "HALO":
                        if idx + 4 < len(tokens):
                            l, b, r, top = [int(v) for v in tokens[idx + 1 : idx + 5]]
                            inst.setHalo(Rect(l, b, r, top))
                            idx += 5
                        else:
                            idx += 1
                    else:
                        idx += 1

                self._block.addInst(inst)

        if self._callback:
            self._callback("Components", comp_idx, total_count)

    def _parse_pins(self, reader: TokenReader) -> None:
        count_tok = reader.next()  # count
        total_count = int(count_tok) if count_tok.isdigit() else 0
        if reader.peek() == ";":
            reader.next()

        if self._callback:
            self._callback("Pins", 0, total_count)

        pin_idx = 0
        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.peek().upper() == "PINS":
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            if tok == "-":
                pin_idx += 1
                if self._callback and pin_idx % 200 == 0:
                    self._callback("Pins", pin_idx, total_count)
                pin_name = reader.next()
                bterm = dbBTerm(self._block, pin_name)
                bpin = dbBPin()
                bterm.addBPin(bpin)

                tokens = reader.read_until_semicolon()
                idx = 0
                curr_layer = None

                while idx < len(tokens):
                    t = tokens[idx].upper()
                    if t == "+":
                        idx += 1
                        continue
                    if t == "DIRECTION":
                        dir_str = tokens[idx + 1].upper()
                        idx += 2
                    elif t == "USE":
                        use_str = tokens[idx + 1].upper()
                        if use_str == "POWER":
                            bterm.setSigType(dbSigType.POWER)
                        elif use_str == "GROUND":
                            bterm.setSigType(dbSigType.GROUND)
                        elif use_str == "CLOCK":
                            bterm.setSigType(dbSigType.CLOCK)
                        idx += 2
                    elif t == "LAYER":
                        layer_name = tokens[idx + 1]
                        curr_layer = self._tech.findLayer(layer_name)
                        if curr_layer is None:
                            curr_layer = dbTechLayer(layer_name)
                            self._tech.addLayer(curr_layer)
                        idx += 2
                        if idx < len(tokens) and tokens[idx].upper() == "MASK":
                            idx += 2  # skip 'MASK' and mask number
                        # Check for ( x1 y1 ) ( x2 y2 )
                        if idx + 7 < len(tokens) and tokens[idx] == "(":
                            x1 = int(round(float(tokens[idx + 1])))
                            y1 = int(round(float(tokens[idx + 2])))
                            x2 = int(round(float(tokens[idx + 5])))
                            y2 = int(round(float(tokens[idx + 6])))
                            bpin.addBox(curr_layer, Rect(x1, y1, x2, y2))
                            idx += 8
                    elif t in ("PLACED", "FIXED", "COVER"):
                        # ( x y ) orient
                        if idx + 4 < len(tokens) and tokens[idx + 1] == "(":
                            x = int(round(float(tokens[idx + 2])))
                            y = int(round(float(tokens[idx + 3])))
                            orient_str = tokens[idx + 5]
                            # Update existing box with placement offset
                            if bpin.getBoxes():
                                new_boxes = []
                                for l, box in bpin.getBoxes():
                                    new_boxes.append((l, Rect(box.xMin() + x, box.yMin() + y, box.xMax() + x, box.yMax() + y)))
                                bpin._boxes = new_boxes
                            idx += 6
                        else:
                            idx += 1
                    else:
                        idx += 1

                self._block.addBTerm(bterm)

        if self._callback:
            self._callback("Pins", pin_idx, total_count)

    def _parse_nets(self, reader: TokenReader, is_special: bool = False) -> None:
        count_tok = reader.next()  # count
        total_count = int(count_tok) if count_tok.isdigit() else 0
        if reader.peek() == ";":
            reader.next()

        net_idx = 0
        stage_name = "Special Nets" if is_special else "Signal Nets"
        update_interval = 200 if is_special else 1000

        if self._callback:
            self._callback(stage_name, 0, total_count)

        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.peek().upper() in ("NETS", "SPECIALNETS"):
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            if tok == "-":
                net_idx += 1
                if self._callback and net_idx % update_interval == 0:
                    self._callback(stage_name, net_idx, total_count)
                net_name = reader.next()
                net = dbNet(self._block, net_name)
                if is_special:
                    net.setSigType(dbSigType.POWER if "VDD" in net_name.upper() else dbSigType.GROUND)

                tokens = reader.read_until_semicolon()
                self._parse_net_tokens(net, tokens, is_special)
                self._block.addNet(net)

        if self._callback:
            self._callback(stage_name, net_idx, total_count)

    def _parse_net_tokens(self, net: dbNet, tokens: List[str], is_special: bool) -> None:
        idx = 0
        n = len(tokens)

        # Parse connections: ( inst pin )
        while idx < n:
            t = tokens[idx]
            if t == "(":
                # Connection
                inst_name = tokens[idx + 1]
                pin_name = tokens[idx + 2]
                if inst_name.upper() == "PIN":
                    bterm = self._block.findBTerm(pin_name)
                    if bterm:
                        bterm.setNet(net)
                        net.addBTerm(bterm)
                else:
                    inst = self._block.findInst(inst_name)
                    if inst:
                        iterm = inst.getITerm(pin_name)
                        if iterm:
                            iterm.setNet(net)
                            net.addITerm(iterm)
                idx += 4
            elif t == "+":
                break
            else:
                idx += 1

        # Parse routing shapes
        curr_layer: Optional[dbTechLayer] = None
        curr_width: int = 0
        last_x: Optional[int] = None
        last_y: Optional[int] = None

        while idx < n:
            t = tokens[idx].upper()
            if t == "+":
                idx += 1
                continue

            if t in ("MASK", "SAMEMASK"):
                idx += 2 if t == "MASK" else 1
                continue

            if t in ("ROUTED", "FIXED", "COVER", "SHIELD", "NOSHIELD"):
                idx += 1
                if idx < n and tokens[idx] != "(":
                    layer_name = tokens[idx]
                    curr_layer = self._tech.findLayer(layer_name)
                    if curr_layer is None:
                        curr_layer = dbTechLayer(layer_name)
                        self._tech.addLayer(curr_layer)
                    curr_width = curr_layer.getWidth()
                    idx += 1
                    if idx < n and tokens[idx].upper() == "MASK":
                        idx += 2
                    # In SPECIALNETS, width is given right after layer
                    if is_special and idx < n and tokens[idx] not in ("(", "+"):
                        try:
                            curr_width = int(tokens[idx])
                            idx += 1
                        except ValueError:
                            pass
                last_x = None
                last_y = None
                continue

            # Layer switch inside path
            layer_candidate = self._tech.findLayer(tokens[idx])
            if layer_candidate is not None:
                curr_layer = layer_candidate
                curr_width = curr_layer.getWidth()
                idx += 1
                if is_special and idx < n and tokens[idx] not in ("(", "+"):
                    try:
                        curr_width = int(round(float(tokens[idx])))
                        idx += 1
                    except ValueError:
                        pass
                last_x = None
                last_y = None
                continue

            if t == "(":
                # Point: ( x y [ext] )
                p_tokens = []
                idx += 1
                while idx < n and tokens[idx] != ")":
                    p_tokens.append(tokens[idx])
                    idx += 1
                idx += 1  # consume ')'

                if len(p_tokens) >= 2:
                    px_str = p_tokens[0]
                    py_str = p_tokens[1]
                    px = last_x if px_str == "*" else int(round(float(px_str)))
                    py = last_y if py_str == "*" else int(round(float(py_str)))

                    if last_x is not None and last_y is not None and curr_layer is not None:
                        hw = max(curr_width // 2, 1)
                        if px == last_x:
                            # Vertical segment
                            box = Rect(px - hw, min(py, last_y) - hw, px + hw, max(py, last_y) + hw)
                        elif py == last_y:
                            # Horizontal segment
                            box = Rect(min(px, last_x) - hw, py - hw, max(px, last_x) + hw, py + hw)
                        else:
                            # Diagonal or degenerate
                            box = Rect(min(px, last_x) - hw, min(py, last_y) - hw, max(px, last_x) + hw, max(py, last_y) + hw)

                        shape = RouteShape(curr_layer, box, is_via=False)
                        if is_special:
                            net.addSpecialWireShape(shape)
                        else:
                            net.addWireShape(shape)

                    last_x = px
                    last_y = py

                # Check if followed by via
                if idx < n and tokens[idx] not in ("(", "+"):
                    via_candidate_name = tokens[idx]
                    via = self._block.findVia(via_candidate_name) or self._tech.findVia(via_candidate_name)
                    if via is not None and last_x is not None and last_y is not None:
                        idx += 1
                        for vb in via.getBoxes():
                            vbox = vb.getBox()
                            placed_rect = Rect(
                                vbox.xMin() + last_x,
                                vbox.yMin() + last_y,
                                vbox.xMax() + last_x,
                                vbox.yMax() + last_y,
                            )
                            v_shape = RouteShape(vb.getTechLayer(), placed_rect, is_via=True, tech_via=via)
                            if is_special:
                                net.addSpecialWireShape(v_shape)
                            else:
                                net.addWireShape(v_shape)
                continue

            if t == "RECT":
                # RECT x1 y1 x2 y2
                if idx + 4 < n and curr_layer is not None:
                    x1, y1, x2, y2 = [int(round(float(v))) for v in tokens[idx + 1 : idx + 5]]
                    shape = RouteShape(curr_layer, Rect(x1, y1, x2, y2), is_via=False)
                    if is_special:
                        net.addSpecialWireShape(shape)
                    else:
                        net.addWireShape(shape)
                    idx += 5
                else:
                    idx += 1
                continue

            if t == "POLYGON":
                # POLYGON ( x1 y1 ) ( x2 y2 ) ...
                idx += 1
                poly_pts = []
                while idx < n and tokens[idx] == "(":
                    px = int(round(float(tokens[idx + 1])))
                    py = int(round(float(tokens[idx + 2])))
                    poly_pts.append(Point(px, py))
                    idx += 4
                if poly_pts and curr_layer is not None:
                    poly = Polygon(poly_pts)
                    shape = RouteShape(curr_layer, poly.getEnclosingRect(), is_via=False, poly=poly)
                    if is_special:
                        net.addSpecialWireShape(shape)
                    else:
                        net.addWireShape(shape)
                continue

            idx += 1

    def _parse_blockages(self, reader: TokenReader) -> None:
        reader.next()  # count
        if reader.peek() == ";":
            reader.next()

        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.peek().upper() == "BLOCKAGES":
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            if tok == "-":
                tokens = reader.read_until_semicolon()
                idx = 0
                is_placement = False
                curr_layer = None
                while idx < len(tokens):
                    t = tokens[idx].upper()
                    if t == "PLACEMENT":
                        is_placement = True
                        idx += 1
                    elif t == "LAYER":
                        curr_layer = self._tech.findLayer(tokens[idx + 1])
                        idx += 2
                    elif t == "RECT":
                        if idx + 8 < len(tokens):
                            # RECT ( x1 y1 ) ( x2 y2 )
                            x1 = int(tokens[idx + 2])
                            y1 = int(tokens[idx + 3])
                            x2 = int(tokens[idx + 6])
                            y2 = int(tokens[idx + 7])
                            rect = Rect(x1, y1, x2, y2)
                            if is_placement:
                                self._block.addBlockage(dbBlockage(rect))
                            elif curr_layer is not None:
                                self._block.addObstruction(dbObstruction(curr_layer, rect))
                            idx += 9
                        else:
                            idx += 1
                    else:
                        idx += 1

    def _parse_fills(self, reader: TokenReader) -> None:
        reader.next()  # count
        if reader.peek() == ";":
            reader.next()

        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                if reader.peek().upper() == "FILLS":
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            if tok == "-":
                tokens = reader.read_until_semicolon()
                idx = 0
                curr_layer = None
                while idx < len(tokens):
                    t = tokens[idx].upper()
                    if t == "LAYER":
                        curr_layer = self._tech.findLayer(tokens[idx + 1])
                        idx += 2
                    elif t == "RECT":
                        if idx + 8 < len(tokens) and curr_layer is not None:
                            x1 = int(tokens[idx + 2])
                            y1 = int(tokens[idx + 3])
                            x2 = int(tokens[idx + 6])
                            y2 = int(tokens[idx + 7])
                            self._block.addFill(dbFill(curr_layer, Rect(x1, y1, x2, y2)))
                            idx += 9
                        else:
                            idx += 1
                    else:
                        idx += 1
