"""Script to organize and copy sample open designs into the local designs/ folder."""

import os
import shutil

SCRATCH_DIR = r"C:\Users\vamsi\.gemini\antigravity\brain\dcc520b6-4651-46e9-95a7-6eb33931842d\scratch\RISHI"
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGNS_DIR = os.path.join(WORKSPACE_DIR, "designs")


def copy_samples():
    os.makedirs(DESIGNS_DIR, exist_ok=True)

    # 1. Nangate45 tech & cells
    nangate_dir = os.path.join(DESIGNS_DIR, "Nangate45")
    os.makedirs(nangate_dir, exist_ok=True)
    src_tech = os.path.join(SCRATCH_DIR, "test", "Nangate45", "Nangate45_tech.lef")
    src_std = os.path.join(SCRATCH_DIR, "test", "Nangate45", "Nangate45_stdcell.lef")
    if os.path.exists(src_tech):
        shutil.copy2(src_tech, nangate_dir)
    if os.path.exists(src_std):
        shutil.copy2(src_std, nangate_dir)

    # 2. GCD routed design
    gcd_dir = os.path.join(DESIGNS_DIR, "gcd")
    os.makedirs(gcd_dir, exist_ok=True)
    src_gcd = os.path.join(SCRATCH_DIR, "src", "odb", "test", "data", "gcd", "gcd_nangate45_route.def")
    if os.path.exists(src_gcd):
        shutil.copy2(src_gcd, gcd_dir)

    # 3. Sky130 HD
    sky130_dir = os.path.join(DESIGNS_DIR, "sky130hd")
    os.makedirs(sky130_dir, exist_ok=True)
    src_sky_tlef = os.path.join(SCRATCH_DIR, "test", "sky130hd", "sky130hd.tlef")
    src_sky_mlef = os.path.join(SCRATCH_DIR, "test", "sky130hd", "sky130_fd_sc_hd_merged.lef")
    if os.path.exists(src_sky_tlef):
        shutil.copy2(src_sky_tlef, sky130_dir)
    if os.path.exists(src_sky_mlef):
        shutil.copy2(src_sky_mlef, sky130_dir)

    # 4. Complex Designs: Ibex RISC-V core and AES cipher top
    ibex_dir = os.path.join(DESIGNS_DIR, "ibex")
    os.makedirs(ibex_dir, exist_ok=True)
    src_ibex = os.path.join(SCRATCH_DIR, "src", "gpl", "test", "design", "nangate45", "ibex_core", "ibex_core.def")
    if os.path.exists(src_ibex):
        shutil.copy2(src_ibex, ibex_dir)

    aes_dir = os.path.join(DESIGNS_DIR, "aes")
    os.makedirs(aes_dir, exist_ok=True)
    src_aes = os.path.join(SCRATCH_DIR, "src", "gpl", "test", "design", "nangate45", "aes_cipher_top", "aes_cipher_top.def")
    if os.path.exists(src_aes):
        shutil.copy2(src_aes, aes_dir)

    print(f"Sample designs copied to: {DESIGNS_DIR}")


if __name__ == "__main__":
    copy_samples()
