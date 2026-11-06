# SolidWorks plugins for Claude Code

Five Claude Code plugins for parts that are hard to model by hand in SolidWorks. Each plugin pairs a
skill (how Claude should run the job) with a Python generator that does the math and checks the design,
then drives SolidWorks over COM to build real parts and assemblies.

| Plugin | What it builds | Checks it runs |
|---|---|---|
| `sw-gyroid-lattice` | Gyroid / diamond / Schwarz-P lattices in a box, cylinder, sphere, any STL, or the open SolidWorks part. Sheet or network style, graded walls, solid skin. | Watertight mesh (0 non-manifold edges), density solved to target, mass |
| `sw-planetary-gearbox` | Sun, planets, ring and carrier with involute teeth, plus an assembly with every planet phased to mesh | Tooth-count search (assembly, neighbour, undercut rules), 2D mesh interference |
| `sw-cycloidal-drive` | Two out-of-phase cycloid disks, pin housing, ring pins, output flange and pins, eccentric shaft, assembly | Profile self-intersection (undercut), every pin seated at the set clearance |
| `sw-harmonic-drive` | Cup flexspline, circular spline, elliptical or twin-roller wave generator, assembly | Simulated deformed-flexspline mesh with automatic tooth-height tuning, rim strain |
| `sw-mcmaster-parts` | McMaster-Carr hardware CAD (SLDPRT/STEP) found through the McMaster MCP, opened or inserted into your assembly | Accepts McMaster URLs only, caches by part number, writes a BOM |

The three gearbox plugins ask for the **gear ratio**, your **requirements** (envelope, motor shaft,
torque, how it will be made) and **whether you want McMaster-Carr hardware**. Each design writes a
`hardware` list (bearings, dowel pins, screws) that the McMaster plugin can source and drop into the assembly.

## Install

```bash
claude plugin marketplace add adityamahes/solidworks-plugins
claude plugin install sw-gyroid-lattice@solidworks-plugins
claude plugin install sw-planetary-gearbox@solidworks-plugins
claude plugin install sw-cycloidal-drive@solidworks-plugins
claude plugin install sw-harmonic-drive@solidworks-plugins
claude plugin install sw-mcmaster-parts@solidworks-plugins
```

Then ask in plain language, for example "make me a 15:1 cycloidal drive about 100 mm across for a
NEMA 17, printed, with McMaster bearings and pins", or call a skill directly, like `/sw-cycloidal-drive:cycloidal-drive`.

## Requirements

- Windows with SolidWorks (tested on SolidWorks 2025) and default part/assembly templates set
- Python 3.10+ with `numpy`, `scipy` and `pywin32` (`scikit-image` is optional and speeds up the gyroid mesher)
- `sw-mcmaster-parts` also needs the McMaster-Carr MCP server connected to Claude Code

```bash
python -m pip install numpy scipy pywin32
```

Every generator also runs **without SolidWorks**. Leave off `--solidworks` to get `report.md`,
`design.json`, DXF profiles and an SVG preview (or the STL for gyroids) for review or for other CAD tools.

## Run a generator directly

```bash
python plugins/sw-planetary-gearbox/skills/planetary-gearbox/scripts/planetary.py --ratio 5 --module 1 --out out/planetary --solidworks --assembly
python plugins/sw-cycloidal-drive/skills/cycloidal-drive/scripts/cycloidal.py --ratio 15 --pin-circle-dia 80 --out out/cycloidal --solidworks --assembly
python plugins/sw-harmonic-drive/skills/harmonic-drive/scripts/harmonic.py --ratio 30 --module 1 --wg rollers --out out/harmonic --solidworks --assembly
python plugins/sw-gyroid-lattice/skills/gyroid-lattice/scripts/gyroid.py --shape cylinder --size 30 30 20 --cell 8 --density 0.2 --shell 1 --out out/gyroid --solidworks
```

Every script supports `--help`.

## Repository layout

```
.claude-plugin/marketplace.json   marketplace listing all five plugins
plugins/<plugin>/.claude-plugin/plugin.json
plugins/<plugin>/skills/<skill>/SKILL.md        instructions Claude follows
plugins/<plugin>/skills/<skill>/scripts/        generator + bundled swkit copy
shared/swkit/                     source of truth: geometry, involute gears, SolidWorks COM driver
tools/sync_shared.py              copies shared/swkit into every plugin after you edit it
```

## Known limits

- Gears are standard involutes with sharp root corners and no profile shift, and there is no tooth-strength calculation. Size the module and face width yourself.
- Harmonic drive parts are modelled undeformed. SolidWorks interference detection on that assembly flags
  tooth overlaps by design; the script's deformed-mesh check is the real test.
- Assemblies place components by position only; add mates (gear, concentric) for motion studies.
- McMaster's CDN often refuses scripted downloads. The plugin then falls back to a browser download and files the result into your project.
- Large gyroid meshes (>~100k triangles) are slow as SolidWorks solid bodies; import them as graphics bodies or coarsen the mesh.

## License

MIT
