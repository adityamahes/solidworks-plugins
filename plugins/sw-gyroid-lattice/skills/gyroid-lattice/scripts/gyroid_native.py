#!/usr/bin/env python3
"""Native SolidWorks gyroid: a real .SLDPRT of B-spline faces (no mesh import).

Method (extends the "Schwarz P with SolidWorks sketches and features" GrabCAD approach):
  1. Unit cell (cached): the two wall surfaces f = +c and f = -c of the sheet gyroid
     |f| <= c, f = sin x cos y + sin y cos z + sin z cos x. Exact boundary curves are traced
     on a grid of sub-cubes, drawn as 3D-sketch splines and filled (InsertFillSurface2, boundary
     sketch selected with mark 257, no swOptimizeSurface). Each connected piece is knitted on its
     own, because Knit merges nothing if the selection splits into separate pieces.
  2. Copies of the cell side by side, half a cell beyond the part (Move/Copy Body).
  3. Each wall knitted into one continuous surface across all cells (the connected groups come
     from the exact geometry; a lone corner piece outside the part is ignored).
  4. The part's core is cut by both surfaces. The second cut's side comes from the surfaces'
     orientation, not their volume, because the wall and the other labyrinth are nearly equal.
     Optional --skin keeps a solid shell (Shell + Combine). Scrap solids are deleted.

Tested on SolidWorks 2025 SP5 (10 mm cell, 1 mm wall, within 2% of the exact volume):
  20 mm box 2510 mm3 (exact 2463), 20x20 mm cylinder 1959 (1935), box + 1.5 mm skin 4620 (4600).
  First build ~75 s for the unit cell, then ~70-90 s per part.

  python gyroid_native.py --cell 10 --wall 1.0 --shape box --size 20 20 20 --out out/
  python gyroid_native.py --cell 8 --wall 0.8 --target-part bracket.SLDPRT --skin 1.5 --out out/
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

PI = math.pi
# SolidWorks 2025 enum values, read from swconst.tlb
SW_FILL_OPTIONS = 0             # no swOptimizeSurface (=1): optimizing pulls edges ~0.1 mm off the boundary
SW_CONTACT = 0                  # swContactType_e.swContact
SW_THICKEN_BOTH = 2             # swThickenThicknessType_e.swThickenSideBoth
SW_BODY_INTERSECT = 15901       # swBodyOperationType_e.SWBODYINTERSECT
SW_BODY_ADD = 15903             # swBodyOperationType_e.SWBODYADD
SW_BODY_CUT = 15902             # swBodyOperationType_e.SWBODYCUT
SW_SOLID, SW_SHEET = 0, 1       # swBodyType_e
SEL_MARK_FILL_BOUNDARY = 257


def f(p):
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    return np.sin(x) * np.cos(y) + np.sin(y) * np.cos(z) + np.sin(z) * np.cos(x)


def grad(p):
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    sx, sy, sz, cx, cy, cz = np.sin(x), np.sin(y), np.sin(z), np.cos(x), np.cos(y), np.cos(z)
    return np.stack([cx * cy - sz * sx, -sx * sy + cy * cz, -sy * sz + cz * cx], -1)


def project(p, fixed_axis=None, iters=25):
    p = np.array(p, float)
    for _ in range(iters):
        g = grad(p)
        if fixed_axis is not None:
            g[..., fixed_axis] = 0
        gg = np.maximum((g * g).sum(-1, keepdims=True), 1e-12)
        p = p - (f(p)[..., None] / gg) * g
    return p


# ---------------------------------------------------------------------------
# Exact face curves
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def face_curve(axis: int, val_i: int, ui: int, vi: int, n: int = 240):
    """Gyroid trace on the cube face {coord[axis] = val_i*pi} x [ui*pi,(ui+1)*pi] x [vi*pi,(vi+1)*pi].
    Returns a tuple of corner-to-corner polylines (exact, Newton-projected)."""
    u_ax, v_ax = [a for a in range(3) if a != axis]
    val = val_i * PI
    u = np.linspace(ui * PI, (ui + 1) * PI, n)
    v = np.linspace(vi * PI, (vi + 1) * PI, n)
    U, V = np.meshgrid(u, v, indexing="ij")
    P = np.zeros(U.shape + (3,))
    P[..., axis], P[..., u_ax], P[..., v_ax] = val, U, V
    F = f(P)
    F = np.where(np.abs(F) < 1e-12, 1e-12, F)
    segs = _marching_squares(F, u, v)
    lines = _chain(segs)
    out = []
    for L in lines:
        Q = np.zeros((len(L), 3))
        Q[:, axis], Q[:, u_ax], Q[:, v_ax] = val, L[:, 0], L[:, 1]
        Q = project(Q, fixed_axis=axis)
        for end in (0, -1):                       # snap ends to exact cube corners
            c = np.round(Q[end] / PI) * PI
            if np.linalg.norm(Q[end] - c) < 0.05:
                Q[end] = c
        out.append(Q)
    return tuple(out)


def _marching_squares(F, u, v):
    n0, n1 = F.shape
    s = F > 0
    out = []
    a, b, c, d = F[:-1, :-1], F[1:, :-1], F[1:, 1:], F[:-1, 1:]
    sa, sb, sc, sd = s[:-1, :-1], s[1:, :-1], s[1:, 1:], s[:-1, 1:]
    I, J = np.meshgrid(np.arange(n0 - 1), np.arange(n1 - 1), indexing="ij")

    def pt(i0, j0, i1, j1, f0, f1):
        t = f0 / (f0 - f1)
        return np.stack([u[i0] + t * (u[i1] - u[i0]), v[j0] + t * (v[j1] - v[j0])], -1)

    e = [(sa != sb, lambda m: pt(I[m], J[m], I[m] + 1, J[m], a[m], b[m])),
         (sb != sc, lambda m: pt(I[m] + 1, J[m], I[m] + 1, J[m] + 1, b[m], c[m])),
         (sc != sd, lambda m: pt(I[m] + 1, J[m] + 1, I[m], J[m] + 1, c[m], d[m])),
         (sd != sa, lambda m: pt(I[m], J[m] + 1, I[m], J[m], d[m], a[m]))]
    cnt = sum(m.astype(int) for m, _ in e)
    two = cnt == 2
    pts = []
    for m, fn in e:
        mm = m & two
        pts.append((mm, fn(mm) if mm.any() else None))
    # collect per cell
    cells = {}
    for k, (mm, P) in enumerate(pts):
        if P is None:
            continue
        for (i, j), p in zip(zip(I[mm], J[mm]), P):
            cells.setdefault((i, j), []).append(p)
    for ps in cells.values():
        out.append((ps[0], ps[1]))
    return out


def _chain(segs, tol=1e-9):
    from collections import defaultdict
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    adj, pos = defaultdict(list), {}
    for a, b in segs:
        ka, kb = key(a), key(b)
        if ka == kb:
            continue
        pos[ka], pos[kb] = a, b
        adj[ka].append(kb)
        adj[kb].append(ka)
    seen, lines = set(), []
    for k in adj:
        if k in seen or len(adj[k]) != 1:
            continue
        line, prev, cur = [k], None, k
        seen.add(k)
        while True:
            nxt = [q for q in adj[cur] if q != prev and q not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            line.append(cur)
        lines.append(np.array([pos[q] for q in line]))
    return lines


def resample(P, k):
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    s = np.linspace(0, d[-1], k)
    return np.stack([np.interp(s, d, P[:, a]) for a in range(3)], 1)


def canonical(P, k=9):
    """Resample a corner-to-corner curve with a direction-independent point set."""
    if tuple(np.round(P[0], 9)) > tuple(np.round(P[-1], 9)):
        P = P[::-1]
    Q = resample(P, k)
    Q[0], Q[-1] = P[0], P[-1]
    return Q


def cube_hexagon(ci, cj, ck):
    """Six exact edge curves bounding the gyroid patch in cube (ci,cj,ck) of side pi."""
    idx = (ci, cj, ck)
    edges = []
    for axis in range(3):
        u_ax, v_ax = [a for a in range(3) if a != axis]
        for side in (0, 1):
            for L in face_curve(axis, idx[axis] + side, idx[u_ax], idx[v_ax]):
                edges.append(canonical(L))
    if len(edges) != 6:
        raise RuntimeError(f"cube {idx}: expected 6 face curves, found {len(edges)}")
    # order edges into a loop
    loop = [edges.pop(0)]
    while edges:
        end = loop[-1][-1]
        for i, e in enumerate(edges):
            if np.allclose(e[0], end, atol=1e-9):
                loop.append(edges.pop(i)); break
            if np.allclose(e[-1], end, atol=1e-9):
                loop.append(edges.pop(i)[::-1]); break
        else:
            raise RuntimeError(f"cube {idx}: face curves do not form a closed hexagon")
    return loop


def _split_curve(P, axis, value):
    """Split polyline P where coordinate `axis` crosses `value`; returns (before, point, after)."""
    s = P[:, axis] - value
    i = int(np.nonzero(np.sign(s[:-1]) != np.sign(s[1:]))[0][0])
    t = s[i] / (s[i] - s[i + 1])
    q = P[i] + t * (P[i + 1] - P[i])
    return np.vstack([P[:i + 1], q]), q, np.vstack([q, P[i + 1:]])


def _exact_point(q, fixed):
    """Newton-project q onto the gyroid keeping the axes in `fixed` constant."""
    q = np.array(q, float)
    for _ in range(40):
        g = grad(q)
        g[list(fixed)] = 0
        q = q - f(q) / max(g @ g, 1e-12) * g
    return q


def _half(P, k=7):
    """Direction-independent resample of a curve piece (shared with neighbours)."""
    return canonical(P, k)


def cube_sectors(ci, cj, ck):
    """Split the cube's gyroid hexagon into 6 four-sided patches meeting at the cube centre.

    The three mid-plane curves (patch ∩ {coord = mid}) pass through the centre and each
    end on two opposite hexagon edges, so every patch is bounded by exact gyroid curves:
    two half-edges on the cube faces and two half mid-curves inside the cube."""
    lo = np.array([ci, cj, ck], float) * PI
    mid = lo + PI / 2
    centre = mid.copy()
    hexa = cube_hexagon(ci, cj, ck)
    # split points: each edge crosses exactly one mid-plane (the coordinate that differs between its corners)
    halves, splits = [], []
    for e in hexa:
        dense = resample(e, 400)
        axis = int(np.argmax(np.abs(e[-1] - e[0])))
        face_axis = int(np.argmin([min(abs(dense[:, a] - lo[a]).max(), abs(dense[:, a] - lo[a] - PI).max())
                                   for a in range(3)]))
        a_part, q, b_part = _split_curve(dense, axis, mid[axis])
        q = _exact_point(q, {face_axis, axis})
        a_part[-1] = q
        b_part[0] = q
        halves.append((a_part, b_part))
        splits.append((q, axis))
    # interior curves: from each split point to the centre, along its mid-plane
    spokes = []
    for q, axis in splits:
        u_ax, v_ax = [a for a in range(3) if a != axis]
        line = np.linspace(q, centre, 60)
        line = project(line, fixed_axis=axis)
        line[0], line[-1] = q, centre
        spokes.append(line)
    sectors = []
    n = len(hexa)
    for i in range(n):
        j = (i + 1) % n
        loop = [_half(halves[i][1]),                 # split_i -> corner
                _half(halves[j][0]),                 # corner -> split_j
                canonical(spokes[j], 7),             # split_j -> centre
                canonical(spokes[i], 7)]             # centre -> split_i
        sectors.append(loop)
    return sectors


# ---------------------------------------------------------------------------
# SolidWorks build
# ---------------------------------------------------------------------------

INSERT_SOLIDS = 1          # swInsertPartOptions_e.swInsertPartImportSolids
INSERT_SURFACES = 2        # swInsertPartOptions_e.swInsertPartImportSurfaces
INSERT_DONT_ZOOM = 262144  # swInsertPartOptions_e.swInsertPartDontZoomAll


class Session:
    """One SolidWorks part document plus the helpers every stage needs."""

    def __init__(self, sw, part):
        from swkit.sw import flag_methods
        self.sw, self.part, self.doc = sw, part, part.doc
        self.sm, self.fm = part.sm, part.fm
        flag_methods(self.fm, "InsertFillSurface2", "InsertSewRefSurface", "InsertCombineFeature",
                     "InsertMoveCopyBody2", "FeatureExtrusion3", "InsertCutSurface", "InsertDeleteBody2")
        flag_methods(self.doc, "GetBodies2", "FeatureByPositionReverse", "ClearSelection2", "EditRebuild3",
                     "InsertPart3", "InsertFeatureShell", "EditUndo2")
        self.ext = self.doc.Extension
        flag_methods(self.ext, "SelectByID2", "CreateMassProperty")
        self.sel = self.doc.SelectionManager
        flag_methods(self.sel, "GetSelectedObject6")

    def fast(self, on: bool):
        """Stop SolidWorks redrawing / re-listing the tree after every call (3.5x faster)."""
        from swkit.sw import call0
        for fn in (lambda: setattr(self.sw.app, "CommandInProgress", on),
                   lambda: setattr(self.doc.FeatureManager, "EnableFeatureTree", not on),
                   lambda: setattr(call0(self.doc, "GetFirstModelView"), "EnableGraphicsUpdate", not on)):
            try:
                fn()
            except Exception:
                pass

    def bodies(self, kind):
        return list(self.doc.GetBodies2(kind, True) or [])

    def names(self, kind=SW_SOLID):
        return {b.Name for b in self.bodies(kind)}

    def select(self, bodies, mark=1, append=False):
        from swkit.sw import _nothing, call0
        if not append:
            self.doc.ClearSelection2(True)
        for b in bodies:
            kind = "SURFACEBODY" if call0(b, "GetType") == SW_SHEET else "SOLIDBODY"
            self.ext.SelectByID2(b.Name, kind, 0, 0, 0, True, mark, _nothing(), 0)

    def combine(self, op, main, tools, label):
        """As in the SOLIDWORKS Combine Bodies example: bodies pre-selected (main mark 1, tools
        mark 2; for Add all mark 2) and Nothing passed in."""
        import pythoncom
        from win32com.client import VARIANT
        from swkit.sw import _nothing
        self.doc.ClearSelection2(True)
        self.ext.SelectByID2(main.Name, "SOLIDBODY", 0, 0, 0, True, 2 if op == SW_BODY_ADD else 1, _nothing(), 0)
        for b in tools:
            self.ext.SelectByID2(b.Name, "SOLIDBODY", 0, 0, 0, True, 2, _nothing(), 0)
        if self.fm.InsertCombineFeature(op, _nothing(), VARIANT(pythoncom.VT_VARIANT, None)) is None:
            raise RuntimeError(f"Combine failed: {label}")

    def move_copy(self, bodies, dx, dy, dz, copies=0):
        """copies=0 moves; copies=n adds n translated copies. Returns the bodies that appeared."""
        kind = SW_SHEET if bodies and bodies[0].Name in self.names(SW_SHEET) else SW_SOLID
        before = self.names(kind)
        self.select(bodies, 1)
        if self.fm.InsertMoveCopyBody2(dx / 1000, dy / 1000, dz / 1000, 0, 0, 0, 0, 0, 0, 0,
                                       copies > 0, max(int(copies), 1)) is None:
            raise RuntimeError("Move/Copy Body failed")
        return [b for b in self.bodies(kind) if b.Name not in before]

    def knit(self, sheets, label):
        before = self.names(SW_SHEET)
        self.select(sheets, 1)
        if self.fm.InsertSewRefSurface(True, False, False, 1e-4, 2e-4) is None:
            raise RuntimeError(f"Knit failed: {label}")
        return [b for b in self.bodies(SW_SHEET) if b.Name not in before]

    def insert_part(self, path, options):
        before = self.names(SW_SOLID) | self.names(SW_SHEET)
        if self.doc.InsertPart3(str(path), options | INSERT_DONT_ZOOM, "") is None:
            raise RuntimeError(f"Insert Part failed for {path}")
        return [b for b in self.bodies(SW_SOLID) + self.bodies(SW_SHEET) if b.Name not in before]

    def volume(self, body):
        from swkit.sw import flag_methods
        mp = self.ext.CreateMassProperty()
        flag_methods(mp, "AddBodies")
        try:
            import pythoncom
            from win32com.client import VARIANT
            mp.AddBodies(VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [body]))
        except Exception:
            pass
        return mp.Volume * 1e9

    def cut_with_surface(self, body, sheet, keep_more, label, flip=None):
        """Cut `body` with `sheet`. If `flip` is None the side is chosen by volume (`keep_more` = keep the
        larger side); otherwise that flip is used as given. Returns (body, flip_used, kept_fraction)."""
        import pythoncom
        from win32com.client import VARIANT
        v0 = self.volume(body)
        others = {b.Name for b in self.bodies(SW_SOLID)} - {body.Name}
        name = body.Name
        for f in ((False, True) if flip is None else (flip,)):
            self.select([sheet], 0)
            err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            feat = self.fm.InsertCutSurface(f, 0, True, False,
                                            VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [body]), err)
            if feat is None:
                raise RuntimeError(f"Cut with surface failed: {label} (error {err.value})")
            # the cut can split the body; the pieces may not keep the original name on the big one
            pieces = [b for b in self.bodies(SW_SOLID) if b.Name not in others]
            v = sum(self.volume(b) for b in pieces)
            if flip is not None or (v > v0 / 2) == keep_more:
                return max(pieces, key=self.volume), f, v / v0
            self.doc.EditUndo2(1)
            body = [b for b in self.bodies(SW_SOLID) if b.Name == name][0]
        raise RuntimeError(f"Cut with surface kept the wrong side both ways: {label}")


def normal_sign(sheet, origin_mm, cell, faces=12):
    """+1 if the sheet's face normals point along grad f (towards larger f), -1 if against."""
    from swkit.sw import call0, flag_methods
    import gyroid_cell as GC
    total, fc, n = 0.0, call0(sheet, "GetFirstFace"), 0
    while fc is not None and n < faces:
        flag_methods(fc, "GetClosestPointOn", "GetBox")
        bb = np.array(call0(fc, "GetBox")).reshape(2, 3)
        q = np.array(fc.GetClosestPointOn(*bb.mean(0))[:3])
        surf = call0(fc, "GetSurface")
        flag_methods(surf, "EvaluateAtPoint")
        nrm = np.array(surf.EvaluateAtPoint(*q)[:3]) * (1 if call0(fc, "FaceInSurfaceSense") else -1)
        total += float(np.dot(nrm, GC.grad((q * 1000 - origin_mm) * 2 * PI / cell)))
        fc = call0(fc, "GetNextFace")
        n += 1
    return 1 if total > 0 else -1


