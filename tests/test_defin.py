import os
from openroad_py.odb.database import dbDatabase
from openroad_py.lefin import LefParser
from openroad_py.defin import DefParser


def test_parse_simple_def():
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\src\odb\test\data\design.def"
    assert os.path.exists(def_path)

    db = dbDatabase()
    parser = DefParser(db)
    block = parser.parse_file(def_path)

    assert block.getName() == "counter"
    # Components
    insts = block.getInsts()
    assert len(insts) == 12

    # Pins
    bterms = block.getBTerms()
    assert len(bterms) == 12

    # Nets
    nets = block.getNets()
    assert len(nets) == 24


def test_parse_routed_gcd_def():
    lef_path1 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\Nangate45\Nangate45_stdcell.lef"
    def_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\src\odb\test\data\gcd\gcd_nangate45_route.def"

    assert os.path.exists(lef_path1)
    assert os.path.exists(lef_path2)
    assert os.path.exists(def_path)

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    def_parser = DefParser(db)
    block = def_parser.parse_file(def_path)

    assert block.getName() == "gcd"
    die = block.getDieArea()
    assert die.dx() > 0 and die.dy() > 0

    insts = block.getInsts()
    assert len(insts) > 100

    nets = block.getNets()
    assert len(nets) > 100

    # Ensure routed wire shapes were parsed
    routed_wire_count = sum(len(net.getWireShapes()) for net in nets)
    assert routed_wire_count > 500

    # Rows
    rows = block.getRows()
    assert len(rows) > 10


def test_parse_complex_ibex_and_aes():
    lef_path1 = r"designs\Nangate45\Nangate45_tech.lef"
    lef_path2 = r"designs\Nangate45\Nangate45_stdcell.lef"
    ibex_def = r"designs\ibex\ibex_core.def"
    aes_def = r"designs\aes\aes_cipher_top.def"

    assert os.path.exists(ibex_def)
    assert os.path.exists(aes_def)

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(lef_path1)
    lef_parser.parse_file(lef_path2)

    # Test Ibex RISC-V core
    def_parser = DefParser(db)
    ibex_block = def_parser.parse_file(ibex_def)
    assert ibex_block.getName() == "ibex_core"
    assert len(ibex_block.getInsts()) > 5000  # Thousands of cell instances!
    assert len(ibex_block.getNets()) > 5000

    # Test AES cipher
    aes_block = def_parser.parse_file(aes_def)
    assert aes_block.getName() == "aes_cipher_top"
    assert len(aes_block.getInsts()) > 5000
    assert len(aes_block.getNets()) > 5000


def test_parse_swerv_and_blackparrot_macros():
    tech_lef = r"designs\Nangate45\Nangate45_tech.lef"
    cell_lef = r"designs\Nangate45\Nangate45_stdcell.lef"
    swerv_macro_lef = r"designs\swerv_wrapper\swerv_wrapper_macro.lef"
    swerv_def = r"designs\swerv_wrapper\swerv_wrapper.def"

    assert os.path.exists(swerv_def)
    assert os.path.exists(swerv_macro_lef)

    db = dbDatabase()
    lef_parser = LefParser(db)
    lef_parser.parse_file(tech_lef)
    lef_parser.parse_file(cell_lef)
    lef_parser.parse_file(swerv_macro_lef)

    def_parser = DefParser(db)
    swerv_block = def_parser.parse_file(swerv_def)
    assert swerv_block.getName() == "swerv_wrapper"
    assert len(swerv_block.getInsts()) == 131271
    assert len(swerv_block.getNets()) == 143973

    # Verify placed SRAM macros
    sram_macros = [
        inst for inst in swerv_block.getInsts()
        if "fakeram" in inst.getMaster().getName()
    ]
    assert len(sram_macros) == 28
    for m in sram_macros:
        assert m.getMaster().getWidth() >= 30000
        assert m.getMaster().getHeight() >= 80000


def test_parse_tracks_and_nets_with_mask(tmp_path):
    def_content = """VERSION 5.8 ;
DESIGN mask_test ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 50000 50000 ) ;
TRACKS X 100 DO 500 STEP 40 MASK 1 SAMEMASK LAYER metal1 metal2 ;
TRACKS Y 200 DO 400 STEP 50 MASK 2 LAYER metal2 ;
PINS 1 ;
- clk + NET clk + DIRECTION INPUT + USE CLOCK + LAYER metal1 MASK 1 ( 0 0 ) ( 100 100 ) + PLACED ( 1000 2000 ) N ;
END PINS
NETS 1 ;
- net1 ( PIN clk ) + ROUTED metal1 MASK 1 ( 1000 2000 ) ( 3000 2000 ) ;
END NETS
END DESIGN
"""
    test_def_file = tmp_path / "test_mask.def"
    test_def_file.write_text(def_content)

    db = dbDatabase()
    parser = DefParser(db)
    block = parser.parse_file(str(test_def_file))

    assert block.getName() == "mask_test"
    assert len(block.getBTerms()) == 1
    assert len(block.getNets()) == 1
    m1 = db.getTech().findLayer("metal1")
    assert m1 is not None
    grid = block.findTrackGrid(m1)
    assert grid is not None


