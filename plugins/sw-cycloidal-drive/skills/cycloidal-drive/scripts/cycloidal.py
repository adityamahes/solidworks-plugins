#!/usr/bin/env python3
"""Cycloidal drive designer + SolidWorks builder (two disks, 180 deg out of phase).

Housing with N ring pins is fixed, eccentric shaft = input, output flange
(pins through the disk holes) = output.  ratio = (N-1):1, output reverses.

  python cycloidal.py --ratio 15 --pin-circle-dia 80 --out out/
  python cycloidal.py --pins 16 --pin-circle-dia 60 --pin-dia 5 --ecc 1.2 --bearing 6805 --out out/ --solidworks --assembly

Profile (N = ring pins, R = pin circle radius, Rr = pin radius, e = eccentricity):
  psi = atan2(sin((1-N)t), R/(eN) - cos((1-N)t))
  x = R cos t - Rr cos(t+psi) - e cos(N t)
  y = -R sin t + Rr sin(t+psi) + e sin(N t)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from swkit.geometry import Profile, polar, rot, self_intersections, write_dxf, write_json, write_svg  # noqa: E402

# id, od, width (mm) - common deep-groove bearings for the eccentric cams
BEARINGS = {
    "625": (5, 16, 5), "696": (6, 15, 5), "688": (8, 16, 5), "6700": (10, 15, 4), "6701": (12, 18, 4),
    "6702": (15, 21, 4), "6703": (17, 23, 4), "6704": (20, 27, 4), "6900": (10, 22, 6), "6901": (12, 24, 6),
    "6800": (10, 19, 5), "6801": (12, 21, 5), "6802": (15, 24, 5), "6803": (17, 26, 5),
    "6804": (20, 32, 7), "6805": (25, 37, 7), "6806": (30, 42, 7), "6807": (35, 47, 7),
    "6808": (40, 52, 7), "6810": (50, 65, 7), "608": (8, 22, 7), "6000": (10, 26, 8),
    "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10), "6004": (20, 42, 12),
    "6005": (25, 47, 12), "6006": (30, 55, 13),
}


def lobe_points(N, R, Rr, e, t0, t1, n):
    t = np.linspace(t0, t1, n)
    psi = np.arctan2(np.sin((1 - N) * t), R / (e * N) - np.cos((1 - N) * t))
    x = R * np.cos(t) - Rr * np.cos(t + psi) - e * np.cos(N * t)
    y = -R * np.sin(t) + Rr * np.sin(t + psi) + e * np.sin(N * t)
    return np.stack([x, y], 1)


def disk_outline(N, R, Rr, e, phase=0.0, per_lobe=48, name="disk"):
    lobes = N - 1
    prof = Profile(name)
    first = None
    for k in range(lobes):
        pts = lobe_points(N, R, Rr, e, 2 * math.pi * k / lobes, 2 * math.pi * (k + 1) / lobes, per_lobe)
        pts = [rot(tuple(p), phase) for p in pts]
        if first is None:
            first = pts[0]
        if k == lobes - 1:
            pts[-1] = first                    # close exactly
        elif prof.items:
            pts[0] = prof.items[-1]["pts"][-1]  # share joints exactly
        prof.spline(pts)
    for k in range(1, len(prof.items)):
        prof.items[k]["pts"][0] = prof.items[k - 1]["pts"][-1]
    return prof


def pin_contact_error(N, R, Rr, e, disk_center, phase, pin_r=None, samples=4000):
    """Distance from each ring pin centre to the disk profile minus the pin radius.
    Profile generated with Rr (pin + clearance); measured against pin_r (real pin).
    Correct conjugate profile: every pin gap ~= clearance, none negative."""
    pin_r = Rr if pin_r is None else pin_r
    t = np.linspace(0, 2 * math.pi, samples, endpoint=False)
    psi = np.arctan2(np.sin((1 - N) * t), R / (e * N) - np.cos((1 - N) * t))
    x = R * np.cos(t) - Rr * np.cos(t + psi) - e * np.cos(N * t)
    y = -R * np.sin(t) + Rr * np.sin(t + psi) + e * np.sin(N * t)
    c, s = math.cos(phase), math.sin(phase)
    X, Y = x * c - y * s + disk_center[0], x * s + y * c + disk_center[1]
    errs = []
    for k in range(N):
        px, py = polar(R, 2 * math.pi * k / N)
        errs.append(float(np.min(np.hypot(X - px, Y - py)) - pin_r))
    return errs


def housing_inner(N, R, Rr, clearance):
    """Union of the pin-circle disk and N pin pockets (pins sit half-buried)."""
    rp = Rr + clearance
    d = 2 * math.asin(rp / (2 * R))           # angle from pin centre to pocket/circle intersection
    prof = Profile("housing")
    for k in range(N):
        th = 2 * math.pi * k / N
        pc = polar(R, th)
        a, b = polar(R, th - d), polar(R, th + d)
        prof.arc(pc, a, b, ccw=True)                    # pocket (outer half of pin)
        prof.arc((0, 0), b, polar(R, th + 2 * math.pi / N - d), ccw=True)
    return prof


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ratio", type=int, help="reduction ratio (= lobes = pins - 1)")
    ap.add_argument("--pins", type=int, help="ring pin count N (overrides --ratio)")
    ap.add_argument("--pin-circle-dia", type=float, default=80.0, help="ring pin circle diameter 2R, mm")
    ap.add_argument("--pin-dia", type=float, help="ring pin diameter, mm (default ~ half the pin pitch)")
    ap.add_argument("--ecc", type=float, help="eccentricity e, mm (default 0.65 R/N)")
    ap.add_argument("--clearance", type=float, default=0.05, help="radial profile clearance, mm")
    ap.add_argument("--disk-thick", type=float, default=6.0)
    ap.add_argument("--disk-gap", type=float, default=0.5, help="axial gap between disks")
    ap.add_argument("--bearing", help=f"eccentric bearing: {', '.join(BEARINGS)}  (default: largest that fits)")
    ap.add_argument("--out-pins", type=int, default=8, help="output pins / disk holes")
    ap.add_argument("--out-pin-dia", type=float, help="output pin diameter, mm")
    ap.add_argument("--housing-wall", type=float, default=6.0)
    ap.add_argument("--shaft-dia", type=float, help="input shaft dia (default bearing ID - 2e... see report)")
    ap.add_argument("--out", default="cycloidal_out")
    ap.add_argument("--solidworks", action="store_true")
    ap.add_argument("--assembly", action="store_true")
    a = ap.parse_args(argv)

    N = a.pins or ((a.ratio + 1) if a.ratio else 16)
    R = a.pin_circle_dia / 2
    Rr = a.pin_dia / 2 if a.pin_dia else round(0.5 * R * math.sin(math.pi / N), 2)
    e = a.ecc if a.ecc else round(0.65 * R / N, 2)
    warn = []
    if e * N >= R:
        sys.exit(f"Eccentricity too large: need e < R/N = {R / N:.3f} mm")
    if 2 * Rr >= 2 * R * math.sin(math.pi / N):
        sys.exit("Ring pins overlap: reduce --pin-dia or use fewer pins")
    if N % 2:
        warn.append("Odd pin count: disk 2 is a different part from disk 1 (even N makes them identical, rotated 180 deg)")

    Rc = Rr + a.clearance                       # clearance = equidistant modification
    disk1 = disk_outline(N, R, Rc, e, 0.0, name="disk1")
    phase2 = -math.pi / (N - 1)                 # disk 2 is half a crank turn later
    disk2 = disk_outline(N, R, Rc, e, phase2, name="disk2")

    hi = disk1.loops(0.05)[0]
    rr = np.hypot(*np.array(hi).T)
    r_min, r_max = float(rr.min()), float(rr.max())
    crossings = self_intersections(hi)
    if crossings:
        sys.exit(f"Disk profile self-intersects ({crossings} crossings): pin too big for this eccentricity. "
                 "Reduce --pin-dia or --ecc.")
    err1 = pin_contact_error(N, R, Rc, e, (e, 0), 0.0, Rr)
    err2 = pin_contact_error(N, R, Rc, e, (-e, 0), phase2, Rr)
    if min(err1 + err2) < -1e-3:
        warn.append(f"Pin penetration {min(err1 + err2):.4f} mm detected - check parameters")

    # --- bearing / centre bore ---------------------------------------------
    usable = r_min - 2 * e                    # keep room for output holes ring
    if a.bearing:
        b_id, b_od, b_w = BEARINGS[a.bearing]
        bname = a.bearing
    else:
        fits = [(v[1], k) for k, v in BEARINGS.items() if v[1] / 2 < 0.42 * r_min]
        if not fits:
            sys.exit("Disk is too small for any listed bearing; increase --pin-circle-dia")
        _, bname = max(fits)
        b_id, b_od, b_w = BEARINGS[bname]
    bore_r = b_od / 2
    # output holes between bore and profile valleys
    min_wall = max(1.5, 0.04 * r_min)
    ring_space = (r_min - min_wall) - (bore_r + min_wall)
    R_out = (r_min - min_wall + bore_r + min_wall) / 2
    hole_max = min(ring_space / 2, R_out * math.sin(math.pi / a.out_pins) - min_wall / 2) - a.clearance
    if a.out_pin_dia:
        pin_r = a.out_pin_dia / 2
        if pin_r + e > hole_max:
            sys.exit(f"Output pins too big: max {2 * (hole_max - e):.2f} mm for {a.out_pins} pins")
    else:
        pin_r = math.floor(2 * 0.85 * (hole_max - e) * 2) / 4   # round down to 0.25 mm dia steps
    if pin_r < 1.0:
        sys.exit("No room for output pins: use a smaller bearing (--bearing), fewer --out-pins or a larger disk")
    hole_r = pin_r + e + a.clearance

    def disk_part(outline, name):
        p = Profile(name).extend(outline).circle((0, 0), bore_r)
        for k in range(a.out_pins):
            p.circle(polar(R_out, 2 * math.pi * k / a.out_pins), hole_r)
        return p

    d1, d2 = disk_part(disk1, "disk1"), disk_part(disk2, "disk2")

    # --- housing, pins, output flange, eccentric shaft ----------------------
    h_od = 2 * (R + Rr + a.housing_wall)
    housing = Profile("housing").extend(housing_inner(N, R, Rr, 0.02)).circle((0, 0), h_od / 2)
    pin = Profile("ring_pin").circle((0, 0), Rr)
    flange = Profile("output_flange").circle((0, 0), R_out + hole_r + 3).circle((0, 0), b_id / 2)
    for k in range(a.out_pins):
        flange.circle(polar(R_out, 2 * math.pi * k / a.out_pins), pin_r)
    out_pin = Profile("output_pin").circle((0, 0), pin_r)
    # bearings slide over the shaft onto the offset cams, so shaft_r + e <= bearing ID / 2
    shaft_r = (a.shaft_dia / 2) if a.shaft_dia else math.floor((b_id / 2 - e - 0.25) * 4) / 4
    if shaft_r + e > b_id / 2:
        warn.append("Shaft + eccentricity exceed the bearing ID: the cam bearings cannot slide over the shaft")
    cam1 = Profile("cam1").circle((e, 0), b_id / 2)
    cam2 = Profile("cam2").circle((-e, 0), b_id / 2)
    shaft = Profile("shaft").circle((0, 0), shaft_r)

    t, gap = a.disk_thick, a.disk_gap
    stack = 2 * t + gap
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in (d1, d2, housing, flange):
        write_dxf(out / f"{p.name}.dxf", [p])
    write_svg(out / "preview.svg", [(housing, (0, 0, 0), "#555"), (d1, (e, 0, 0), "#c0392b"),
                                    (d2, (-e, 0, 0), "#2471a3")] +
              [(pin, (*polar(R, 2 * math.pi * k / N), 0), "#111") for k in range(N)])

    design = {
        "ratio": N - 1, "output_direction": "reversed", "ring_pins": N, "lobes": N - 1,
        "pin_circle_dia_mm": 2 * R, "pin_dia_mm": 2 * Rr, "eccentricity_mm": e,
        "shortening_coefficient_eN_over_R": round(e * N / R, 3),
        "profile_clearance_mm": a.clearance, "disk_r_min_mm": round(r_min, 3), "disk_r_max_mm": round(r_max, 3),
        "disk_thickness_mm": t, "bearing": {"model": bname, "id": b_id, "od": b_od, "width": b_w},
        "output_pins": a.out_pins, "output_pin_dia_mm": round(2 * pin_r, 3),
        "output_hole_dia_mm": round(2 * hole_r, 3), "output_pin_circle_dia_mm": round(2 * R_out, 3),
        "housing_od_mm": round(h_od, 2), "shaft_dia_mm": round(2 * shaft_r, 2),
        "disk2_phase_rad": round(phase2, 6),
        "hardware": [
            {"item": "eccentric cam bearing", "qty": 2, "spec": f"{bname} ball bearing {b_id} mm ID x {b_od} mm OD x {b_w} mm wide"},
            {"item": "ring pin", "qty": N, "spec": f"{2 * Rr:g} mm dowel pin, >= {stack + 1:.0f} mm long"},
            {"item": "output pin", "qty": a.out_pins, "spec": f"{2 * pin_r:g} mm dowel pin, >= {stack + 6:.0f} mm long"},
            {"item": "input shaft", "qty": 1, "spec": f"{2 * shaft_r:g} mm shaft (or the printed eccentric shaft)"},
        ],
        "pin_contact_gap_mm": {"min": round(min(err1 + err2), 4), "max": round(max(err1 + err2), 4)},
        "warnings": warn,
    }
    design["hardware"] = [h for h in design["hardware"] if h["qty"]]
    write_json(out / "design.json", design)
    (out / "report.md").write_text(report_md(design), encoding="utf-8")
    print(json.dumps(design, indent=2))

    if a.solidworks:
        from swkit import sw
        L = stack + 2
        build = {
            "disk1": [(d1, t, 0)], "disk2": [(d2, t, 0)],
            "housing": [(housing, stack + 1, 0)],
            "ring_pin": [(pin, stack + 1, 0)],
            "output_flange": [(flange, 5, 0)],
            "output_pin": [(out_pin, stack + 8, 0)],
            "eccentric_shaft": [(shaft, L + 15, -10), (cam1, t, 0.5), (cam2, t, 0.5 + t + gap)],
        }
        asm = None
        if a.assembly:
            asm = [("housing", 0, 0, -0.5, 0.0)]
            asm += [("ring_pin", *polar(R, 2 * math.pi * k / N), -0.5, 0.0) for k in range(N)]
            asm += [("disk1", e, 0, 0.0, 0.0), ("disk2", -e, 0, t + gap, 0.0),
                    ("eccentric_shaft", 0, 0, -0.5, 0.0), ("output_flange", 0, 0, stack + 1, 0.0)]
            asm += [("output_pin", *polar(R_out, 2 * math.pi * k / a.out_pins), -1, 0.0) for k in range(a.out_pins)]
        sw.build(build, out, asm, "cycloidal_drive")


def report_md(d):
    b = d["bearing"]
    lines = [
        "# Cycloidal drive", "",
        f"**Ratio {d['ratio']}:1**, output reversed. {d['ring_pins']} ring pins, {d['lobes']}-lobe disks x2", "",
        f"- Pin circle {d['pin_circle_dia_mm']} mm, pins {d['pin_dia_mm']} mm, eccentricity {d['eccentricity_mm']} mm "
        f"(K1 = eN/R = {d['shortening_coefficient_eN_over_R']}, 0.5-0.8 is typical)",
        f"- Disk radius {d['disk_r_min_mm']}..{d['disk_r_max_mm']} mm, thickness {d['disk_thickness_mm']} mm",
        f"- Eccentric bearing {b['model']} ({b['id']}x{b['od']}x{b['width']} mm) - disk bore = bearing OD",
        f"- {d['output_pins']} output pins {d['output_pin_dia_mm']} mm on {d['output_pin_circle_dia_mm']} mm circle, "
        f"disk holes {d['output_hole_dia_mm']} mm (= pin + 2e + clearance)",
        f"- Housing OD {d['housing_od_mm']} mm; input shaft {d['shaft_dia_mm']} mm",
        f"- Pin contact gap {d['pin_contact_gap_mm']['min']}..{d['pin_contact_gap_mm']['max']} mm "
        "(min ~ clearance means every pin is seated, none penetrate)", "",
    ]
    if d["warnings"]:
        lines += ["## Warnings", ""] + [f"- {w}" for w in d["warnings"]] + [""]
    lines += ["Notes: disk 2 sits on the opposite cam (-e) and is pre-rotated half a lobe; both disks turn at "
              "output speed. Pins are modelled as separate dowels in half-pockets."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