def level_of(sheet, origin_mm, cell):
    """Which gyroid level (+c or -c) a sheet body lies on: evaluate f at a point on it."""
    from swkit.sw import call0
    import gyroid_cell as GC
    face = call0(sheet, "GetFirstFace")
    box = np.array(call0(sheet, "GetBodyBox"))
    from swkit.sw import flag_methods
    flag_methods(face, "GetClosestPointOn")
    p = np.array(face.GetClosestPointOn(*((box[:3] + box[3:]) / 2))[:3]) * 1000
    return float(GC.f((p - origin_mm) * 2 * PI / cell))


def build_unit_cell(sw, a, log):
    """Stage 1: the unit cell's two wall surfaces (f=+c, f=-c) from exact-boundary fills, knitted
    per level and saved as a cached surface part. Walls already have the requested thickness."""
    from swkit.sw import _arr, _nothing, call0
    import gyroid_cell as GC
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    key = f"gyroid_surfcell_{a.cell:g}mm_wall{a.wall:g}_sub{a.subdiv}_k{a.curve_points}"
    path = (cache / f"{key}.SLDPRT").resolve()
    meta = cache / f"{key}.json"
    if path.exists() and meta.exists() and not a.rebuild_cell:
        log(f"unit cell: reusing cached {path.name}")
        return path, json.loads(meta.read_text())
    c = GC.wall_to_level(a.wall, a.cell)
    m = 0.001 * a.cell / (2 * PI)
    msub = 2 * a.subdiv
    groups = {+1: [], -1: []}
    for cube in [(i, j, k) for i in range(msub) for j in range(msub) for k in range(msub)]:
        for sgn in (+1, -1):
            groups[sgn] += GC.cube_loops(cube, sgn * c, a.curve_points, a.subdiv)
    s = Session(sw, sw.new_part(key))
    doc, sm, fm, ext, sel = s.doc, s.sm, s.fm, s.ext, s.sel
    made = {+1: [], -1: []}
    made_loop = {+1: [], -1: []}       # fill body for each loop, in loop order
    n = 0
    s.fast(True)
    try:
        for sgn in (+1, -1):
            for loop in groups[sgn]:
                before = s.names(SW_SHEET)
                sm.Insert3DSketch(True)
                sm.AddToDB = True                  # shared curves must be identical on both sides
                for cv in loop:
                    P = cv * m
                    if sm.CreateSpline2(_arr(P.ravel()), False) is None:
                        raise RuntimeError("sketch spline rejected")
                sm.AddToDB = False
                sm.Insert3DSketch(True)
                sk = doc.FeatureByPositionReverse(0)
                doc.ClearSelection2(True)
                ext.SelectByID2(sk.Name, "SKETCH", 0, 0, 0, False, SEL_MARK_FILL_BOUNDARY, _nothing(), 0)
                if fm.InsertFillSurface2(2, SW_FILL_OPTIONS, sel.GetSelectedObject6(1, SEL_MARK_FILL_BOUNDARY),
                                         SW_CONTACT, None, None) is None:
                    raise RuntimeError("fill surface failed")
                new = [b for b in s.bodies(SW_SHEET) if b.Name not in before]
                made[sgn] += new
                made_loop[sgn].append(new[0])
                n += 1
                if n % 50 == 0:
                    log(f"  unit cell: {n}/{len(groups[1]) + len(groups[-1])} surfaces")
        # Knit is all-or-nothing: a selection that splits into separate pieces knits nothing.
        # Within one cell each level has a lone corner patch, so knit piece by piece.
        for sgn in (+1, -1):
            for piece in GC.sheet_pieces(groups[sgn]):
                if len(piece["loops"]) > 1:
                    merged = s.knit([made_loop[sgn][i] for i in piece["loops"]], f"unit cell level {sgn:+d}c")
                    if len(merged) != 1:
                        raise RuntimeError(f"unit cell piece of {len(piece['loops'])} patches knitted into {len(merged)}")
    finally:
        s.fast(False)
    call0(doc, "EditRebuild3")
    info = {"cell_mm": a.cell, "wall_mm": a.wall, "level_c": round(c, 4), "surfaces": n,
            "solid_fraction_exact": round(GC.volume_fraction(c), 4)}
    s.part.name = key
    s.part.save(cache)
    meta.write_text(json.dumps(info, indent=2))
    sw.app.CloseDoc(str(path))
    log(f"unit cell: {n} exact-boundary surfaces, knitted into the two wall faces (c = {c:.3f})")
    return path, info


