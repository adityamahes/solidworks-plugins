---
name: planetary-gearbox
description: Design and build a planetary (epicyclic) gearbox in SolidWorks — picks sun/planet/ring tooth counts for a target ratio under assembly, neighbour-clearance and undercut constraints, generates involute gear profiles, checks mesh interference, and builds sun, planet, ring and carrier parts plus a correctly phased assembly. Use when the user wants a planetary gearbox, epicyclic reducer, or planetary actuator in SolidWorks.
---

# Planetary gearbox for SolidWorks

Script: `scripts/planetary.py` in this skill's base directory (`--help` for all options).
Configuration: ring fixed, sun = input, carrier = output, ratio = 1 + Zr/Zs.

## Requirements
Windows Python with `numpy`; `pywin32` and SolidWorks for the build step. Find the interpreter as in
the gyroid-lattice skill (`python`, `py -3`, or the WindowsApps `python3.x.exe` full path).

## Intake (ask once, up front)
Collect these before running anything. Use the defaults shown when the user doesn't care.
1. **Gear ratio** (required).
2. **Requirements:** size envelope (max OD / length), input motor shaft diameter, output torque and
   speed if known, and how it will be made (FDM / resin / machined). Use these to pick the module and
   face width: bigger module and wider face for more torque. FDM needs module ≥ 1 for planetary and ≥ 0.5 for harmonic.
3. **McMaster-Carr hardware? (yes/no)** The gears and disks are always generated. If yes, after the build
   take the `hardware` list from `design.json` and use the **mcmaster-parts** skill to find each item
   (confirm part numbers with the user) and insert their CAD into the assembly.

## Workflow
1. Map the intake onto options: `--ratio`, `--module` (1 mm is a good printed default, 0.5–0.8 for small
   actuators), `--planets` (3), `--face`, `--sun-bore` (motor shaft), `--max-od`.
2. Dry run without `--solidworks`. Read `report.md`/stdout: chosen teeth, ratio, ring OD,
   `interference_samples` (must be 0) and warnings. Offer the listed alternatives if the ratio or size is off.
   Show `preview.svg` if the user wants a picture (planets are drawn in their meshed positions).
3. Build: rerun with `--solidworks --assembly`. Parts (`sun`, `planet`, `ring`, `carrier`) are saved
   as .SLDPRT in `--out`, and the assembly places each planet rotated so its teeth mesh with the sun and ring.
4. Suggest checking with Tools > Evaluate > Interference Detection and adding gear mates if they want motion.

## Design rules enforced
- Zr = Zs + 2·Zp; (Zs + Zr) divisible by the planet count (equal spacing);
  (Zs+Zp)·sin(π/n) > Zp + 2 (planet tips clear each other); teeth ≥ undercut limit (17 at 20°) unless the user forces it.
- Planet k at carrier angle θk is rotated ψk = π − π/Zp + θk(1 + Zs/Zp); the ring is offset by π/Zr when Zp is even.
- Ratios above ~10 get a two-stage suggestion (run the script once per stage).

## Limits
No tooth-strength calculation: size the module and face width from experience or a Lewis/AGMA check.
Standard full-depth involute, no profile shift, sharp root corners (add fillets for metal parts),
single stage. Units are mm.
