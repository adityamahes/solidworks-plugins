---
name: gyroid-lattice
description: Generate gyroid (and diamond / Schwarz-P) TPMS lattices for SolidWorks — fill a box, cylinder, sphere, any STL body, or the active SolidWorks part with a sheet or network gyroid at a target wall thickness or density, optionally graded and with a solid skin, export a watertight STL and import it into SolidWorks. Use when the user wants a gyroid, TPMS, infill, lightweighting lattice, heat-exchanger core, or energy-absorbing lattice in SolidWorks.
---

# Gyroid lattice for SolidWorks

A gyroid has no exact CAD surface, so every gyroid tool works from its equation
`sin x cos y + sin y cos z + sin z cos x = 0`. This skill has two builders:

| Builder | Script | Result | Status |
|---|---|---|---|
| **Mesh** (default) | `scripts/gyroid.py` | watertight STL → imported into SolidWorks | tested on SW 2025 SP5 |
| **Native** | `scripts/gyroid_native.py` | real `.SLDPRT` of B-spline faces: surface unit cell → copies side by side → knit → cut the part's core | tested on SW 2025 SP5 |

Both scripts live in this skill's base directory. Run either with `--help` for every option.

## Requirements
- Windows Python 3.10+ with `numpy` and `scipy`; `pywin32` for the SolidWorks steps.
  `scikit-image` is optional (marching cubes: fewer triangles than the built-in mesher).
- Find a working interpreter first: try `python`, `py -3`, then
  `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.13.exe` (or python3.12 etc).
  If `python` errors with "No application is associated", it is the Store alias: use the full path.
- If a package is missing, tell the user the `python -m pip install ...` command; do not install without asking.

## Mesh workflow
1. Pin down: domain (box/cylinder/sphere size, an STL path, or "the part open in SolidWorks"),
   cell size, and either wall thickness or target density. Defaults: 8 mm cell, 20% density, sheet style.
   Rules of thumb: wall ≥ 2 × nozzle width for FDM (≥0.8 mm), cell 4–10× wall.
2. Dry run first (no `--solidworks`) and read the JSON report:
   - `non_manifold_edges` must be 0; `bodies` should be 1.
   - `sealed_voids` > 0 means the skin closes off the gyroid's labyrinths (a skinned sheet gyroid has 2).
     Powder or resin printing can't drain those: tell the user and suggest drain holes or `--shell 0`.
   - `effective_density`, `mass_g`, `triangles`, `voxels_per_cell`, `fragments_dropped`.
3. Then rerun with `--solidworks` (or `--from-solidworks` to fill the active part: it exports the part to STL,
   fixes SolidWorks' STL units/offset against the part bounding box, fills it and imports the result).
4. Report the STL path, density, mass and triangle count to the user.

What the mesh builder does automatically:
- **Resolution:** voxels per cell are raised so every sheet wall is ≥ `--min-wall-voxels` (3) thick.
  Thinner walls broke into separate pieces and came out jagged.
- **Smoothing:** `--smooth 10` Taubin passes remove voxel stair-steps without shrinking walls (`--smooth 0` = raw).
- **Fragments:** pieces under 1% of the largest are dropped. These are slivers where a wall grazes a corner
  or the shape's surface. `--keep-fragments` keeps them. Real sealed voids are never dropped.

## Choosing options
- `--style sheet` (default): double-sided thin wall, the stiffest gyroid per weight, open for drainage.
  `--style network`: one solid phase, a strut-like lattice; `--wall` is then an offset in mm (0 ≈ 50%).
- `--shell 1.2`: solid outer skin so the part looks and seals like the original body.
- Grading: `--density 0.15 --density-end 0.4 --grade-axis z` (or `--wall/--wall-end`).
- `--type diamond|primitive` for other TPMS lattices.

## SolidWorks import (tested on SW 2025 SP5)
- `--sw-body graphics` (default) imports in seconds even at 1M triangles (20 mm box, 1.09M tris: 6.5 s).
  Use it for looks, fit checks and assemblies; take mass from the JSON report.
- `--sw-body solid` gives a mesh-BREP solid you can Boolean, but it is slow: 78k triangles took 61 s.
  Keep solid imports under ~100k triangles (bigger `--cell`, thicker `--wall`).
- The script sets the import type and millimetre units for this import only, then restores the user's
  Tools > Options settings. It also switches the view to plain Shaded: "Shaded with Edges" draws every
  triangle edge and makes the lattice look black.
- Thin walls force fine grids and big meshes (a graded 0.15 → 0.40 density part reached 7.2M triangles). Fine
  for a slicer, heavy for SolidWorks. For printing, send the STL straight to the slicer.
- Grids above 400³ voxels are capped (a WARNING says how thick the walls end up in voxels).

## Native builder
`gyroid_native.py` builds the gyroid from SolidWorks surface features, so the result is an ordinary solid
you can fillet, cut, dimension and draw. Use it when the user wants an editable part. Use the mesh builder
for speed, printing, or very fine lattices.

1. A surface unit cell is made of fill surfaces bounded by exact gyroid curves, then cached in `--cache`
   (default `Documents\gyroid_cells`), so the same cell/wall is never rebuilt.
2. Copies go side by side half a cell beyond the part.
3. Each wall (`f = +c`, `f = -c`) knits into one continuous surface.
4. The part's core is cut by both surfaces. `--skin` keeps a solid shell.

Options: `--cell`, `--wall` (must be < cell/6), `--shape box|cylinder --size`, or `--target-part X.SLDPRT`
to fill your own part, plus `--skin`. Accuracy: `--subdiv 2` (default) and `--curve-points 17`.

Tested on SW 2025 SP5, 10 mm cell, 1 mm walls, each giving one solid body:

| Part | Volume | Exact | Time |
|---|---|---|---|
| 20 mm box | 2510 mm³ | 2463 mm³ (+1.9%) | 78 s |
| 20×20 mm cylinder | 1959 mm³ | 1935 mm³ (+1.3%) | 71 s |
| 20 mm box + 1.5 mm skin | 4620 mm³ | 4600 mm³ (+0.4%) | 88 s |

The first build of a new cell/wall adds ~75 s for the unit cell. The walls sit within ~23 µm (max 53 µm) of
the exact gyroid. A full `--skin` seals the gyroid's labyrinths inside, so powder or resin prints need drain holes.

SolidWorks API lessons behind it (SW 2025):
- Fill boundary = sketch selected with mark 257. Don't use `swOptimizeSurface`.
- Knit needs mark 1 and merges nothing if the selection splits into separate pieces.
- Sheet bounding boxes are loose.
- Surface-cut sides are chosen from the face normal (`ISurface.EvaluateAtPoint`, elements 0-2, flipped by
  `FaceInSurfaceSense`).

## Example
```
python scripts/gyroid.py --shape box --size 20 20 20 --cell 6 --wall 0.8 --out out/gyroid --solidworks
```
Measured on SW 2025: 23 voxels/cell (auto), 1.09M triangles, 1 body, 0 non-manifold edges, 35% effective
density, ~10 s to mesh and 6.5 s to import as a graphics body.
