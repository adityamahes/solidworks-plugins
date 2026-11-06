---
name: cycloidal-drive
description: Design and build a cycloidal drive (cycloid reducer) in SolidWorks — computes the exact cycloidal disk profile for a ring-pin count, checks undercut/self-intersection and pin contact, sizes the eccentric bearing, output pins and holes, and builds two out-of-phase disks, pin housing, ring pins, output flange, eccentric shaft and an assembly. Use when the user wants a cycloidal drive, cycloid disk, cycloidal reducer, or a high-ratio compact robot actuator in SolidWorks.
---

# Cycloidal drive for SolidWorks

Script: `scripts/cycloidal.py` in this skill's base directory (`--help` for all options).
Configuration: housing + ring pins fixed, eccentric shaft = input, output flange = output.
Ratio = N − 1 for N ring pins (output turns the opposite way).

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
1. Ask for (or default): ratio (10–40 typical), pin-circle diameter (sets size), and optionally pin
   diameter, eccentricity, bearing, number of output pins. Defaults: pin ≈ half the pin pitch,
   e = 0.65·R/N (shortening coefficient K1 = eN/R = 0.65), largest listed bearing that fits.
2. Dry run without `--solidworks`; read the report. Check:
   - `pin_contact_gap_mm` min ≈ max ≈ clearance → all pins seated, no penetration.
   - No self-intersection exit (if it fails: smaller pins or eccentricity).
   - Output pin diameter, hole diameter (= pin + 2e + clearance) and the bearing.
3. Build with `--solidworks --assembly`. Parts: `disk1`, `disk2`, `housing`, `ring_pin`, `output_pin`,
   `output_flange`, `eccentric_shaft` (shaft with two cams 180° apart).

## Key facts
- Profile: ψ = atan2(sin((1−N)t), R/(eN) − cos((1−N)t)),
  x = R cos t − Rr cos(t+ψ) − e cos Nt,  y = −R sin t + Rr sin(t+ψ) + e sin Nt; needs e < R/N.
- Disk 2 sits on the −e cam and is pre-rotated −π/(N−1). With an even N (odd lobe count) it is the
  same shape as disk 1 turned 180°, so one part can be made twice.
- `--clearance` (default 0.05 mm) is an equidistant profile offset: raise it for FDM prints (0.1–0.2).
- Bearing table covers 6xx/67xx/68xx/69xx/60xx sizes; use the McMaster plugin to fetch bearing,
  dowel-pin and fastener CAD.

## Limits
Pins are separate dowels in half-pockets; no needle bushings or housing bearings are modelled. Units mm.