def test_def_progress_callbacks(tmp_path):
    def_content = """VERSION 5.8 ;
DESIGN progress_test ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
COMPONENTS 2 ;
- c1 dummy_master + PLACED ( 100 100 ) N ;
- c2 dummy_master + PLACED ( 200 200 ) N ;
END COMPONENTS
PINS 2 ;
- in1 + NET n1 + DIRECTION INPUT + LAYER metal1 ( 0 0 ) ( 10 10 ) + FIXED ( 10 10 ) N ;
- out1 + NET n2 + DIRECTION OUTPUT + LAYER metal1 ( 0 0 ) ( 10 10 ) + FIXED ( 20 20 ) N ;
END PINS
SPECIALNETS 1 ;
- VDD ( PIN in1 ) ;
END SPECIALNETS
NETS 2 ;
- n1 ( PIN in1 ) ( c1 in ) ;
- n2 ( PIN out1 ) ( c2 out ) ;
END NETS
END DESIGN
"""
    test_def_file = tmp_path / "test_prog.def"
    test_def_file.write_text(def_content)

    stages_recorded = []

    def callback(stage, cur, total):
        stages_recorded.append((stage, cur, total))

    db = dbDatabase()
    parser = DefParser(db)
    block = parser.parse_file(str(test_def_file), callback=callback)

    assert block.getName() == "progress_test"
    stage_names = [s[0] for s in stages_recorded]
    assert "Components" in stage_names
    assert "Pins" in stage_names
    assert "Special Nets" in stage_names
    assert "Signal Nets" in stage_names


def test_bterm_special_classification_from_def_use(tmp_path):
    def_content = """VERSION 5.8 ;
DESIGN pin_types ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
PINS 4 ;
- signal + USE SIGNAL + PLACED ( 100 100 ) N ;
- vdd + USE POWER + PLACED ( 200 100 ) N ;
- vss + USE GROUND + PLACED ( 300 100 ) N ;
- clock + USE CLOCK + PLACED ( 400 100 ) N ;
END PINS
END DESIGN
"""
    def_file = tmp_path / "pin_types.def"
    def_file.write_text(def_content)

    block = DefParser(dbDatabase()).parse_file(str(def_file))
    terms = {bterm.getName(): bterm for bterm in block.getBTerms()}

    assert not terms["signal"].isSpecial()
    assert terms["vdd"].isSpecial()
    assert terms["vss"].isSpecial()
    assert not terms["clock"].isSpecial()
    assert terms["signal"].isIOPin()
    assert terms["clock"].isIOPin()
    assert not terms["vdd"].isIOPin()


def test_io_tcl_whitelists_design_pins_from_parent_directory(tmp_path):
    design_dir = tmp_path / "eth_design"
    design_dir.mkdir()
    def_file = design_dir / "Eth_def.def"
    def_file.write_text("""VERSION 5.8 ;
DESIGN Ethernet_SS ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
PINS 3 ;
- listed + USE SIGNAL + PLACED ( 100 100 ) N ;
- omitted + USE SIGNAL + PLACED ( 200 100 ) N ;
- vdd + USE POWER + PLACED ( 300 100 ) N ;
END PINS
END DESIGN
""")
    (tmp_path / "io.tcl").write_text("""# Design: Ethernet_SS
(iopin
    (pin name="listed" offset=1.0 layer=5 width=0.04 depth=0.22)
)
""")

    block = DefParser(dbDatabase()).parse_file(str(def_file))
    terms = {bterm.getName(): bterm for bterm in block.getBTerms()}

    assert terms["listed"].isIOPin()
    assert not terms["omitted"].isIOPin()
    assert not terms["vdd"].isIOPin()


