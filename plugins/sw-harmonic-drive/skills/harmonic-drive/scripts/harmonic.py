#!/usr/bin/env python3
"""Harmonic (strain wave) drive designer + SolidWorks builder.

Circular spline (CS, internal teeth Zc) fixed, wave generator (WG) = input,
cup flexspline (FS, external teeth Zf = Zc - 2) = output:
    ratio = Zf / (Zc - Zf) = Zf / 2, output reverses.

  python harmonic.py --ratio 50 --pitch-dia 60 --out out/
  python harmonic.py --zf 100 --module 0.5 --wg rollers --wg-bearing 6800 --out out/ --solidworks --assembly

Teeth are short (stub) involutes at 30 deg pressure angle by default; the
script simulates the elliptically deformed flexspline inside the circular
spline and shortens the teeth until they stop colliding (disable: --no-auto-teeth).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from swkit.gears import external_gear, internal_gear  # noqa: E402
from swkit.geometry import Profile, points_in_polygon, polar, write_dxf, write_json, write_svg  # noqa: E402

BEARINGS = {"625": (5, 16, 5), "688": (8, 16, 5), "608": (8, 22, 7), "6700": (10, 15, 4), "6800": (10, 19, 5),
            "6801": (12, 21, 5), "6000": (10, 26, 8), "6802": (15, 24, 5), "6001": (12, 28, 8)}


def ellipse_perimeter(a, b):
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def perimeter_preserving_b(r0, a):
    lo, hi = r0 * 0.5, r0
    for _ in range(80):
        mid = (lo + hi) / 2
        if ellipse_perimeter(a, mid) > 2 * math.pi * r0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def deform(pts, w0, r_neutral):
    """Inextensible elliptical deformation of the FS (WG major axis on x)."""
    P = np.asarray(pts)
    rho = np.hypot(P[:, 0], P[:, 1])
    phi = np.arctan2(P[:, 1], P[:, 0])
    w = w0 * np.cos(2 * phi)
    v = -0.5 * w0 * np.sin(2 * phi)
    # tooth rotation with the rim normal: approximate by rigid offset along the radius
    phi2 = phi + v / r_neutral
    rho2 = rho + w
    return np.stack([rho2 * np.cos(phi2), rho2 * np.sin(phi2)], 1)


def mesh_check(fs_outline, cs_outline, w0, r_neutral):
    """Return (penetrating_fraction, max_penetration_mm) of the deformed FS into the CS."""
    fs = deform(fs_outline.loops(0.03)[0], w0, r_neutral)
    cs = np.asarray(cs_outline.loops(0.03)[0])
    outside = ~points_in_polygon(fs[:, 0], fs[:, 1], cs)
    if not outside.any():
        return 0.0, 0.0
    bad = fs[outside]
    depth = 0.0
    for chunk in np.array_split(bad, max(1, len(bad) // 500)):
        d = np.min(np.hypot(chunk[:, None, 0] - cs[None, :, 0], chunk[:, None, 1] - cs[None, :, 1]), axis=1)
        depth = max(depth, float(d.max()))
    return float(outside.mean()), depth


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ratio", type=int, help="reduction (Zf/2); Zf = 2*ratio")
    ap.add_argument("--zf", type=int, help="flexspline teeth (even); overrides --ratio")
    ap.add_argument("--module", type=float, help="module, mm")
    ap.add_argument("--pitch-dia", type=float, help="flexspline pitch diameter, mm (sets module)")
    ap.add_argument("--pressure-angle", type=float, default=30.0)
    ap.add_argument("--addendum", type=float, default=0.6, help="tooth addendum coefficient (x module)")
    ap.add_argument("--dedendum", type=float, default=0.75, help="tooth dedendum coefficient")
    ap.add_argument("--deflection-coef", type=float, default=1.0, help="radial deflection w0 = coef * m")
    ap.add_argument("--backlash", type=float, default=0.04, help="mm on pitch circle")
    ap.add_argument("--no-auto-teeth", action="store_true")
    ap.add_argument("--face", type=float, help="tooth face width, mm (default 0.2 d)")
    ap.add_argument("--rim", type=float, help="FS rim thickness under the teeth, mm (default 1.5%% d, >= 0.8)")
    ap.add_argument("--cup-length", type=float, help="FS cup length, mm (default 0.8 d; longer = lower stress)")
    ap.add_argument("--cup-bottom", type=float, default=3.0, help="FS diaphragm thickness, mm")
    ap.add_argument("--output-holes", type=int, default=6)
    ap.add_argument("--output-hole-dia", type=float, default=3.2)
    ap.add_argument("--cs-wall", type=float, default=6.0)
    ap.add_argument("--wg", default="ellipse", choices=["ellipse", "rollers"],
                    help="ellipse = cam for a flexible thin bearing (or direct sliding); rollers = 2 ball bearings")
    ap.add_argument("--wg-bearing-section", type=float, default=0.0,
                    help="ellipse WG: radial section of the flexible bearing, mm (0 = cam touches FS bore)")
    ap.add_argument("--wg-bearing", default="6800", help=f"rollers WG bearing: {', '.join(BEARINGS)}")
    ap.add_argument("--input-bore", type=float, default=5.0, help="WG motor shaft bore, mm")
    ap.add_argument("--wg-thick", type=float, help="WG thickness (default = face width)")
    ap.add_argument("--out", default="harmonic_out")
    ap.add_argument("--solidworks", action="store_true")
    ap.add_argument("--assembly", action="store_true")
    a = ap.parse_args(argv)

    zf = a.zf or (2 * a.ratio if a.ratio else 100)
    if zf % 2:
        sys.exit("Zf must be even (two-lobe wave generator)")
    zc = zf + 2
    if a.pitch_dia:
        m = a.pitch_dia / zf
    elif a.module:
        m = a.module
    else:
        m = 0.5
    alpha = math.radians(a.pressure_angle)
    d = m * zf
    r_f, r_c = d / 2, m * zc / 2
    w0 = a.deflection_coef * m
    warn = []
    if m < 0.3:
        warn.append(f"Module {m:.3f} mm is very fine; FDM printing needs >= ~0.5 mm, resin >= ~0.3 mm")

    # --- teeth: shorten until the deformed mesh is clean ----------------------
    ha, hf = a.addendum, a.dedendum
    tries = []
    while True:
        fs_teeth = external_gear(zf, m, alpha, a.backlash / 2, ha=ha, hf=hf, name="fs")
        cs_teeth = internal_gear(zc, m, alpha, a.backlash / 2, ha=ha, hf=hf, name="cs")
        frac, depth = mesh_check(fs_teeth, cs_teeth, w0, r_f)
        tries.append({"addendum": round(ha, 3), "penetration_mm": round(depth, 4), "fraction": round(frac, 4)})
        if depth <= 0.02 * m or a.no_auto_teeth or ha <= 0.3:
            break
        ha -= 0.05
        hf = max(hf - 0.05, ha + 0.15)
    if depth > 0.02 * m:
        warn.append(f"Deformed flexspline still penetrates the circular spline by {depth:.3f} mm; "
                    "raise --deflection-coef slightly or --backlash")

    face = a.face or round(0.2 * d, 1)
    rim = a.rim or round(max(0.8, 0.015 * d), 2)
    cup_len = a.cup_length or round(0.8 * d, 1)
    r_root_f = r_f - hf * m
    r_bore = r_root_f - rim
    strain = 1.5 * rim * w0 / r_f ** 2
    if strain > 0.02:
        warn.append(f"Rim bending strain {strain:.2%} is high even for nylon/TPU; increase diameter or thin the rim")

    # --- parts ---------------------------------------------------------------
    fs_band = Profile("flexspline").extend(fs_teeth).circle((0, 0), r_bore)
    fs_wall = Profile("fs_wall").circle((0, 0), r_bore + rim).circle((0, 0), r_bore)
    hub_r = max(a.input_bore, 0.15 * d) / 2
    fs_bottom = Profile("fs_bottom").circle((0, 0), r_bore + rim).circle((0, 0), hub_r)
    bolt_r = (hub_r + r_bore) / 2
    for k in range(a.output_holes):
        fs_bottom.circle(polar(bolt_r, 2 * math.pi * k / a.output_holes), a.output_hole_dia / 2)

    cs_od = 2 * (r_c + hf * m + a.cs_wall)
    cs = Profile("circular_spline").extend(cs_teeth).circle((0, 0), cs_od / 2)
    cs_bolt_r = (r_c + hf * m + cs_od / 2) / 2
    for k in range(6):
        cs.circle(polar(cs_bolt_r, 2 * math.pi * k / 6 + math.pi / 6), a.output_hole_dia / 2)

    wg_t = a.wg_thick or face
    wg_info = {"style": a.wg}
    if a.wg == "ellipse":
        r0 = r_bore - a.wg_bearing_section
        A = r0 + w0
        B = perimeter_preserving_b(r0, A)
        wg = Profile("wave_generator").ellipse((0, 0), A, B).circle((0, 0), a.input_bore / 2)
        wg_parts = {"wave_generator": [(wg, wg_t, 0)]}
        wg_info.update(cam_major_dia=round(2 * A, 4), cam_minor_dia=round(2 * B, 4),
                       bearing_section=a.wg_bearing_section)
        if a.wg_bearing_section == 0:
            wg_info["note"] = "Cam slides directly in the FS bore: lubricate, or use a flexible thin-section bearing"
    else:
        b_id, b_od, b_w = BEARINGS[a.wg_bearing]
        c = r_bore + w0 - b_od / 2
        if c - b_od / 2 < a.input_bore / 2 + 1:
            sys.exit("Roller bearings are too big for this flexspline; choose a smaller --wg-bearing")
        arm_w = b_id + 4
        wg = Profile("wave_generator")
        wg.circle((0, 0), a.input_bore / 2)
        hw, L = arm_w / 2, c + b_id / 2 + 1
        # stadium-shaped arm spanning both bearing posts
        wg.line((-c, -hw), (c, -hw)).arc((c, 0), (c, -hw), (c, hw), True)
        wg.line((c, hw), (-c, hw)).arc((-c, 0), (-c, hw), (-c, -hw), True)
        posts = Profile("wg_posts").circle((c, 0), b_id / 2).circle((-c, 0), b_id / 2)
        wg_parts = {"wave_generator": [(wg, 4, 0), (posts, b_w + 0.5, 4)]}
        wg_info.update(bearing=a.wg_bearing, bearing_size=[b_id, b_od, b_w], post_centre_mm=round(c, 3))
        warn.append("Roller WG only pushes at the major axis; the minor axis is unsupported (fine for prototypes)")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in (fs_band, cs, wg):
        write_dxf(out / f"{p.name}.dxf", [p])
    # preview: deformed flexspline teeth inside the circular spline
    fs_def = Profile("fs_deformed")
    fs_def.spline([tuple(p) for p in deform(fs_teeth.loops(0.05)[0], w0, r_f)])
    write_svg(out / "preview.svg", [(cs, (0, 0, 0), "#555"), (fs_def, (0, 0, 0), "#c0392b"),
                                    (wg, (0, 0, 0), "#2471a3")])

    design = {
        "ratio": zf // 2, "output_direction": "reversed (CS fixed, WG in, FS out)",
        "flexspline_teeth": zf, "circular_spline_teeth": zc, "module_mm": round(m, 4),
        "pressure_angle_deg": a.pressure_angle, "addendum_coef": round(ha, 3), "dedendum_coef": round(hf, 3),
        "fs_pitch_dia_mm": round(d, 3), "cs_pitch_dia_mm": round(2 * r_c, 3), "radial_deflection_w0_mm": round(w0, 4),
        "fs_bore_dia_mm": round(2 * r_bore, 3), "fs_rim_mm": rim, "fs_cup_length_mm": cup_len, "face_width_mm": face,
        "rim_bending_strain": round(strain, 5), "cs_od_mm": round(cs_od, 2), "wave_generator": wg_info,
        "hardware": ([{"item": "wave generator roller bearing", "qty": 2,
                        "spec": "{} ball bearing {} mm ID x {} mm OD x {} mm wide".format(a.wg_bearing, *BEARINGS[a.wg_bearing])}]
                     if a.wg == "rollers" else
                     [{"item": "flexible thin-section bearing (optional)", "qty": 1,
                       "spec": f"thin-section bearing ~{2 * r_bore:.0f} mm OD for the elliptical cam"}]) + [
            {"item": "output screw", "qty": a.output_holes, "spec": f"screw for {a.output_hole_dia} mm holes in the flexspline diaphragm"},
            {"item": "circular spline mounting screw", "qty": 6, "spec": f"screw for {a.output_hole_dia} mm holes"},
        ],
        "mesh_check": {"max_penetration_mm": round(depth, 4), "iterations": tries},
        "warnings": warn,
    }
    design["hardware"] = [h for h in design["hardware"] if h["qty"]]
    write_json(out / "design.json", design)
    (out / "report.md").write_text(report_md(design), encoding="utf-8")
    print(json.dumps(design, indent=2))

    if a.solidworks:
        from swkit import sw
        build = {
            "flexspline": [(fs_band, face, 0), (fs_wall, cup_len - face, face),
                           (fs_bottom, a.cup_bottom, cup_len)],
            "circular_spline": [(cs, face, 0)],
            **wg_parts,
        }
        asm = None
        if a.assembly:
            asm = [("circular_spline", 0, 0, 0, 0.0), ("flexspline", 0, 0, 0, 0.0),
                   ("wave_generator", 0, 0, 0, 0.0)]
        sw.build(build, out, asm, "harmonic_drive")


def report_md(d):
    wg = d["wave_generator"]
    lines = [
        "# Harmonic (strain wave) drive", "",
        f"**Ratio {d['ratio']}:1**, output reversed. FS {d['flexspline_teeth']} teeth / CS "
        f"{d['circular_spline_teeth']} teeth, module {d['module_mm']} mm, {d['pressure_angle_deg']} deg", "",
        f"- FS pitch dia {d['fs_pitch_dia_mm']} mm, bore {d['fs_bore_dia_mm']} mm, rim {d['fs_rim_mm']} mm, "
        f"cup length {d['fs_cup_length_mm']} mm, face {d['face_width_mm']} mm",
        f"- Radial deflection w0 = {d['radial_deflection_w0_mm']} mm; rim bending strain "
        f"{d['rim_bending_strain']:.3%} (steel fatigue ~0.2%, nylon/PETG ~1-2%)",
        f"- Teeth: addendum {d['addendum_coef']} m, dedendum {d['dedendum_coef']} m; deformed-mesh max "
        f"penetration {d['mesh_check']['max_penetration_mm']} mm",
        f"- Circular spline OD {d['cs_od_mm']} mm",
        f"- Wave generator: {json.dumps(wg)}", "",
    ]
    if d["warnings"]:
        lines += ["## Warnings", ""] + [f"- {w}" for w in d["warnings"]] + [""]
    lines += ["Notes: parts are modelled undeformed, so SolidWorks Interference Detection on the assembly WILL flag FS/CS tooth "
              "overlaps away from the major axis and WG/FS overlap at it. That is expected; the deformed-mesh check above is the "
              "real test. Involute stub teeth are a prototyping approximation of "
              "production S-tooth profiles. The FS must be a flexible material (steel, nylon, PETG/TPU for prints)."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
