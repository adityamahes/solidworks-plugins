"""Exact geometry for a solid sheet-gyroid unit cell:  -c <= f <= +c,
f = sin x cos y + sin y cos z + sin z cos x  (cell = 2*pi in gyroid units).

Boundary of the solid inside one unit cell =
  * the level surfaces f = +c and f = -c   (two disk patches per pi-cube per level)
  * planar caps on the six cell faces where |f| <= c.
Every patch/cap is bounded by exact curves traced on the pi-cube faces; curve
end points are solved exactly on the cube edges, so neighbouring patches and
caps share bit-identical edges and knit into a closed solid.
"""
from __future__ import annotations

import math
from collections import defaultdict
from functools import lru_cache

import numpy as np

PI = math.pi


def f(p):
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    return np.sin(x) * np.cos(y) + np.sin(y) * np.cos(z) + np.sin(z) * np.cos(x)


def grad(p):
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    sx, sy, sz, cx, cy, cz = np.sin(x), np.sin(y), np.sin(z), np.cos(x), np.cos(y), np.cos(z)
    return np.stack([cx * cy - sz * sx, -sx * sy + cy * cz, -sy * sz + cz * cx], -1)


def newton(p, level, fixed, iters=60):
    p = np.array(p, float)
    for _ in range(iters):
        g = grad(p)
        g[..., list(fixed)] = 0
        gg = np.maximum((g * g).sum(-1, keepdims=True), 1e-14)
        p = p - ((f(p) - level)[..., None] / gg) * g
    return p


def resample(P, k):
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    s = np.linspace(0, d[-1], k)
    return np.stack([np.interp(s, d, P[:, a]) for a in range(3)], 1)


def _key(p):
    return tuple(np.round(np.asarray(p) / PI * 1e7).astype(np.int64))


def canonical(P, k):
    """Direction-independent resample so neighbours reuse identical points."""
    if _key(P[0]) > _key(P[-1]):
        P = P[::-1]
    Q = resample(P, k)
    Q[0], Q[-1] = P[0], P[-1]
    return Q


# ---------------------------------------------------------------------------
# exact traces on a pi-face
# ---------------------------------------------------------------------------

def _march(F, u, v):
    s = F > 0
    a, b, c, d = F[:-1, :-1], F[1:, :-1], F[1:, 1:], F[:-1, 1:]
    sa, sb, sc, sd = s[:-1, :-1], s[1:, :-1], s[1:, 1:], s[:-1, 1:]
    I, J = np.meshgrid(np.arange(F.shape[0] - 1), np.arange(F.shape[1] - 1), indexing="ij")
    edges = [(sa != sb, I, J, I + 1, J, a, b), (sb != sc, I + 1, J, I + 1, J + 1, b, c),
             (sc != sd, I + 1, J + 1, I, J + 1, c, d), (sd != sa, I, J + 1, I, J, d, a)]
    cells = defaultdict(list)
    for m, i0, j0, i1, j1, f0, f1 in edges:
        t = f0[m] / (f0[m] - f1[m])
        pu = u[i0[m]] + t * (u[i1[m]] - u[i0[m]])
        pv = v[j0[m]] + t * (v[j1[m]] - v[j0[m]])
        for ci, cj, x, y in zip(I[m], J[m], pu, pv):
            cells[(ci, cj)].append((x, y))
    segs = []
    for ps in cells.values():
        if len(ps) == 2:
            segs.append((ps[0], ps[1]))
        elif len(ps) == 4:
            segs += [(ps[0], ps[1]), (ps[2], ps[3])]
    return segs


def _chain2d(segs, tol=1e-10):
    adj, pos = defaultdict(list), {}
    k = lambda p: (round(p[0] / tol), round(p[1] / tol))
    for a, b in segs:
        ka, kb = k(a), k(b)
        if ka != kb:
            pos[ka], pos[kb] = a, b
            adj[ka].append(kb)
            adj[kb].append(ka)
    seen, lines = set(), []
    ends = [q for q in adj if len(adj[q]) == 1] + [q for q in adj if len(adj[q]) != 1]
    for s0 in ends:
        if s0 in seen:
            continue
        line, prev, cur = [s0], None, s0
        seen.add(s0)
        while True:
            nxt = [q for q in adj[cur] if q != prev and q not in seen]
            if not nxt:
                if len(line) > 2 and s0 in adj[cur] and cur != s0:
                    line.append(s0)            # closed loop
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            line.append(cur)
        lines.append(np.array([pos[q] for q in line]))
    return lines


