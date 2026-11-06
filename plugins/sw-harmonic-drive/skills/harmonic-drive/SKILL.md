---
name: harmonic-drive
description: Design and build a harmonic (strain wave) drive in SolidWorks — cup flexspline with Zc−2 teeth, internal-tooth circular spline, and an elliptical-cam or twin-roller wave generator; simulates the deformed flexspline mesh and shortens the teeth until it is collision-free, estimates rim bending strain, and builds the parts and an assembly. Use when the user wants a harmonic drive, strain wave gear, flexspline, or zero-backlash high-ratio actuator in SolidWorks.
---

# Harmonic (strain wave) drive for SolidWorks

Script: `scripts/harmonic.py` in this skill's base directory (`--help` for all options).
Configuration: circular spline (CS) fixed, wave generator (WG) = input, flexspline (FS) = output.
Zf = Zc − 2, ratio = Zf/2 (output reversed).

## Requirements
Windows Python with `numpy`; `pywin32` and SolidWorks for the build. Find the interpreter as in the
gyroid-lattice skill.

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
1. Ask for (or default): ratio (30–160; even Zf = 2·ratio), FS pitch diameter or module, manufacturing
   method (FDM needs module ≥ ~0.5 mm, resin ≥ ~0.3, machined steel finer), and WG style:
   `ellipse` (cam for a thin flexible bearing, or a lubricated sliding cam) or `rollers`
   (two standard ball bearings on the major axis: the easiest printed build).
2. Dry run; read the report: `mesh_check.max_penetration_mm` (≈0), the tooth height chosen by the
   auto-tuner, `rim_bending_strain` (steel fatigue ≈0.2%, nylon/PETG ≈1–2%) and warnings.
   `preview.svg` shows the *deformed* flexspline inside the circular spline.
3. Build with `--solidworks --assembly`: `flexspline` (tooth band, thin cup wall, diaphragm with output
   bolt holes), `circular_spline` (with mounting holes) and `wave_generator`.

## Key facts
- Radial deflection w0 = coef × m (default 1.0·m). The FS deforms inextensibly:
  w = w0·cos2φ, v = −(w0/2)·sin2φ. The mesh check applies this to the FS outline and measures overlap with the CS.
- The elliptical cam keeps the bore perimeter (Ramanujan perimeter, solved for the minor axis), so the FS is bent, not stretched.
- Teeth are 30° stub involutes (addendum 0.6m, dedendum 0.75m by default), a prototyping
  approximation of commercial S-tooth profiles. The auto-tuner lowers the addendum in 0.05m steps if needed.
- Cup length defaults to 0.8·d: shorter cups raise the cone-angle stress at the tooth band.

## Limits
Parts are modelled undeformed, so SolidWorks Interference Detection on the assembly flags FS/CS tooth
overlaps (about 38 for a 30:1, m = 1 design) plus WG/FS at the major axis. Tell the user this is expected:
the flexspline only clears once the wave generator bends it, and `mesh_check` is the authoritative test. No flexible-bearing CAD (source one via the McMaster plugin or a bearing
vendor). Units mm.