def GC_exact_level(a):
    import gyroid_cell as GC
    return GC.wall_to_level(a.wall, a.cell)


def knit_lattice_level(s, sheets, sgn, c, a, start, n, part_lo, part_size, log):
    """Knit one level's pieces across all cells into one continuous wall surface.

    Each SolidWorks sheet body is matched to its (cell, piece) by bounding-box centre, the
    connected groups come from the exact geometry (gyroid_cell.lattice_groups), and each group
    is knitted on its own. Returns the main (largest) wall surface; small leftover groups must
    lie outside the part (they sit in the half-cell margin around it)."""
    import gyroid_cell as GC
    from swkit.sw import call0
    msub = 2 * a.subdiv
    loops = [L for cube in [(i, j, k) for i in range(msub) for j in range(msub) for k in range(msub)]
             for L in GC.cube_loops(cube, sgn * c, a.curve_points, a.subdiv)]
    pieces = GC.sheet_pieces(loops)
    k = a.cell / (2 * PI)
    expected = {}
    for ci in np.ndindex(*n):
        for pi, pc in enumerate(pieces):
            expected[(ci, pi)] = start + np.array(ci) * a.cell + np.array(pc["center"]) * k
    keys = list(expected)
    centres = np.array([expected[kk] for kk in keys])
    owner = {}
    for b in sheets:
        raw = call0(b, "GetBodyBox")
        if raw is None:
            continue
        box = np.array(raw) * 1000
        mid = (box[:3] + box[3:]) / 2
        d = np.linalg.norm(centres - mid, axis=1)
        j = int(np.argmin(d))
        # SolidWorks bounding boxes of B-spline sheets are loose (a lone corner patch's centre is off by
        # ~0.03 cell); pieces of one level are >= ~0.5 cell apart, so 0.15 cell is unambiguous.
        if d[j] < 0.15 * a.cell and abs(level_of(b, start, a.cell) - sgn * c) < 0.05:
            if keys[j] in owner:
                raise RuntimeError(f"two SolidWorks bodies matched the same {sgn:+d}c piece {keys[j]}")
            owner[keys[j]] = b
    if len(owner) != len(keys):
        raise RuntimeError(f"matched {len(owner)} of {len(keys)} {sgn:+d}c surface pieces to SolidWorks bodies")
    groups = GC.lattice_groups(pieces, n)
    main = s.knit([owner[g] for g in groups[0]], f"{sgn:+d}c wall surface")
    if len(main) != 1:
        raise RuntimeError(f"{sgn:+d}c wall: {len(groups[0])} pieces knitted into {len(main)} bodies, expected 1")
    hi = part_lo + part_size
    for g in groups[1:]:
        for kk in g:
            box = np.array(call0(owner[kk], "GetBodyBox")) * 1000
            if np.all(box[:3] < hi) and np.all(box[3:] > part_lo):
                raise RuntimeError(f"a detached {sgn:+d}c surface piece overlaps the part; enlarge the margin")
    log(f"{sgn:+d}c wall: {len(groups[0])} pieces knitted into one surface "
        f"({sum(len(g) for g in groups[1:])} detached corner pieces outside the part ignored)")
    return main[0]