@lru_cache(maxsize=None)
def face_traces(axis, val_i, ui, vi, level, sub=1, n=200):
    """Curves of f = level on the pi-face {coord[axis] = val_i*pi} x [ui, ui+1]pi x [vi, vi+1]pi.
    Open curves run edge to edge; their end points are exact roots on the face edges."""
    H = PI / sub
    u_ax, v_ax = [a for a in range(3) if a != axis]
    lo_u, lo_v = ui * H, vi * H
    u = np.linspace(lo_u, lo_u + H, n)
    v = np.linspace(lo_v, lo_v + H, n)
    U, V = np.meshgrid(u, v, indexing="ij")
    P = np.zeros(U.shape + (3,))
    P[..., axis], P[..., u_ax], P[..., v_ax] = val_i * H, U, V
    F = f(P) - level
    F = np.where(np.abs(F) < 1e-13, 1e-13, F)
    out = []
    for L in _chain2d(_march(F, u, v)):
        Q = np.zeros((len(L), 3))
        Q[:, axis], Q[:, u_ax], Q[:, v_ax] = val_i * H, L[:, 0], L[:, 1]
        Q = newton(Q, level, {axis})
        closed = np.linalg.norm(Q[0] - Q[-1]) < 1e-9
        if not closed:
            for end in (0, -1):                 # exact root on the face edge
                e = Q[end].copy()
                best = None
                for a, lo in ((u_ax, lo_u), (v_ax, lo_v)):
                    for bound in (lo, lo + H):
                        d = abs(e[a] - bound)
                        if best is None or d < best[0]:
                            best = (d, a, bound)
                if best[0] > 3 * H / n:
                    raise RuntimeError("trace does not end on the face boundary")
                _, a, bound = best
                e[a] = bound
                Q[end] = newton(e, level, {axis, a}, iters=80)
        out.append(Q)
    return tuple(out)


# ---------------------------------------------------------------------------
# patches and caps
# ---------------------------------------------------------------------------

def cube_loops(cube, level, k=9, sub=1):
    """Closed boundary loops (list of curves) of f=level inside the cube of side pi/sub."""
    idx = np.array(cube)
    curves = []
    for axis in range(3):
        u_ax, v_ax = [a for a in range(3) if a != axis]
        for side in (0, 1):
            for Q in face_traces(axis, int(idx[axis] + side), int(idx[u_ax]), int(idx[v_ax]), level, sub):
                curves.append(canonical(Q, k))
    return _chain_loops(curves)


def _chain_loops(curves):
    loops = []
    pool = list(curves)
    while pool:
        first = pool.pop(0)
        if _key(first[0]) == _key(first[-1]):
            loops.append([first])
            continue
        loop = [first]
        while _key(loop[-1][-1]) != _key(loop[0][0]):
            end = _key(loop[-1][-1])
            for i, c in enumerate(pool):
                if _key(c[0]) == end:
                    loop.append(pool.pop(i)); break
                if _key(c[-1]) == end:
                    loop.append(pool.pop(i)[::-1]); break
            else:
                raise RuntimeError("level-surface boundary curves do not close")
        loops.append(loop)
    return loops


def face_caps(axis, val_i, ui, vi, c, k=9, sub=1):
    """Closed loops bounding {|f| <= c} on one pi-face of the cell boundary.
    Pieces: traces of f=+c and f=-c, and straight runs along the face edges."""
    u_ax, v_ax = [a for a in range(3) if a != axis]
    lo = np.zeros(3)
    H = PI / sub
    lo[axis], lo[u_ax], lo[v_ax] = val_i * H, ui * H, vi * H
    curves = [canonical(Q, k) for lev in (c, -c) for Q in face_traces(axis, val_i, ui, vi, lev, sub)]
    # perimeter parameter of a point on the face boundary (counter-clockwise in (u, v))
    def per(p):
        a, b = (p[u_ax] - lo[u_ax]) / H, (p[v_ax] - lo[v_ax]) / H
        if abs(b) < 1e-7: return a
        if abs(a - 1) < 1e-7: return 1 + b
        if abs(b - 1) < 1e-7: return 3 - a
        return 4 - b
    def at(t):
        t %= 4
        p = lo.copy()
        a, b = ((t, 0) if t < 1 else (1, t - 1) if t < 2 else (3 - t, 1) if t < 3 else (0, 4 - t))
        p[u_ax] += a * H
        p[v_ax] += b * H
        return p
    ends = sorted({round(per(Q[e]), 12): Q[e] for Q in curves if _key(Q[0]) != _key(Q[-1]) for e in (0, -1)}.items())
    runs = []
    if not ends:   # no traces: whole face is inside or outside
        if abs(f(at(0.5))) <= c:
            corners = [at(t) for t in (0, 1, 2, 3, 4)]
            runs = [np.array([corners[i], corners[i + 1]]) for i in range(4)]
    for i, (t0, p0) in enumerate(ends):
        t1, p1 = ends[(i + 1) % len(ends)]
        if t1 <= t0:
            t1 += 4
        if abs(f(at((t0 + t1) / 2))) <= c:        # this stretch of edge is inside the wall
            pts = [p0] + [at(t) for t in (1, 2, 3, 4, 5, 6, 7) if t0 < t < t1] + [p1]
            for a_, b_ in zip(pts[:-1], pts[1:]):
                runs.append(np.array([a_, b_]))
    return _chain_loops(curves + runs)


