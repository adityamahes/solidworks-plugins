#!/usr/bin/env python3
"""Single-stage planetary gearbox designer + SolidWorks builder.

Ring fixed, sun = input, carrier = output:  ratio = 1 + Zr/Zs.

  python planetary.py --ratio 5 --module 1 --planets 3 --face 10 --out out/          # design + previews
  python planetary.py --zs 15 --zp 21 --module 1.5 --planets 3 --out out/ --solidworks --assembly

Outputs: report.md, design.json, <part>.dxf, preview.svg, and with --solidworks
the .SLDPRT parts (+ .SLDASM with --assembly, planets phased to mesh).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from swkit.gears import external_gear, internal_gear, min_teeth_no_undercut  # noqa: E402
from swkit.geometry import Profile, points_in_polygon, polar, write_dxf, write_json, write_svg  # noqa: E402


def candidates(target, n, zmin, zmax, m, max_od, wall):
    out = []
    for zs in range(zmin, zmax + 1):
        for zp in range(zmin, 2 * zmax + 1):
            zr = zs + 2 * zp
            if (zs + zr) % n:
                continue                                    # equal-spacing assembly condition
            if (zs + zp) * math.sin(math.pi / n) <= zp + 2 + 0.5:
                continue                                    # neighbouring planet tips must clear
            od = m * zr + 2.5 * m + 2 * wall
            if max_od and od > max_od:
                continue
            ratio = 1 + zr / zs
            out.append({"zs": zs, "zp": zp, "zr": zr, "ratio": ratio, "ring_od": od,
                        "err": abs(ratio - target) / target})
    out.sort(key=lambda c: (round(c["err"], 3), c["ring_od"]))
    return out


def interference(sun, planet, ring, a, n, zs, zp, zr, psi0, ring_phase):
    """Max penetration-ish check: count planet outline points inside the sun or
    outside the ring's inner boundary, for every planet in its assembled pose."""
    sun_poly = sun.loops(0.05)[0]
    ring_poly = ring.loops(0.05)[0]
    pl = np.array(planet.loops(0.05)[0])
    bad = 0
    for k in range(n):
        th = 2 * math.pi * k / n
        psi = psi0 + th * (1 + zs / zp)
        c, s = math.cos(psi), math.sin(psi)
        P = pl @ np.array([[c, s], [-s, c]]) + np.array(polar(a, th))
        bad += int(points_in_polygon(P[:, 0], P[:, 1], sun_poly).sum())
        bad += int((~points_in_polygon(P[:, 0], P[:, 1], ring_poly)).sum())
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ratio", type=float, help="target reduction (single stage ~3..10)")
    ap.add_argument("--zs", type=int, help="sun teeth (skip search)")
    ap.add_argument("--zp", type=int, help="planet teeth (skip search)")
    ap.add_argument("--module", type=float, default=1.0, help="gear module, mm")
    ap.add_argument("--pressure-angle", type=float, default=20.0)
    ap.add_argument("--planets", type=int, default=3)
    ap.add_argument("--face", type=float, default=10.0, help="face width, mm")
    ap.add_argument("--backlash", type=float, default=0.1, help="total backlash on pitch circle, mm")
    ap.add_argument("--max-od", type=float, help="max ring outer diameter, mm")
    ap.add_argument("--ring-wall", type=float, default=4.0, help="ring wall outside root circle, mm")
    ap.add_argument("--zmin", type=int, help="min teeth per gear (default: undercut limit, ~17 @20deg)")
    ap.add_argument("--sun-bore", type=float, default=5.0, help="sun bore dia, mm (motor shaft)")
    ap.add_argument("--planet-bore", type=float, help="planet bore dia, mm (bearing OD / pin)")
    ap.add_argument("--carrier-pin", type=float, help="carrier pin hole dia, mm")
    ap.add_argument("--carrier-thick", type=float, default=5.0)
    ap.add_argument("--output-bore", type=float, default=8.0, help="carrier centre bore, mm")
    ap.add_argument("--ring-holes", type=int, default=6, help="mounting holes in ring flange")
    ap.add_argument("--ring-hole-dia", type=float, default=3.4)
    ap.add_argument("--out", default="planetary_out")
    ap.add_argument("--solidworks", action="store_true")
    ap.add_argument("--assembly", action="store_true")
    a = ap.parse_args(argv)

    m, n = a.module, a.planets
    alpha = math.radians(a.pressure_angle)
    zmin = a.zmin or min_teeth_no_undercut(alpha)
    warn = []

    if a.zs and a.zp:
        zs, zp = a.zs, a.zp
        zr = zs + 2 * zp
        if (zs + zr) % n:
            sys.exit(f"(Zs+Zr)={zs + zr} is not divisible by {n} planets: they cannot be equally spaced")
        alts = []
    else:
        if not a.ratio:
            sys.exit("give --ratio or both --zs and --zp")
        if a.ratio > 12:
            warn.append(f"Ratio {a.ratio} is high for one stage; consider two stages of ~{math.sqrt(a.ratio):.2f}.")
        cands = candidates(a.ratio, n, zmin, 80, m, a.max_od, a.ring_wall)
        if not cands:
            sys.exit("No tooth combination satisfies the constraints; relax --max-od, --module or --planets")
        best = cands[0]
        zs, zp, zr = best["zs"], best["zp"], best["zr"]
        alts = cands[1:6]
    for nm, z in (("sun", zs), ("planet", zp)):
        if z < zmin:
            warn.append(f"{nm} has {z} teeth (< {zmin}): involute undercut; use profile shift or more teeth")
    if (zs + zp) * math.sin(math.pi / n) <= zp + 2:
        sys.exit("Planets collide with each other; use fewer planets or a bigger sun")

    a_c = m * (zs + zp) / 2                      # carrier radius (centre distance)
    ratio = 1 + zr / zs
    ring_od = m * zr + 2.5 * m + 2 * a.ring_wall
    planet_bore = a.planet_bore or round(max(3.0, 0.35 * m * zp), 1)
    carrier_pin = a.carrier_pin or planet_bore
    if planet_bore > m * (zp - 2.5) - 2:
        warn.append("planet bore leaves < 1 mm under the planet root")
    if a.sun_bore > m * (zs - 2.5) - 2:
        warn.append("sun bore leaves < 1 mm under the sun root")

    # --- profiles -----------------------------------------------------------
    psi0 = math.pi - math.pi / zp                # planet 0 presents a tooth space to sun tooth at 0 rad
    ring_phase = 0.0 if zp % 2 else math.pi / zr
    sun = external_gear(zs, m, alpha, a.backlash / 2, name="sun")
    planet = external_gear(zp, m, alpha, a.backlash / 2, name="planet")
    ring_in = internal_gear(zr, m, alpha, a.backlash / 2, phase=ring_phase, name="ring")

    bad = interference(sun, planet, ring_in, a_c, n, zs, zp, zr, psi0, ring_phase)
    if bad:
        warn.append(f"Interference check found {bad} overlapping outline samples; increase --backlash")

    sun_p = Profile("sun").extend(sun).circle((0, 0), a.sun_bore / 2)
    planet_p = Profile("planet").extend(planet).circle((0, 0), planet_bore / 2)
    ring_p = Profile("ring").extend(ring_in).circle((0, 0), ring_od / 2)
    hole_r = (ring_od / 2 + m * zr / 2 + 1.25 * m) / 2
    if a.ring_holes and ring_od / 2 - hole_r > a.ring_hole_dia / 2 + 0.8:
        for k in range(a.ring_holes):
            ring_p.circle(polar(hole_r, 2 * math.pi * k / a.ring_holes + math.pi / a.ring_holes), a.ring_hole_dia / 2)
    else:
        a.ring_holes = 0
    carrier_r = a_c + 0.6 * m * zp
    carrier_p = Profile("carrier").circle((0, 0), carrier_r).circle((0, 0), a.output_bore / 2)
    for k in range(n):
        carrier_p.circle(polar(a_c, 2 * math.pi * k / n), carrier_pin / 2)
    if carrier_r > m * zr / 2 - m - 0.5:
        warn.append("carrier plate is wider than the ring tip circle: mount it outside the ring (axially)")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    parts = {"sun": sun_p, "planet": planet_p, "ring": ring_p, "carrier": carrier_p}
    for name, p in parts.items():
        write_dxf(out / f"{name}.dxf", [p])
    layers = [(ring_p, (0, 0, 0), "#555"), (sun_p, (0, 0, 0), "#c0392b")]
    for k in range(n):
        th = 2 * math.pi * k / n
        x, y = polar(a_c, th)
        layers.append((planet_p, (x, y, psi0 + th * (1 + zs / zp)), "#2471a3"))
    write_svg(out / "preview.svg", layers)

    design = {
        "ratio": round(ratio, 4), "sun_teeth": zs, "planet_teeth": zp, "ring_teeth": zr, "planets": n,
        "module_mm": m, "pressure_angle_deg": a.pressure_angle, "face_width_mm": a.face,
        "centre_distance_mm": round(a_c, 4), "sun_pitch_dia": m * zs, "planet_pitch_dia": m * zp,
        "ring_pitch_dia": m * zr, "ring_od_mm": round(ring_od, 2), "planet_bore_mm": planet_bore,
        "carrier_radius_mm": round(carrier_r, 2), "backlash_mm": a.backlash,
        "planet_rotation_rad": [round(psi0 + 2 * math.pi * k / n * (1 + zs / zp), 6) for k in range(n)],
        "hardware": [
            {"item": "planet pin / dowel", "qty": n, "spec": f"{carrier_pin} mm dowel pin, >= {a.face + a.carrier_thick:.0f} mm long"},
            {"item": "planet bearing (optional)", "qty": n, "spec": f"bearing whose OD = planet bore ({planet_bore} mm; "
             "set --planet-bore to the chosen bearing OD and --carrier-pin to its ID)"},
            {"item": "ring mounting screw", "qty": a.ring_holes, "spec": f"socket head cap screw for {a.ring_hole_dia} mm clearance holes"},
            {"item": "sun set screw / shaft", "qty": 1, "spec": f"{a.sun_bore} mm motor shaft into the sun bore"},
        ],
        "ring_phase_rad": ring_phase, "interference_samples": bad, "warnings": warn,
        "alternatives": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items() if k != "err"}
                         for c in alts],
    }
    design["hardware"] = [h for h in design["hardware"] if h["qty"]]
    write_json(out / "design.json", design)
    (out / "report.md").write_text(report_md(design, a), encoding="utf-8")
    print(json.dumps(design, indent=2))

    if a.solidworks:
        from swkit import sw
        build = {"sun": [(sun_p, a.face, 0)], "planet": [(planet_p, a.face, 0)],
                 "ring": [(ring_p, a.face, 0)], "carrier": [(carrier_p, a.carrier_thick, 0)]}
        asm = None
        if a.assembly:
            asm = [("ring", 0, 0, 0, 0.0), ("sun", 0, 0, 0, 0.0)]
            for k in range(n):
                th = 2 * math.pi * k / n
                x, y = polar(a_c, th)
                asm.append(("planet", x, y, 0, psi0 + th * (1 + zs / zp)))
            asm.append(("carrier", 0, 0, a.face + 0.5, 0.0))
        sw.build(build, out, asm, "planetary_gearbox")


