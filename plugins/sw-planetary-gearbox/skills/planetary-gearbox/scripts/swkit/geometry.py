"""2D sketch profiles and exporters (DXF R12, SVG, JSON).

All units are millimetres and radians. A Profile is an ordered list of
primitives that the SolidWorks builder turns into sketch entities, and that the
exporters turn into DXF/SVG so a design can be checked without SolidWorks.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

Point = tuple[float, float]


def polar(r: float, a: float) -> Point:
    return (r * math.cos(a), r * math.sin(a))


def rot(p: Point, a: float, c: Point = (0.0, 0.0)) -> Point:
    x, y = p[0] - c[0], p[1] - c[1]
    ca, sa = math.cos(a), math.sin(a)
    return (c[0] + x * ca - y * sa, c[1] + x * sa + y * ca)


class Profile:
    """Closed loops of sketch primitives. Every loop must be closed for extrusion."""

    def __init__(self, name: str = ""):
        self.name = name
        self.items: list[dict] = []

    # ---- primitives -----------------------------------------------------
    def line(self, p1: Point, p2: Point):
        self.items.append({"kind": "line", "p1": tuple(p1), "p2": tuple(p2)})
        return self

    def arc(self, c: Point, p1: Point, p2: Point, ccw: bool = True):
        self.items.append({"kind": "arc", "c": tuple(c), "p1": tuple(p1), "p2": tuple(p2), "ccw": ccw})
        return self

    def circle(self, c: Point, r: float):
        self.items.append({"kind": "circle", "c": tuple(c), "r": float(r)})
        return self

    def spline(self, pts):
        pts = [tuple(map(float, p)) for p in pts]
        if len(pts) < 2:
            raise ValueError("spline needs >= 2 points")
        self.items.append({"kind": "spline", "pts": pts})
        return self

    def ellipse(self, c: Point, a: float, b: float, angle: float = 0.0):
        self.items.append({"kind": "ellipse", "c": tuple(c), "a": float(a), "b": float(b), "angle": float(angle)})
        return self

    def extend(self, other: "Profile"):
        self.items.extend(other.items)
        return self

    # ---- transforms -----------------------------------------------------
    def rotated(self, a: float, c: Point = (0.0, 0.0)) -> "Profile":
        out = Profile(self.name)
        for it in self.items:
            k = it["kind"]
            if k == "line":
                out.line(rot(it["p1"], a, c), rot(it["p2"], a, c))
            elif k == "arc":
                out.arc(rot(it["c"], a, c), rot(it["p1"], a, c), rot(it["p2"], a, c), it["ccw"])
            elif k == "circle":
                out.circle(rot(it["c"], a, c), it["r"])
            elif k == "spline":
                out.spline([rot(p, a, c) for p in it["pts"]])
            elif k == "ellipse":
                out.ellipse(rot(it["c"], a, c), it["a"], it["b"], it["angle"] + a)
        return out

    # ---- sampling -------------------------------------------------------
    @staticmethod
    def sample_item(it: dict, seg_len: float = 0.25) -> list[Point]:
        k = it["kind"]
        if k == "line":
            return [it["p1"], it["p2"]]
        if k == "spline":
            return list(it["pts"])
        if k == "arc":
            c = it["c"]
            r = math.dist(c, it["p1"])
            a1 = math.atan2(it["p1"][1] - c[1], it["p1"][0] - c[0])
            a2 = math.atan2(it["p2"][1] - c[1], it["p2"][0] - c[0])
            if it["ccw"]:
                while a2 <= a1:
                    a2 += 2 * math.pi
            else:
                while a2 >= a1:
                    a2 -= 2 * math.pi
            n = max(2, int(abs(a2 - a1) * r / seg_len) + 1)
            return [(c[0] + r * math.cos(a1 + (a2 - a1) * i / (n - 1)),
                     c[1] + r * math.sin(a1 + (a2 - a1) * i / (n - 1))) for i in range(n)]
        if k == "circle":
            c, r = it["c"], it["r"]
            n = max(24, int(2 * math.pi * r / seg_len))
            return [polar_off(c, r, 2 * math.pi * i / n) for i in range(n + 1)]
        if k == "ellipse":
            c, a, b, th = it["c"], it["a"], it["b"], it["angle"]
            n = max(48, int(2 * math.pi * max(a, b) / seg_len))
            pts = []
            for i in range(n + 1):
                t = 2 * math.pi * i / n
                pts.append(rot((c[0] + a * math.cos(t), c[1] + b * math.sin(t)), th, c))
            return pts
        raise ValueError(k)

    def loops(self, seg_len: float = 0.25) -> list[list[Point]]:
        """Chain primitives into closed loops of sampled points."""
        loops, cur = [], []
        for it in self.items:
            pts = self.sample_item(it, seg_len)
            if it["kind"] in ("circle", "ellipse"):
                loops.append(pts)
                continue
            if cur and math.dist(cur[-1], pts[0]) < 1e-6:
                cur.extend(pts[1:])
            else:
                if cur:
                    loops.append(cur)
                cur = list(pts)
            if len(cur) > 2 and math.dist(cur[0], cur[-1]) < 1e-6:
                loops.append(cur)
                cur = []
        if cur:
            loops.append(cur)
        return loops

    def open_ends(self, tol: float = 1e-6) -> int:
        """Number of loops that are not closed (should be 0)."""
        return sum(1 for lp in self.loops() if math.dist(lp[0], lp[-1]) > tol)

    def bounds(self):
        xs, ys = [], []
        for lp in self.loops():
            xs += [p[0] for p in lp]
            ys += [p[1] for p in lp]
        return min(xs), min(ys), max(xs), max(ys)

    def to_json(self):
        return {"name": self.name, "items": self.items}


def polar_off(c: Point, r: float, a: float) -> Point:
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

def write_dxf(path, profiles: list[Profile]):
    """Minimal DXF R12 (opens in SolidWorks, Fusion, LibreCAD, laser cutters)."""
    out = ["0", "SECTION", "2", "ENTITIES"]

    def ent(*pairs):
        for code, val in pairs:
            out.extend([str(code), f"{val:.6f}" if isinstance(val, float) else str(val)])

    for prof in profiles:
        layer = (prof.name or "0").replace(" ", "_")
        for it in prof.items:
            k = it["kind"]
            if k == "line":
                ent((0, "LINE"), (8, layer), (10, it["p1"][0]), (20, it["p1"][1]), (11, it["p2"][0]), (21, it["p2"][1]))
            elif k == "circle":
                ent((0, "CIRCLE"), (8, layer), (10, it["c"][0]), (20, it["c"][1]), (40, it["r"]))
            elif k == "arc":
                c, p1, p2 = it["c"], it["p1"], it["p2"]
                if not it["ccw"]:
                    p1, p2 = p2, p1
                r = math.dist(c, p1)
                a1 = math.degrees(math.atan2(p1[1] - c[1], p1[0] - c[0])) % 360
                a2 = math.degrees(math.atan2(p2[1] - c[1], p2[0] - c[0])) % 360
                ent((0, "ARC"), (8, layer), (10, c[0]), (20, c[1]), (40, r), (50, a1), (51, a2))
            else:  # spline / ellipse -> polyline
                pts = Profile.sample_item(it, 0.1)
                ent((0, "POLYLINE"), (8, layer), (66, 1), (70, 0))
                for p in pts:
                    ent((0, "VERTEX"), (8, layer), (10, p[0]), (20, p[1]))
                ent((0, "SEQEND"), (8, layer))
    out += ["0", "ENDSEC", "0", "EOF"]
    Path(path).write_text("\n".join(out) + "\n")


def write_svg(path, layers: list[tuple[Profile, tuple[float, float, float], str]], margin: float = 3.0):
    """layers: (profile, (dx, dy, rotation), css colour). Quick visual check."""
    polys = []
    for prof, (dx, dy, ang), color in layers:
        p = prof.rotated(ang) if ang else prof
        for lp in p.loops(0.15):
            polys.append(([(x + dx, y + dy) for x, y in lp], color))
    xs = [x for lp, _ in polys for x, _ in lp]
    ys = [y for lp, _ in polys for _, y in lp]
    x0, x1, y0, y1 = min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin
    w, h = x1 - x0, y1 - y0
    body = []
    for lp, color in polys:
        d = " ".join(f"{x - x0:.3f},{y1 - y:.3f}" for x, y in lp)
        body.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{max(w, h) / 600:.3f}"/>')
    Path(path).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.3f} {h:.3f}" '
        f'width="{min(900, 9 * w):.0f}" style="background:#fff">\n' + "\n".join(body) + "\n</svg>\n")


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, default=lambda o: o.to_json() if hasattr(o, "to_json") else str(o)))


# ---------------------------------------------------------------------------
# Polygon helpers for interference checks
# ---------------------------------------------------------------------------

def points_in_polygon(px, py, poly):
    """Vectorised even-odd test. px, py: numpy arrays; poly: list of points."""
    import numpy as np
    poly = np.asarray(poly)
    x0, y0 = poly[:, 0], poly[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    px = np.asarray(px)[:, None]
    py = np.asarray(py)[:, None]
    cond = (y0 > py) != (y1 > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
    return np.count_nonzero(cond & (px < xint), axis=1) % 2 == 1


def self_intersections(loop) -> int:
    """Count proper crossings between non-adjacent segments of a closed loop."""
    import numpy as np
    p = np.asarray(loop[:-1] if math.dist(loop[0], loop[-1]) < 1e-9 else loop)
    a, b = p, np.roll(p, -1, axis=0)
    n = len(p)

    def cross(o, u, v):
        return (u[..., 0] - o[..., 0]) * (v[..., 1] - o[..., 1]) - (u[..., 1] - o[..., 1]) * (v[..., 0] - o[..., 0])

    A, B = a[:, None, :], b[:, None, :]
    C, D = a[None, :, :], b[None, :, :]
    d1, d2 = cross(A, B, C), cross(A, B, D)
    d3, d4 = cross(C, D, A), cross(C, D, B)
    hit = (d1 * d2 < 0) & (d3 * d4 < 0)
    i, j = np.triu_indices(n, k=2)
    mask = ~((i == 0) & (j == n - 1))
    return int(np.count_nonzero(hit[i[mask], j[mask]]))
