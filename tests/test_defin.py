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