def unit_cell(c, k=9, sub=1):
    """Boundary loops of the solid unit cell [0, 2pi]^3, traced on a grid of cubes of side pi/sub.
    Smaller cubes -> smaller, flatter fill patches -> closer to the exact gyroid."""
    m = 2 * sub
    patches = []
    for cube in [(i, j, kk) for i in range(m) for j in range(m) for kk in range(m)]:
        for lev in (c, -c):
            patches += cube_loops(cube, lev, k, sub)
    caps = []
    for axis in range(3):
        for val in (0, m):
            for ui in range(m):
                for vi in range(m):
                    caps += face_caps(axis, val, ui, vi, c, k, sub)
    return patches, caps


def pockets(loops):
    """Groups of loops that share edges (each group closes into one solid)."""
    def ckey(cv):
        a, b = _key(cv[0]), _key(cv[-1])
        return (min(a, b), max(a, b), _key(cv.mean(0)))
    by = defaultdict(list)
    for i, L in enumerate(loops):
        for cv in L:
            by[ckey(cv)].append(i)
    bad = [k_ for k_, v in by.items() if len(v) != 2]
    if bad:
        raise RuntimeError(f"{len(bad)} boundary curves are not shared by exactly two faces")
    adj = defaultdict(set)
    for v in by.values():
        adj[v[0]].add(v[1])
        adj[v[1]].add(v[0])
    comps, seen = [], set()
    for i in range(len(loops)):
        if i in seen:
            continue
        st, comp = [i], []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            st += adj[x]
        comps.append(sorted(comp))
    return comps


def wall_to_level(wall, cell):
    """c giving the requested mean wall thickness (mm) for a cell size (mm)."""
    rng = np.random.default_rng(0)
    Q = newton(rng.uniform(0, 2 * PI, (20000, 3)), 0.0, set())
    g = np.linalg.norm(grad(Q), axis=1)
    k = cell / (2 * PI)
    return float(wall / (2 * k * np.mean(1 / g)))


def volume_fraction(c, n=3_000_000, seed=5):
    """Exact solid fraction of the sheet |f| <= c (Monte Carlo, +-0.05%)."""
    P = np.random.default_rng(seed).uniform(0, 2 * PI, (n, 3))
    return float(np.mean(np.abs(f(P)) <= c))


# ---------------------------------------------------------------------------
# connectivity: SolidWorks Knit is all-or-nothing, so surfaces are knitted one
# connected group at a time. Within one unit cell each level surface splits into
# pieces (e.g. a lone corner patch) that only join up through neighbouring cells.
# ---------------------------------------------------------------------------

def _curve_key(cv):
    a, b = _key(cv[0]), _key(cv[-1])
    return (min(a, b), max(a, b), _key(cv.mean(0)))


def sheet_pieces(loops):
    """Connected pieces of an open sheet made of fill loops.
    Returns [{'loops': [i...], 'boundary': set(curve keys used once), 'center': xyz (gyroid units)}]."""
    by = defaultdict(list)
    for i, L in enumerate(loops):
        for cv in L:
            by[_curve_key(cv)].append(i)
    adj = defaultdict(set)
    for v in by.values():
        for x in v:
            for y in v:
                if x != y:
                    adj[x].add(y)
    seen, out = set(), []
    for i in range(len(loops)):
        if i in seen:
            continue
        st, comp = [i], []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            st += adj[x]
        keys = [_curve_key(cv) for j in comp for cv in loops[j]]
        counts = defaultdict(int)
        for kk in keys:
            counts[kk] += 1
        pts = np.vstack([cv for j in comp for cv in loops[j]])
        out.append({"loops": sorted(comp), "boundary": {kk for kk, n in counts.items() if n == 1},
                    "center": ((pts.min(0) + pts.max(0)) / 2).tolist()})
    return out


def _shift_key(k, d):
    """Translate a curve key by d unit cells (2*pi each): keys are round(coord/pi*1e7)."""
    s = np.array(d, dtype=np.int64) * 20_000_000
    return tuple(tuple(int(c) for c in np.array(part) + s) for part in k)


def lattice_groups(pieces, n):
    """Connected groups of (cell_index, piece_index) across an n[0] x n[1] x n[2] block of cells.
    Pieces in neighbouring cells connect where they share a (translated) boundary curve."""
    owner = {}
    for ci in np.ndindex(*n):
        for pi, p in enumerate(pieces):
            for kk in p["boundary"]:
                owner.setdefault(_shift_key(kk, ci), []).append((ci, pi))
    adj = defaultdict(set)
    for v in owner.values():
        for x in v:
            for y in v:
                if x != y:
                    adj[x].add(y)
    nodes = [(ci, pi) for ci in np.ndindex(*n) for pi in range(len(pieces))]
    seen, groups = set(), []
    for nd in nodes:
        if nd in seen:
            continue
        st, comp = [nd], []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            st += adj[x]
        groups.append(comp)
    groups.sort(key=len, reverse=True)
    return groups