def build_target(sw, a, out):
    p = sw.new_part(f"{a.name}_target")
    p.extrude(_domain_profile(a), a.size[2], 0)
    path = p.save(out)
    sw.app.CloseDoc(path)
    return Path(path)


def build(a):
    """1 surface unit cell (cached) -> 2 new part: copies side by side, larger than the part, knitted
    into two continuous wall surfaces -> 3 walls are at the requested thickness by construction
    -> 4 part's core cut with both surfaces (keeps |f| <= c), plus a solid skin -> final part."""
    from swkit.sw import SolidWorks, call0
    t0 = time.time()

    def log(msg):
        print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)

    sw = SolidWorks()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cell_path, cell_info = build_unit_cell(sw, a, log)
    target_path = Path(a.target_part).resolve() if a.target_part else build_target(sw, a, out)
    if not target_path.exists():
        sys.exit(f"target part not found: {target_path}")

    s = Session(sw, sw.new_part(a.name))
    s.fast(True)
    try:
        target = s.insert_part(target_path, INSERT_SOLIDS)
        if len(target) > 1:
            s.combine(SW_BODY_ADD, target[0], target[1:], "merge target bodies")
        target = s.bodies(SW_SOLID)[0]
        box = [v * 1000 for v in call0(target, "GetBodyBox")]
        lo, size = np.array(box[:3]), np.array(box[3:]) - np.array(box[:3])

        # 2. lattice of surface cells, half a cell larger than the part on every side
        start = lo - a.cell / 2
        n = np.ceil((size + a.cell) / a.cell).astype(int)
        cell_sheets = s.insert_part(cell_path, INSERT_SURFACES)
        s.move_copy(cell_sheets, *start)
        for axis in range(3):
            if n[axis] > 1:
                d = [0.0, 0.0, 0.0]
                d[axis] = a.cell
                s.move_copy(s.bodies(SW_SHEET), *d, copies=n[axis] - 1)
        sheets = s.bodies(SW_SHEET)
        log(f"lattice: {n[0]} x {n[1]} x {n[2]} cells placed ({len(sheets)} surface bodies)")
        walls = {}
        for sgn in (+1, -1):
            walls[sgn] = knit_lattice_level(s, s.bodies(SW_SHEET), sgn, GC_exact_level(a), a, start, n, lo, size, log)  # fresh: a knit consumes bodies
        wall_plus, wall_minus = [walls[+1]], [walls[-1]]

        # 4. core of the part, cut by both wall surfaces; optional solid skin
        skin = None
        if a.skin > 0:
            others = s.names()
            skin = s.move_copy([target], 0, 0, 0, copies=1)[0]
            s.select([skin], 0)
            s.doc.InsertFeatureShell(a.skin / 1000, False)
            skin = [b for b in s.bodies(SW_SOLID) if b.Name not in others][0]
            tool = s.move_copy([skin], 0, 0, 0, copies=1)[0]
            core = [b for b in s.bodies(SW_SOLID) if b.Name in others][0]
            s.combine(SW_BODY_CUT, core, [tool], "core = part minus skin")
            core = [b for b in s.bodies(SW_SOLID) if b.Name != skin.Name][0]
        else:
            core = target
        frac = cell_info["solid_fraction_exact"]
        # Cut 1 keeps f <= +c: about (1+frac)/2 of the core, clearly the larger side.
        core, flip1, r1 = s.cut_with_surface(core, wall_plus[0], True, "remove f > +c")
        # Cut 2 must keep the wall (frac of the core) and remove f < -c ((1-frac)/2): nearly equal
        # volumes, so pick the side from the surfaces' orientation instead. Cut 1 removed the +grad side
        # of the +c sheet with flip1; the -c sheet must lose its -grad side.
        same = normal_sign(wall_plus[0], start, a.cell) == -normal_sign(wall_minus[0], start, a.cell)
        core, flip2, r2 = s.cut_with_surface(core, wall_minus[0], None, "remove f < -c",
                                             flip=flip1 if same else (not flip1))
        expect = 2 * frac / (1 + frac)
        if abs(r2 - expect) > 0.25 * expect:
            raise RuntimeError(f"second cut kept {r2:.3f} of the core; the wall should be ~{expect:.3f}")
        log(f"core cut by both wall surfaces (kept {r1:.3f}, then {r2:.3f}; wall expected ~{expect:.3f})")
        if skin is not None:
            rest = [b for b in s.bodies(SW_SOLID) if b.Name != skin.Name]
            s.combine(SW_BODY_ADD, skin, rest, "skin + gyroid core")
            log("skin and gyroid core combined")
        # delete clipping scraps: tiny solids where a wall grazes a corner of the part
        solids = s.bodies(SW_SOLID)
        vols = {b.Name: s.volume(b) for b in solids}
        scraps = [b for b in solids if vols[b.Name] < 0.005 * max(vols.values())]
        if scraps:
            scrap_vol = sum(vols[b.Name] for b in scraps)
            s.select(scraps, 0)
            s.fm.InsertDeleteBody2(False)
            log(f"deleted {len(scraps)} scrap solid(s), {scrap_vol:.2f} mm3 in total")
        # hide the construction surfaces
        for b in s.bodies(SW_SHEET):
            try:
                b.HideBody(True)
            except Exception:
                pass
    finally:
        s.fast(False)
    call0(s.doc, "EditRebuild3")
    path = s.part.save(out)
    solids = s.bodies(SW_SOLID)
    vol = sum(s.volume(b) for b in solids) if len(solids) > 1 else s.volume(solids[0])
    report = {"part": path, "target": str(target_path), "unit_cell": str(cell_path), "unit_cell_info": cell_info,
              "cell_mm": a.cell, "wall_mm": a.wall, "skin_mm": a.skin, "cells": int(n.prod()),
              "solid_bodies": len(solids), "volume_mm3": round(vol, 1), "seconds": round(time.time() - t0, 1)}
    (out / f"{a.name}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def _domain_profile(a):
    from swkit.geometry import Profile
    p = Profile("domain")
    x, y = a.size[0], a.size[1]
    if a.shape == "cylinder":
        p.circle((x / 2, x / 2), x / 2)
    else:
        p.line((0, 0), (x, 0)).line((x, 0), (x, y)).line((x, y), (0, y)).line((0, y), (0, 0))
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=float, default=10.0, help="unit cell size, mm")
    ap.add_argument("--wall", type=float, default=1.0, help="wall thickness, mm")
    ap.add_argument("--shape", default="box", choices=["box", "cylinder"])
    ap.add_argument("--size", type=float, nargs=3, default=[20, 20, 20], metavar=("X", "Y", "Z"),
                    help="box extents (cylinder: DIA DIA HEIGHT), mm")
    ap.add_argument("--target-part", help="SLDPRT to give a gyroid core (default: box/cylinder from --shape/--size)")
    ap.add_argument("--skin", type=float, default=0.0,
                    help="solid skin kept from the original part, mm (0 = lattice only, cut to the part's shape)")
    ap.add_argument("--curve-points", type=int, default=17, help="points per exact boundary spline (accuracy)")
    ap.add_argument("--subdiv", type=int, default=2, help="trace on cubes of cell/(2*subdiv): higher = more accurate")
    ap.add_argument("--cache", default=str(Path.home() / "Documents" / "gyroid_cells"),
                    help="folder for cached unit-cell parts (same specs are never rebuilt)")
    ap.add_argument("--rebuild-cell", action="store_true", help="ignore the cached unit cell")
    ap.add_argument("--name", default="gyroid_part")
    ap.add_argument("--out", default="gyroid_native_out")
    ap.add_argument("--dry-run", action="store_true", help="only validate the patch geometry (no SolidWorks)")
    a = ap.parse_args(argv)
    if a.wall >= a.cell / 6:
        sys.exit("wall must be < cell/6 (level surfaces would merge)")
    if a.dry_run:
        import gyroid_cell as GC
        c = GC.wall_to_level(a.wall, a.cell)
        msub = 2 * a.subdiv
        for sgn in (+1, -1):
            loops = [L for cube in [(i, j, k) for i in range(msub) for j in range(msub) for k in range(msub)]
                     for L in GC.cube_loops(cube, sgn * c, a.curve_points, a.subdiv)]
            pieces = GC.sheet_pieces(loops)
            groups = GC.lattice_groups(pieces, (3, 3, 3))
            print(f"OK {sgn:+d}c wall: {len(loops)} exact-boundary surfaces per cell in {len(pieces)} pieces; "
                  f"3x3x3 cells -> {len(groups[0])} pieces knit into one surface, {len(groups) - 1} detached")
        print(f"level c = {c:.4f}, exact solid fraction {GC.volume_fraction(c):.4f}")
        return
    build(a)


if __name__ == "__main__":
    main()
