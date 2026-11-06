---
name: primitive-lattice
description: Generate Schwarz Primitive (P) TPMS lattices for SolidWorks. Fill a box, cylinder, sphere, any STL body, or the active SolidWorks part with a sheet or network Schwarz Primitive lattice at a target wall thickness or density, optionally graded and with a solid skin. Exports a watertight STL and imports it into SolidWorks. Use when the user asks for Schwarz P, primitive lattice, P surface, plumber's nightmare, open-channel lattice, easy-drain lattice, filter or scaffold lattice in SolidWorks.
---

# Schwarz Primitive (P) lattice for SolidWorks

The Schwarz Primitive is a triply periodic minimal surface (TPMS):

    cos x + cos y + cos z = 0

It looks like rounded 'plumbing joint' cavities on a cubic grid, with straight-through holes along X, Y and Z.

## When to choose it
- Large, straight, open channels: the easiest TPMS to clean, drain and inspect.
- Stiffer along the X/Y/Z axes than diagonally (anisotropic). Choose it when the loads line up with the grid.
- Good for flow-through parts, filters, scaffolds and visible decorative lattices.

Compared with other lattices: **gyroid** is the all-rounder with smooth twisting walls (`sw-gyroid-lattice`).
**Diamond** is the stiffest per weight. **Primitive** has the most open, easiest-to-drain channels. **I-WP**
is best for energy absorption. If the user hasn't picked one, say this in one line and confirm before building.

Script: `scripts/primitive.py` in this skill's base directory (`--help` for every option). It uses the shared
TPMS generator in `scripts/swkit/tpms.py`, the same mesher as the gyroid plugin, which was tested on
SolidWorks 2025 SP5. This lattice type itself has not been run in SolidWorks yet.

## Requirements
- Windows Python 3.10+ with `numpy` and `scipy`; `pywin32` for the SolidWorks steps.
- Find a working interpreter first: try `python`, `py -3`, then
  `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.13.exe`. If `python` errors with "No application is
  associated", it is the Store alias: use the full path.
- If a package is missing, tell the user the `python -m pip install ...` command; do not install without asking.

## Workflow
1. Pin down the domain: box, cylinder or sphere size, an STL path, or "the part open in SolidWorks".
   Then the cell size, and a wall thickness or target density. Defaults: 8 mm cell, 20% density, sheet style.
   Before anything touches SolidWorks, state the part, the settings and the style, and wait for the user's OK.
2. Dry run first (no `--solidworks`) and read the JSON report:
   - `non_manifold_edges` must be 0; `bodies` should be 1.
   - `sealed_voids` > 0 means a skin seals off the lattice's labyrinths. Powder or resin prints can't drain
     them: tell the user and suggest drain holes or `--shell 0`.
   - Also report `effective_density`, `mass_g`, `triangles` and any WARNING lines.
3. Rerun with `--solidworks`, or `--from-solidworks` to fill the active part.
4. Report the STL path, density, mass and triangle count.

## Options
- `--style sheet` (default): a thin double-sided wall. `--style network`: one solid phase,
  spheres joined by necks on a cubic grid. Use `--density` for network, since `--wall` is then an offset in mm.
- `--shell 1.2`: solid outer skin. Grading: `--density 0.15 --density-end 0.4 --grade-axis z`.
- Automatic: resolution rises so every sheet wall is at least 3 voxels, `--smooth 10` Taubin passes are applied,
  and pieces under 1% of the largest are dropped (`--keep-fragments` keeps them).

## SolidWorks import
- `--sw-body graphics` (default) imports large meshes in seconds. `--sw-body solid` gives a mesh-BREP solid,
  but it is slow: keep it under ~100k triangles (bigger `--cell`, thicker walls).
- The import type and mm units are set for this import only; the user's Tools > Options are restored.
- Thin walls force fine grids and big meshes. For printing, send the STL straight to the slicer.

## Example
```
python scripts/primitive.py --shape box --size 30 30 30 --cell 8 --density 0.25 --out out/primitive --solidworks
```
