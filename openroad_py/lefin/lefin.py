"""LEF file parser ported from OpenROAD odb/src/lefin/lefin.cpp."""

import os
from typing import Optional, Union, List
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

    def parse_file(self, filepath: str) -> None:
        """Parses a LEF file from path."""
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

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = TokenReader(tokenize_stream(f))
            self._parse_top(reader)

    def _parse_top(self, reader: TokenReader) -> None:
        while reader.has_next():
            tok = reader.next()
            u = tok.upper()

            if u == "UNITS":
                self._parse_units(reader)
            elif u == "MANUFACTURINGGRID":
                grid_val = float(reader.next())
                if reader.peek() == ";":
                    reader.next()
                self._tech.setManufacturingGrid(round(grid_val * self._dbu))
            elif u == "LAYER":
                self._parse_layer(reader)
            elif u == "VIA":
                self._parse_via(reader)
            elif u == "SITE":
                self._parse_site(reader)
            elif u == "MACRO":
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
                if name.upper() == section_name.upper():
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
            elif u == "WIDTH":
                val = float(reader.next())
                layer.setWidth(self.dbu(val))
                reader.read_until_semicolon()
            elif u == "PITCH":
                tokens = reader.read_until_semicolon()
                if tokens:
                    px = float(tokens[0])
                    py = float(tokens[1]) if len(tokens) > 1 else px
                    layer.setPitchXY(self.dbu(px), self.dbu(py))
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
                if len(tokens) >= 4 and curr_layer is not None:
                    x1, y1, x2, y2 = [float(v) for v in tokens[:4]]
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
                w_val = float(reader.next())
                reader.expect("BY")
                h_val = float(reader.next())
                site.setWidth(self.dbu(w_val))
                site.setHeight(self.dbu(h_val))
                reader.read_until_semicolon()
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
                ox = float(reader.next())
                oy = float(reader.next())
                macro.setOrigin(Point(self.dbu(ox), self.dbu(oy)))
                reader.read_until_semicolon()
            elif u == "SIZE":
                w = float(reader.next())
                reader.expect("BY")
                h = float(reader.next())
                macro.setWidth(self.dbu(w))
                macro.setHeight(self.dbu(h))
                reader.read_until_semicolon()
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
                if len(tokens) >= 4 and curr_layer is not None:
                    x1, y1, x2, y2 = [float(v) for v in tokens[:4]]
                    rect = Rect(self.dbu(x1), self.dbu(y1), self.dbu(x2), self.dbu(y2))
                    mpin.addGeometry(dbBox(curr_layer, rect))
            elif u == "POLYGON":
                tokens = reader.read_until_semicolon()
                if len(tokens) >= 6 and curr_layer is not None:
                    pts = []
                    for i in range(0, len(tokens) - 1, 2):
                        pts.append(Point(self.dbu(float(tokens[i])), self.dbu(float(tokens[i + 1]))))
                    mpin.addPolygon(curr_layer, Polygon(pts))
            elif u == "VIA":
                via_name = reader.next()
                vx = float(reader.next())
                vy = float(reader.next())
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
                reader.read_until_semicolon()
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
                if len(tokens) >= 4 and curr_layer is not None:
                    x1, y1, x2, y2 = [float(v) for v in tokens[:4]]
                    rect = Rect(self.dbu(x1), self.dbu(y1), self.dbu(x2), self.dbu(y2))
                    macro.addObstruction(dbBox(curr_layer, rect))
            elif u == "POLYGON":
                tokens = reader.read_until_semicolon()
                if len(tokens) >= 6 and curr_layer is not None:
                    pts = []
                    for i in range(0, len(tokens) - 1, 2):
                        pts.append(Point(self.dbu(float(tokens[i])), self.dbu(float(tokens[i + 1]))))
                    macro.addPolyObstruction(curr_layer, Polygon(pts))
            else:
                reader.read_until_semicolon()