def test_macro_orientations_bbox(tmp_path):
    """Verify that macros placed with N (R0), FN (MY), FS (MX), and S (R180) are positioned correctly

    such that their bounding boxes span [x, x + W] and [y, y + H], matching OpenROAD definComponent.cpp.
    """
    lef_content = """VERSION 5.8 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MACRO SRAM_2K
  CLASS BLOCK ;
  ORIGIN 0.0 0.0 ;
  SIZE 20.0 BY 30.0 ;
END SRAM_2K
END LIBRARY
"""
    def_content = """VERSION 5.8 ;
DESIGN orient_test ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
COMPONENTS 4 ;
- m_r0 SRAM_2K + PLACED ( 10000 10000 ) N ;
- m_my SRAM_2K + PLACED ( 40000 10000 ) FN ;
- m_mx SRAM_2K + PLACED ( 10000 50000 ) FS ;
- m_r180 SRAM_2K + PLACED ( 40000 50000 ) S ;
END COMPONENTS
END DESIGN
"""
    lef_file = tmp_path / "macro.lef"
    def_file = tmp_path / "test.def"
    lef_file.write_text(lef_content)
    def_file.write_text(def_content)

    db = dbDatabase()
    lp = LefParser(db)
    lp.parse_file(str(lef_file))
    dp = DefParser(db)
    block = dp.parse_file(str(def_file))

    # W = 20,000 DBU, H = 30,000 DBU
    # m_r0: [10000, 30000] x [10000, 40000]
    m_r0 = block.findInst("m_r0")
    b0 = m_r0.getBBox().getBox()
    assert b0.xMin() == 10000 and b0.xMax() == 30000
    assert b0.yMin() == 10000 and b0.yMax() == 40000
    assert m_r0.getLocation().x == 10000 and m_r0.getLocation().y == 10000

    # m_my (mirrored across Y): must still span [40000, 60000] x [10000, 40000], NOT jump outside to [20000, 40000]!
    m_my = block.findInst("m_my")
    b_my = m_my.getBBox().getBox()
    assert b_my.xMin() == 40000 and b_my.xMax() == 60000
    assert b_my.yMin() == 10000 and b_my.yMax() == 40000
    assert m_my.getLocation().x == 40000 and m_my.getLocation().y == 10000

    # m_mx (mirrored across X): must still span [10000, 30000] x [50000, 80000], NOT jump outside downwards to [20000, 50000]!
    m_mx = block.findInst("m_mx")
    b_mx = m_mx.getBBox().getBox()
    assert b_mx.xMin() == 10000 and b_mx.xMax() == 30000
    assert b_mx.yMin() == 50000 and b_mx.yMax() == 80000
    assert m_mx.getLocation().x == 10000 and m_mx.getLocation().y == 50000

    # m_r180: must still span [40000, 60000] x [50000, 80000]
    m_r180 = block.findInst("m_r180")
    b_r180 = m_r180.getBBox().getBox()
    assert b_r180.xMin() == 40000 and b_r180.xMax() == 60000
    assert b_r180.yMin() == 50000 and b_r180.yMax() == 80000
    assert m_r180.getLocation().x == 40000 and m_r180.getLocation().y == 50000


def test_io_pins_placement_and_bbox(tmp_path):
    """Verify that IO pins have non-zero coordinates matching DEF placement,

    and do not default to (0, 0) or produce gigantic bounding boxes.
    """
    def_content = """VERSION 5.8 ;
DESIGN pin_test ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
PINS 2 ;
- pin_placed_first + NET clk + DIRECTION INPUT + PLACED ( 25000 50000 ) N + LAYER metal3 ( -140 -140 ) ( 140 140 ) ;
- pin_layer_first + NET rst + DIRECTION INPUT + LAYER metal3 ( -100 -200 ) ( 100 200 ) + FIXED ( 75000 80000 ) N ;
END PINS
END DESIGN
"""
    def_file = tmp_path / "pin_test.def"
    def_file.write_text(def_content)

    db = dbDatabase()
    dp = DefParser(db)
    block = dp.parse_file(str(def_file))

    p1 = block.findBTerm("pin_placed_first")
    assert p1 is not None
    box1 = p1.getBBox()
    # Should be centered at 25000, 50000 with width 280, height 280
    assert box1.xMin() == 25000 - 140
    assert box1.xMax() == 25000 + 140
    assert box1.yMin() == 50000 - 140
    assert box1.yMax() == 50000 + 140
    assert box1.dx() == 280
    assert box1.dy() == 280

    p2 = block.findBTerm("pin_layer_first")
    assert p2 is not None
    box2 = p2.getBBox()
    # Should be centered at 75000, 80000 with width 200, height 400
    assert box2.xMin() == 75000 - 100
    assert box2.xMax() == 75000 + 100
    assert box2.yMin() == 80000 - 200
    assert box2.yMax() == 80000 + 200
    assert box2.dx() == 200
    assert box2.dy() == 400



