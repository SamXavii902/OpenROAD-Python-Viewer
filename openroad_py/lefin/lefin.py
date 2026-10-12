"""LEF file parser ported from OpenROAD odb/src/lefin/lefin.cpp."""

import os
from typing import Optional, Union, List, Tuple, Callable
from openroad_py.lefin.tokenizer import tokenize_stream, TokenReader
from openroad_py.odb.geom import Rect, Polygon, Point
from openroad_py.odb.types import (
    dbTechLayerType,
    dbTechLayerDir,
    dbMasterType,
    dbSigType,
)
from openroad_py.odb.tech import dbTech, dbTechLayer, dbTechVia, dbSite
from openroad_py.odb.lib import dbLib, dbMaster, dbMTerm, dbMPin, dbBox
from openroad_py.odb.database import dbDatabase


def _extract_rect_coords(tokens: List[str]) -> Optional[Tuple[float, float, float, float]]:
    """Extract (x1, y1, x2, y2) from RECT tokens, skipping MASK, ITERATE, parens, and extraneous keywords."""
    nums: List[float] = []
    i = 0
    n = len(tokens)
    while i < n and len(nums) < 4:
        tok = tokens[i]
        u = tok.upper()
        if u == "MASK":
            i += 2  # skip MASK and <mask_num>
            continue
        if u in ("SAMEMASK", "ITERATE", "(", ")"):
            i += 1
            continue
        try:
            val = float(tok)
            nums.append(val)
        except ValueError:
            pass
        i += 1
    if len(nums) >= 4:
        return nums[0], nums[1], nums[2], nums[3]
    return None


def _extract_polygon_points(tokens: List[str]) -> List[Tuple[float, float]]:
    """Extract [(x1, y1), ...] points from POLYGON tokens, skipping MASK, parens, etc."""
    nums: List[float] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        u = tok.upper()
        if u == "MASK":
            i += 2
            continue
        if u in ("SAMEMASK", "(", ")"):
            i += 1
            continue
        try:
            val = float(tok)
            nums.append(val)
        except ValueError:
            pass
        i += 1
    pts: List[Tuple[float, float]] = []
    for j in range(0, len(nums) - 1, 2):
        pts.append((nums[j], nums[j + 1]))
    return pts