def report_md(d, a):
    lines = [
        "# Planetary gearbox", "",
        f"**Ratio {d['ratio']}:1** (ring fixed, sun in, carrier out), {d['planets']} planets, "
        f"module {d['module_mm']} mm, {d['pressure_angle_deg']} deg pressure angle", "",
        "| Gear | Teeth | Pitch dia (mm) |", "|---|---|---|",
        f"| Sun | {d['sun_teeth']} | {d['sun_pitch_dia']:.2f} |",
        f"| Planet | {d['planet_teeth']} | {d['planet_pitch_dia']:.2f} |",
        f"| Ring | {d['ring_teeth']} | {d['ring_pitch_dia']:.2f} |", "",
        f"- Centre distance (carrier radius) {d['centre_distance_mm']} mm",
        f"- Ring OD {d['ring_od_mm']} mm, face width {d['face_width_mm']} mm",
        f"- Planet bore {d['planet_bore_mm']} mm, backlash {d['backlash_mm']} mm",
        f"- Mesh interference samples: {d['interference_samples']} (0 = clean)", "",
    ]
    if d["warnings"]:
        lines += ["## Warnings", ""] + [f"- {w}" for w in d["warnings"]] + [""]
    if d["alternatives"]:
        lines += ["## Other tooth combinations", "", "| Zs | Zp | Zr | ratio | ring OD |", "|---|---|---|---|---|"]
        lines += [f"| {c['zs']} | {c['zp']} | {c['zr']} | {c['ratio']} | {c['ring_od']} |" for c in d["alternatives"]]
    lines += ["", "Notes: standard involute teeth (no profile shift, sharp root corners). Add root fillets and "
              "check with Tools > Evaluate > Interference Detection before manufacturing."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
