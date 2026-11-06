---
name: gyroid-lattice
description: Generate gyroid (and diamond / Schwarz-P) TPMS lattices for SolidWorks — fill a box, cylinder, sphere, any STL body, or the active SolidWorks part with a sheet or network gyroid at a target wall thickness or density, optionally graded and with a solid skin, export a watertight STL and import it into SolidWorks. Use when the user wants a gyroid, TPMS, infill, lightweighting lattice, heat-exchanger core, or energy-absorbing lattice in SolidWorks.
---

# Gyroid lattice for SolidWorks

SolidWorks cannot model gyroids natively (equation-driven surfaces don't knit
into a lattice). This skill builds the lattice as an implicit field in Python,
meshes it watertight, and brings the mesh into SolidWorks.

Script: `scripts/gyroid.py` in this skill's base directory. Run with `--help` for every option.

## Requirements
- Windows Python 3.10+ with `numpy` and `scipy`; `pywin32` for the SolidWorks steps.
  `scikit-image` is optional (faster mesher with fewer triangles).
- Find a working interpreter first: try `python`, `py -3`, then
  `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.13.exe` (or python3.12 etc).
  If `python` errors with "No application is associated", it is the Store alias: use the full path.
- If a package is missing, tell the user the `python -m pip install ...` command; do not install without asking.

## Workflow
1. Pin down: domain (box/cylinder/sphere size, an STL path, or "the part open in SolidWorks"),
   cell size, and either wall thickness or target density. Defaults: 8 mm cell, 20% density, sheet style.
   Rules of thumb: wall ≥ 2 × nozzle width for FDM (≥0.8 mm), cell 4–10× wall, `--res` 12–20.
2. Do a dry run first (no `--solidworks`) and read the JSON report: `effective_density`, `mass_g`,
   `triangles`, `non_manifold_edges` (must be 0), and any WARNING lines.
3. Then rerun with `--solidworks` (or `--from-solidworks` to fill the active part, which exports it to STL,
   fixes SolidWorks' STL units/offset against the part bounding box, fills it, and imports the result).
4. Report the STL path, density, mass and triangle count to the user.

## Choosing options
- `--style sheet` (default): double-sided thin wall, the stiffest gyroid per weight, open for powder/resin drainage.
  `--style network`: one solid phase, a strut-like lattice; `--wall` is then an offset in mm (0 ≈ 50%).
- `--shell 1.2`: solid outer skin so the part looks and seals like the original body.
- Grading: `--density 0.15 --density-end 0.4 --grade-axis z` (or `--wall/--wall-end`).
- `--type diamond|primitive` for other TPMS lattices.

## SolidWorks import notes
- The body type follows Tools > Options > Import > STL/OBJ/OFF/PLY: **Graphics body** is fast and fine for
  visualisation, mass properties (use the JSON), and printing. **Solid body** gives a mesh BREP you can
  Boolean, but it gets slow beyond ~100k triangles: raise `--cell` or lower `--res` for that.
- For 3D printing, the STL can go straight to the slicer; SolidWorks is for fit checks and assemblies.
- Large grids are refused above 400³ voxels; split the part or coarsen.

## Example
```
python scripts/gyroid.py --shape cylinder --size 30 30 20 --cell 8 --density 0.2 --shell 1 --out out/gyroid
```
Measured: 245k triangles, 0 non-manifold edges, effective density 27% including the skin, about 11 s.