def _extract_via_info(tokens: List[str]) -> Optional[Tuple[str, float, float]]:
    """Extract (via_name, x, y) from PORT VIA tokens: VIA [MASK <num>] <via_name> <x> <y> or VIA [MASK <num>] <x> <y> <via_name>."""
    filtered: List[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        u = tok.upper()
        if u == "MASK":
            i += 2
            continue
        if u in ("SAMEMASK", "ITERATE", "(", ")"):
            i += 1
            continue
        filtered.append(tok)
        i += 1

    via_name: Optional[str] = None
    coords: List[float] = []
    for item in filtered:
        try:
            val = float(item)
            coords.append(val)
        except ValueError:
            if via_name is None:
                via_name = item
    if via_name and len(coords) >= 2:
        return via_name, coords[0], coords[1]
    return None


class LefParser:
    """Parses standard LEF files into OpenDB data structures."""

    def __init__(self, db: dbDatabase):
        self._db: dbDatabase = db
        self._tech: Optional[dbTech] = db.getTech()
        if self._tech is None:
            self._tech = dbTech(dbu_per_micron=1000)
            db.setTech(self._tech)
        self._lib: Optional[dbLib] = None
        self._dbu: int = self._tech.getDbuPerMicron()

    def dbu(self, val: float) -> int:
        return round(float(val) * self._dbu)

    def parse_file(self, filepath: str, callback: Optional[Callable] = None) -> None:
        """Parses a LEF file from path with optional progress callback."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"LEF file not found: {filepath}")

        # Auto-resolve git symlinks on Windows
        if os.path.getsize(filepath) < 512:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
                if (first_line.startswith("../") or first_line.startswith("./")) and (
                    first_line.endswith(".lef") or first_line.endswith(".tlef")
                ):
                    resolved = os.path.normpath(os.path.join(os.path.dirname(filepath), first_line))
                    if os.path.exists(resolved):
                        filepath = resolved

        lib_name = os.path.splitext(os.path.basename(filepath))[0]
        self._lib = dbLib(lib_name)
        self._db.addLib(self._lib)
        self._callback = callback
        self._file_size = max(os.path.getsize(filepath), 1)
        pos_holder = [0]

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = TokenReader(tokenize_stream(f, pos_holder=pos_holder), pos_holder=pos_holder)
            self._parse_top(reader)

        self._notify_progress("LEF", self._file_size, self._file_size, f"Completed {lib_name}", sub_fraction=1.0)

    def _notify_progress(self, stage: str, cur: int, total: int, detail: str = "", sub_fraction: float = 0.0) -> None:
        if not self._callback:
            return
        try:
            self._callback(stage, cur, total, detail=detail, sub_fraction=sub_fraction)
        except TypeError:
            try:
                self._callback(stage, cur, total, detail)
            except TypeError:
                self._callback(stage, cur, total)

    def _parse_top(self, reader: TokenReader) -> None:
        last_token_notify = 0
        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            # Periodically notify progress so UI stays responsive on large LEFs
            if reader.token_count - last_token_notify >= 600:
                last_token_notify = reader.token_count
                cur_bytes = reader.get_bytes_read()
                frac = min(cur_bytes / self._file_size, 0.99)
                self._notify_progress("LEF", cur_bytes, self._file_size, f"{u}", sub_fraction=frac)

            if u == "UNITS":
                self._parse_units(reader)
            elif u == "MANUFACTURINGGRID":
                grid_val = float(reader.next())
                if reader.peek() == ";":
                    reader.next()
                self._tech.setManufacturingGrid(round(grid_val * self._dbu))
            elif u == "LAYER":
                cur_bytes = reader.get_bytes_read()
                frac = min(cur_bytes / self._file_size, 0.99)
                self._notify_progress("LEF", cur_bytes, self._file_size, f"Layer: {reader.peek()}", sub_fraction=frac)
                self._parse_layer(reader)
            elif u == "VIA":
                cur_bytes = reader.get_bytes_read()
                frac = min(cur_bytes / self._file_size, 0.99)
                self._notify_progress("LEF", cur_bytes, self._file_size, f"Via: {reader.peek()}", sub_fraction=frac)
                self._parse_via(reader)
            elif u == "SITE":
                self._parse_site(reader)
            elif u == "MACRO":
                cur_bytes = reader.get_bytes_read()
                frac = min(cur_bytes / self._file_size, 0.99)
                macro_peek = reader.peek()
                self._notify_progress("LEF", cur_bytes, self._file_size, f"Macro: {macro_peek}", sub_fraction=frac)
                self._parse_macro(reader)
            elif u == "PROPERTYDEFINITIONS":
                self._skip_section(reader, "PROPERTYDEFINITIONS")
            elif u == "VIARULE":
                rule_name = reader.next()
                self._skip_section(reader, rule_name)
            elif u == "NONDEFAULTRULE":
                rule_name = reader.next()
                self._skip_section(reader, rule_name)
            elif u == "SPACING":
                self._skip_section(reader, "SPACING")
            elif u in ("VERSION", "NAMESCASESENSITIVE", "BUSBITCHARS", "DIVIDERCHAR", "CLEARANCEMEASURE", "MAXVIASTACK"):
                reader.read_until_semicolon()
            elif u == "END":
                if reader.has_next():
                    reader.next()  # e.g. LIBRARY
                if reader.peek() == ";":
                    reader.next()
            else:
                pass

    def _skip_section(self, reader: TokenReader, section_name: str) -> None:
        while reader.has_next():
            tok = reader.next()
            if tok.upper() == "END":
                name = reader.peek()
                if name == ";" or name.upper() in (section_name.upper(), "VIARULE", "NONDEFAULTRULE", "PROPERTYDEFINITIONS"):
                    if name != ";":
                        reader.next()
                    if reader.peek() == ";":
                        reader.next()
                    break

    def _parse_units(self, reader: TokenReader) -> None:
        while reader.has_next():
            tok = reader.next()
            u = tok.upper()
            if u == "END":
                if reader.peek().upper() == "UNITS":
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "DATABASE":
                microns_tok = reader.next()  # MICRONS
                val_tok = reader.next()
                dbu_val = int(val_tok)
                self._dbu = dbu_val
                self._tech.setDbuPerMicron(dbu_val)
                if reader.peek() == ";":
                    reader.next()

    def _parse_layer(self, reader: TokenReader) -> None:
        layer_name = reader.next()
        layer = dbTechLayer(layer_name)
        routing_count = sum(1 for l in self._tech.getLayers() if l.getType() == dbTechLayerType.ROUTING)

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek().upper() == layer_name.upper():
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "TYPE":
                type_name = reader.next().upper()
                if type_name == "ROUTING":
                    layer.setType(dbTechLayerType.ROUTING)
                    layer.setRoutingLevel(routing_count + 1)
                elif type_name == "CUT":
                    layer.setType(dbTechLayerType.CUT)
                elif type_name == "MASTERSLICE":
                    layer.setType(dbTechLayerType.MASTERSLICE)
                elif type_name == "OVERLAP":
                    layer.setType(dbTechLayerType.OVERLAP)
                reader.read_until_semicolon()
            elif u == "DIRECTION":
                dir_name = reader.next().upper()
                if dir_name == "HORIZONTAL":
                    layer.setDirection(dbTechLayerDir.HORIZONTAL)
                elif dir_name == "VERTICAL":
                    layer.setDirection(dbTechLayerDir.VERTICAL)
                reader.read_until_semicolon()
            elif u == "SPACING":
                tokens = reader.read_until_semicolon()
                for t in tokens:
                    try:
                        val = float(t)
                        layer.setSpacing(self.dbu(val))
                        break
                    except ValueError:
                        continue
            elif u == "WIDTH":
                tokens = reader.read_until_semicolon()
                for t in tokens:
                    try:
                        val = float(t)
                        layer.setWidth(self.dbu(val))
                        break
                    except ValueError:
                        continue
            elif u == "PITCH":
                tokens = reader.read_until_semicolon()
                nums = []
                for t in tokens:
                    try:
                        nums.append(float(t))
                    except ValueError:
                        continue
                if len(nums) == 1:
                    layer.setPitch(self.dbu(nums[0]))
                elif len(nums) >= 2:
                    layer.setPitchXY(self.dbu(nums[0]), self.dbu(nums[1]))
            elif u == "PROPERTY":
                reader.read_until_semicolon()
            else:
                reader.read_until_semicolon()

        self._tech.addLayer(layer)

    def _parse_via(self, reader: TokenReader) -> None:
        via_name = reader.next()
        via = dbTechVia(via_name)
        curr_layer = None

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek().upper() == via_name.upper():
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "LAYER":
                layer_name = reader.next()
                curr_layer = self._tech.findLayer(layer_name)
                reader.read_until_semicolon()
            elif u == "RECT":
                tokens = reader.read_until_semicolon()
                if curr_layer is not None:
                    coords = _extract_rect_coords(tokens)
                    if coords is not None:
                        x1, y1, x2, y2 = coords
                        rect = Rect(self.dbu(x1), self.dbu(y1), self.dbu(x2), self.dbu(y2))
                        via.addBox(curr_layer, rect)
            elif u == "DEFAULT":
                pass
            else:
                reader.read_until_semicolon()

        self._tech.addVia(via)

    def _parse_site(self, reader: TokenReader) -> None:
        site_name = reader.next()
        site = dbSite(site_name)

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek().upper() == site_name.upper():
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "CLASS":
                cls_name = reader.next()
                site.setClass(cls_name)
                reader.read_until_semicolon()
            elif u == "SIZE":
                tokens = reader.read_until_semicolon()
                nums = []
                for t in tokens:
                    try:
                        nums.append(float(t))
                    except ValueError:
                        continue
                if len(nums) >= 2:
                    site.setWidth(self.dbu(nums[0]))
                    site.setHeight(self.dbu(nums[1]))
            else:
                reader.read_until_semicolon()

        self._tech.addSite(site)

    def _parse_macro(self, reader: TokenReader) -> None:
        macro_name = reader.next()
        macro = dbMaster(macro_name)

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek().upper() == macro_name.upper():
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "CLASS":
                cls_tok = reader.next().upper()
                if cls_tok.startswith("CORE"):
                    macro.setType(dbMasterType.CORE)
                elif cls_tok.startswith("BLOCK"):
                    macro.setType(dbMasterType.BLOCK)
                elif cls_tok.startswith("PAD"):
                    macro.setType(dbMasterType.PAD)
                reader.read_until_semicolon()
            elif u == "ORIGIN":
                tokens = reader.read_until_semicolon()
                nums = []
                for t in tokens:
                    try:
                        nums.append(float(t))
                    except ValueError:
                        continue
                if len(nums) >= 2:
                    macro.setOrigin(Point(self.dbu(nums[0]), self.dbu(nums[1])))
            elif u == "SIZE":
                tokens = reader.read_until_semicolon()
                nums = []
                for t in tokens:
                    try:
                        nums.append(float(t))
                    except ValueError:
                        continue
                if len(nums) >= 2:
                    macro.setWidth(self.dbu(nums[0]))
                    macro.setHeight(self.dbu(nums[1]))
            elif u == "PIN":
                self._parse_pin(reader, macro)
            elif u == "OBS":
                self._parse_obs(reader, macro)
            else:
                reader.read_until_semicolon()

        if self._lib is not None:
            self._lib.addMaster(macro)

    def _parse_pin(self, reader: TokenReader, macro: dbMaster) -> None:
        pin_name = reader.next()
        mterm = dbMTerm(pin_name)
        macro.addMTerm(mterm)

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek().upper() == pin_name.upper():
                    reader.next()
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "USE":
                use_tok = reader.next().upper()
                if use_tok == "POWER":
                    mterm.setSigType(dbSigType.POWER)
                elif use_tok == "GROUND":
                    mterm.setSigType(dbSigType.GROUND)
                elif use_tok == "CLOCK":
                    mterm.setSigType(dbSigType.CLOCK)
                reader.read_until_semicolon()
            elif u == "PORT":
                self._parse_port(reader, mterm)
            else:
                reader.read_until_semicolon()

    def _parse_port(self, reader: TokenReader, mterm: dbMTerm) -> None:
        mpin = dbMPin()
        mterm.addMPin(mpin)
        curr_layer = None

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "LAYER":
                layer_name = reader.next()
                curr_layer = self._tech.findLayer(layer_name)
                reader.read_until_semicolon()
            elif u == "RECT":
                tokens = reader.read_until_semicolon()
                if curr_layer is not None:
                    coords = _extract_rect_coords(tokens)
                    if coords is not None:
                        x1, y1, x2, y2 = coords
                        rect = Rect(self.dbu(x1), self.dbu(y1), self.dbu(x2), self.dbu(y2))
                        mpin.addGeometry(dbBox(curr_layer, rect))
            elif u == "POLYGON":
                tokens = reader.read_until_semicolon()
                if curr_layer is not None:
                    pts = _extract_polygon_points(tokens)
                    if len(pts) >= 3:
                        poly_pts = [Point(self.dbu(x), self.dbu(y)) for x, y in pts]
                        mpin.addPolygon(curr_layer, Polygon(poly_pts))
            elif u == "VIA":
                tokens = reader.read_until_semicolon()
                info = _extract_via_info(tokens)
                if info is not None:
                    via_name, vx, vy = info
                    tech_via = self._tech.findVia(via_name)
                    if tech_via is not None:
                        via_xy = Point(self.dbu(vx), self.dbu(vy))
                        for vb in tech_via.getBoxes():
                            vbox = vb.getBox()
                            rect = Rect(
                                vbox.xMin() + via_xy.x,
                                vbox.yMin() + via_xy.y,
                                vbox.xMax() + via_xy.x,
                                vbox.yMax() + via_xy.y,
                            )
                            mpin.addGeometry(dbBox(vb.getTechLayer(), rect, is_via=True, tech_via=tech_via, via_xy=via_xy))
            else:
                reader.read_until_semicolon()

    def _parse_obs(self, reader: TokenReader, macro: dbMaster) -> None:
        curr_layer = None

        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "END":
                if reader.peek() == ";":
                    reader.next()
                break
            elif u == "LAYER":
                layer_name = reader.next()
                curr_layer = self._tech.findLayer(layer_name)
                reader.read_until_semicolon()
            elif u == "RECT":
                tokens = reader.read_until_semicolon()
                if curr_layer is not None:
                    coords = _extract_rect_coords(tokens)
                    if coords is not None:
                        x1, y1, x2, y2 = coords
                        rect = Rect(self.dbu(x1), self.dbu(y1), self.dbu(x2), self.dbu(y2))
                        macro.addObstruction(dbBox(curr_layer, rect))
            elif u == "POLYGON":
                tokens = reader.read_until_semicolon()
                if curr_layer is not None:
                    pts = _extract_polygon_points(tokens)
                    if len(pts) >= 3:
                        poly_pts = [Point(self.dbu(x), self.dbu(y)) for x, y in pts]
                        macro.addPolyObstruction(curr_layer, Polygon(poly_pts))
            else:
                reader.read_until_semicolon()

