import os
import shutil
import urllib.request

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGNS_DIR = os.path.join(WORKSPACE_DIR, "designs")
SCRATCH_OPENROAD = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\OpenROAD"

def setup_designs():
    os.makedirs(DESIGNS_DIR, exist_ok=True)
    nangate_dir = os.path.join(DESIGNS_DIR, "Nangate45")
    sky130_dir = os.path.join(DESIGNS_DIR, "sky130hd")
    os.makedirs(nangate_dir, exist_ok=True)
    os.makedirs(sky130_dir, exist_ok=True)

    # 1. Nangate45 LEF files
    src_tech = os.path.join(SCRATCH_OPENROAD, "test", "Nangate45", "Nangate45_tech.lef")
    src_std = os.path.join(SCRATCH_OPENROAD, "test", "Nangate45", "Nangate45_stdcell.lef")
    if os.path.exists(src_tech):
        shutil.copy2(src_tech, nangate_dir)
    if os.path.exists(src_std):
        shutil.copy2(src_std, nangate_dir)

    # 2. Sky130 LEF files
    src_sky_tlef = os.path.join(SCRATCH_OPENROAD, "test", "sky130hd", "sky130hd.tlef")
    src_sky_mlef = os.path.join(SCRATCH_OPENROAD, "test", "sky130hd", "sky130_fd_sc_hd_merged.lef")
    if os.path.exists(src_sky_tlef):
        shutil.copy2(src_sky_tlef, sky130_dir)
    if os.path.exists(src_sky_mlef):
        shutil.copy2(src_sky_mlef, sky130_dir)

    # 3. SweRV Placed Core (28 SRAM Macros, 131k Placed Standard Cells)
    swerv_dir = os.path.join(DESIGNS_DIR, "swerv_wrapper")
    os.makedirs(swerv_dir, exist_ok=True)
    src_swerv_macro_lef = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "swerv_wrapper_macro.lef")
    src_swerv_placed_def = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "macro03.defok")
    if os.path.exists(src_swerv_macro_lef):
        shutil.copy2(src_swerv_macro_lef, swerv_dir)
    if os.path.exists(src_swerv_placed_def):
        shutil.copy2(src_swerv_placed_def, os.path.join(swerv_dir, "swerv_wrapper.def"))

    # 4. BlackParrot Placed SoC (10 Cache Macros, 76k Placed Standard Cells)
    bp_dir = os.path.join(DESIGNS_DIR, "blackparrot")
    os.makedirs(bp_dir, exist_ok=True)
    src_bp_macro_lef = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "bp_be_top_macro.lef")
    src_bp_placed_def = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "macro01.defok")
    if os.path.exists(src_bp_macro_lef):
        shutil.copy2(src_bp_macro_lef, bp_dir)
    if os.path.exists(src_bp_placed_def):
        shutil.copy2(src_bp_placed_def, os.path.join(bp_dir, "bp_be_top.def"))

    # 5. Leon3 Large Benchmarks: large01 (220k cells) and large02 (312k cells)
    large_dir = os.path.join(DESIGNS_DIR, "large")
    os.makedirs(large_dir, exist_ok=True)
    src_large01 = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "large01.defok")
    src_large02 = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "large02.def")
    if os.path.exists(src_large01):
        shutil.copy2(src_large01, os.path.join(large_dir, "large01.def"))
    if os.path.exists(src_large02):
        shutil.copy2(src_large02, os.path.join(large_dir, "large02.def"))

    # 6. Medium Benchmark (80k cells, 100k nets)
    med_dir = os.path.join(DESIGNS_DIR, "medium")
    os.makedirs(med_dir, exist_ok=True)
    src_med04 = os.path.join(SCRATCH_OPENROAD, "src", "gpl", "test", "medium04.defok")
    if os.path.exists(src_med04):
        shutil.copy2(src_med04, os.path.join(med_dir, "medium04.def"))

    # 7. Sky130 Multi-Power-Domain AES Crypto Engine (UPF Voltage Domains)
    upf_dir = os.path.join(DESIGNS_DIR, "upf_aes")
    os.makedirs(upf_dir, exist_ok=True)
    src_upf = os.path.join(SCRATCH_OPENROAD, "test", "upf_aes.defok")
    if os.path.exists(src_upf):
        shutil.copy2(src_upf, os.path.join(upf_dir, "upf_aes.def"))

    # 8. Sky130 Cell On Block (Dense Macro with Standard Cell Channel Placement)
    cob_dir = os.path.join(DESIGNS_DIR, "cell_on_block")
    os.makedirs(cob_dir, exist_ok=True)
    src_cob_lef = os.path.join(SCRATCH_OPENROAD, "src", "dpl", "test", "cell_on_block2.lef")
    src_cob_def = os.path.join(SCRATCH_OPENROAD, "src", "dpl", "test", "cell_on_block2.defok")
    if os.path.exists(src_cob_lef):
        shutil.copy2(src_cob_lef, cob_dir)
    if os.path.exists(src_cob_def):
        shutil.copy2(src_cob_def, os.path.join(cob_dir, "cell_on_block2.def"))

    # 9. GCD Routed Core
    gcd_dir = os.path.join(DESIGNS_DIR, "gcd")
    os.makedirs(gcd_dir, exist_ok=True)
    src_gcd = os.path.join(SCRATCH_OPENROAD, "src", "odb", "test", "data", "gcd", "gcd_nangate45_route.def")
    if os.path.exists(src_gcd):
        shutil.copy2(src_gcd, gcd_dir)

    # 10. Download Caravel Sky130 SoC Harness (efabless/caravel)
    caravel_dir = os.path.join(DESIGNS_DIR, "caravel")
    os.makedirs(caravel_dir, exist_ok=True)
    caravel_base = "https://raw.githubusercontent.com/efabless/caravel/main"
    files_to_download = [
        ("def/caravel.def", os.path.join(caravel_dir, "caravel.def")),
        ("def/chip_io.def", os.path.join(caravel_dir, "chip_io.def")),
        ("lef/caravel.lef", os.path.join(caravel_dir, "caravel.lef")),
        ("lef/chip_io.lef", os.path.join(caravel_dir, "chip_io.lef")),
        ("lef/housekeeping.lef", os.path.join(caravel_dir, "housekeeping.lef")),
        ("lef/mgmt_protect.lef", os.path.join(caravel_dir, "mgmt_protect.lef")),
    ]
    for rel_url, local_path in files_to_download:
        if not os.path.exists(local_path):
            try:
                url = f"{caravel_base}/{rel_url}"
                print(f"Downloading {rel_url}...")
                urllib.request.urlretrieve(url, local_path)
            except Exception as e:
                print(f"Note: Could not download {rel_url}: {e}")

    print("All designs successfully setup in designs/ directory!")

if __name__ == "__main__":
    setup_designs()
