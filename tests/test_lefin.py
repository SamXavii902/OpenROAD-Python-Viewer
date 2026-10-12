import os
from openroad_py.odb.database import dbDatabase
from openroad_py.odb.types import dbTechLayerType
from openroad_py.lefin import LefParser


def test_parse_gscl45nm_lef():
    lef_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\src\odb\test\data\gscl45nm.lef"
    assert os.path.exists(lef_path)

    db = dbDatabase()
    parser = LefParser(db)
    parser.parse_file(lef_path)

    tech = db.getTech()
    assert tech is not None
    assert tech.getDbuPerMicron() == 2000

    layers = tech.getLayers()
    assert len(layers) > 10
    metal1 = tech.findLayer("metal1")
    assert metal1 is not None
    assert metal1.getType() == dbTechLayerType.ROUTING
    assert metal1.getWidth() == round(0.065 * 2000)

    # Check vias
    vias = tech.getVias()
    assert len(vias) > 0
    via1 = tech.findVia("M2_M1_via")
    assert via1 is not None
    assert len(via1.getBoxes()) == 3

    # Check sites
    core_site = tech.findSite("CoreSite")
    assert core_site is not None
    assert core_site.getWidth() == round(0.38 * 2000)
    assert core_site.getHeight() == round(2.47 * 2000)

    # Check macros in lib
    libs = db.getLibs()
    assert len(libs) == 1
    lib = libs[0]
    masters = lib.getMasters()
    assert len(masters) > 30

    and2 = lib.findMaster("AND2X1")
    assert and2 is not None
    assert and2.getWidth() == round(1.14 * 2000)
    assert and2.getHeight() == round(2.47 * 2000)
    mterms = and2.getMTerms()
    assert len(mterms) == 5  # A, B, Y, gnd, vdd
    obs = and2.getObstructions()
    assert len(obs) > 0


def test_parse_sky130_lefs():
    tlef_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\test\sky130hd\sky130hd.tlef"
    mlef_path = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD\src\odb\test\data\sky130hd\sky130_fd_sc_hd_merged.lef"
    assert os.path.exists(tlef_path)
    assert os.path.exists(mlef_path)

    db = dbDatabase()
    parser = LefParser(db)
    parser.parse_file(tlef_path)
    parser.parse_file(mlef_path)

    tech = db.getTech()
    assert tech is not None
    assert tech.getDbuPerMicron() == 1000

    met1 = tech.findLayer("met1")
    assert met1 is not None
    assert met1.getType() == dbTechLayerType.ROUTING

    # Check that standard cells from sky130 are present
    libs = db.getLibs()
    assert len(libs) == 2
    merged_lib = libs[1]
    masters = merged_lib.getMasters()
    assert len(masters) > 100
    inv = merged_lib.findMaster("sky130_fd_sc_hd__inv_1")
    assert inv is not None
    assert inv.getWidth() > 0
    assert inv.getHeight() > 0


def test_parse_lef_with_mask(tmp_path):
    lef_content = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;

UNITS
  DATABASE MICRONS 1000 ;
END UNITS

LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.2 ;
  WIDTH 0.1 ;
  SPACING 0.1 MASK 1 ;
END met1

LAYER cut1
  TYPE CUT ;
  WIDTH 0.1 ;
END cut1

VIA via1 DEFAULT
  LAYER met1 ;
    RECT MASK 1 -0.05 -0.05 0.05 0.05 ;
  LAYER cut1 ;
    RECT MASK 2 -0.03 -0.03 0.03 0.03 ;
END via1

MACRO test_macro
  CLASS CORE ;
  ORIGIN 0.0 0.0 ;
  SIZE 1.0 BY 2.0 ;
  PIN A
    DIRECTION INPUT ;
    PORT
      LAYER met1 ;
        RECT MASK 1 0.1 0.2 0.3 0.4 ;
        RECT MASK 2 ITERATE ( 0.5 0.6 ) ( 0.7 0.8 ) ;
        POLYGON MASK 1 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.2 ;
        VIA MASK 101 via1 0.5 0.5 ;
    END
  END A
  OBS
    LAYER met1 ;
      RECT MASK 3 0.0 0.0 1.0 1.0 ;
      POLYGON MASK 1 0.0 0.0 0.5 0.0 0.5 0.5 0.0 0.5 ;
  END
END test_macro

END LIBRARY
"""
    lef_file = tmp_path / "test_mask.lef"
    lef_file.write_text(lef_content, encoding="utf-8")

    db = dbDatabase()
    parser = LefParser(db)
    parser.parse_file(str(lef_file))

    tech = db.getTech()
    assert tech is not None
    assert tech.getDbuPerMicron() == 1000

    via1 = tech.findVia("via1")
    assert via1 is not None
    assert len(via1.getBoxes()) == 2
    b0 = via1.getBoxes()[0].getBox()
    assert b0.xMin() == -50 and b0.yMin() == -50 and b0.xMax() == 50 and b0.yMax() == 50

    libs = db.getLibs()
    assert len(libs) == 1
    macro = libs[0].findMaster("test_macro")
    assert macro is not None
    assert macro.getWidth() == 1000
    assert macro.getHeight() == 2000

    mterm = macro.findMTerm("A")
    assert mterm is not None
    mpins = mterm.getMPins()
    assert len(mpins) == 1
    geoms = mpins[0].getGeometry()
    # 2 rects + 2 via boxes = 4 boxes
    assert len(geoms) == 4
    polys = mpins[0].getPolygonGeometry()
    assert len(polys) == 1

    obs = macro.getObstructions()
    assert len(obs) == 1
    poly_obs = macro.getPolygonObstructions()
    assert len(poly_obs) == 1

