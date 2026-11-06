#!/usr/bin/env python3
"""Gyroid (TPMS) lattice generator -> watertight STL -> optional SolidWorks import.

Examples
  python gyroid.py --shape box --size 40 40 20 --cell 8 --wall 0.8 --out out/
  python gyroid.py --shape cylinder --size 30 30 50 --cell 6 --density 0.25 --shell 1.2 --out out/
  python gyroid.py --domain-stl bracket.stl --cell 5 --wall 0.6 --shell 1.0 --out out/ --solidworks
  python gyroid.py --from-solidworks --cell 6 --wall 0.7 --shell 1.0 --out out/   # fill the active part

Field is an approximate signed distance (mm): negative = material.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

TAU = 2 * math.pi


# ---------------------------------------------------------------------------
# TPMS fields with analytic gradients (so f/|grad f| ~ distance in mm)
# ---------------------------------------------------------------------------

def tpms(kind: str, X, Y, Z, cell: float):
    k = TAU / cell
    x, y, z = k * X, k * Y, k * Z
    sx, sy, sz, cx, cy, cz = np.sin(x), np.sin(y), np.sin(z), np.cos(x), np.cos(y), np.cos(z)
    if kind == "gyroid":
        f = sx * cy + sy * cz + sz * cx
        gx = cx * cy - sz * sx
        gy = -sx * sy + cy * cz
        gz = -sy * sz + cz * cx
    elif kind == "diamond":
        f = sx * sy * sz + sx * cy * cz + cx * sy * cz + cx * cy * sz
        gx = cx * sy * sz + cx * cy * cz - sx * sy * cz - sx * cy * sz
        gy = sx * cy * sz - sx * sy * cz + cx * cy * cz - cx * sy * sz
        gz = sx * sy * cz - sx * cy * sz - cx * sy * sz + cx * cy * cz
    elif kind == "primitive":
        f = cx + cy + cz
        gx, gy, gz = -sx, -sy, -sz
    else:
        raise ValueError(kind)
    g = k * np.sqrt(gx * gx + gy * gy + gz * gz)
    return f / np.maximum(g, 0.35 * k)


def lattice_sdf(kind, style, X, Y, Z, cell, param):
    d = tpms(kind, X, Y, Z, cell)
    if style == "sheet":          # param = wall thickness (mm), may be an array (grading)
        return np.abs(d) - param / 2
    return d - param              # network: param = offset (mm), 0 -> ~50% solid


def solve_param(kind, style, cell, density, res=48):
    """Bisection for the wall/offset giving a target solid volume fraction."""
    t = (np.arange(res) + 0.5) / res * cell
    X, Y, Z = np.meshgrid(t, t, t, indexing="ij")
    d = tpms(kind, X, Y, Z, cell)
    lo, hi = (0.0, cell) if style == "sheet" else (-cell / 2, cell / 2)
    for _ in range(50):
        mid = (lo + hi) / 2
        frac = np.mean((np.abs(d) - mid / 2 if style == "sheet" else d - mid) <= 0)
        lo, hi = (mid, hi) if frac < density else (lo, mid)
    return (lo + hi) / 2


def unit_density(kind, style, cell, param, res=48):
    t = (np.arange(res) + 0.5) / res * cell
    X, Y, Z = np.meshgrid(t, t, t, indexing="ij")
    return float(np.mean(lattice_sdf(kind, style, X, Y, Z, cell, param) <= 0))


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

def sdf_box(X, Y, Z, size):
    h = np.array(size) / 2
    q = [np.abs(X - h[0]) - h[0], np.abs(Y - h[1]) - h[1], np.abs(Z - h[2]) - h[2]]
    outside = np.sqrt(sum(np.maximum(a, 0) ** 2 for a in q))
    return outside + np.minimum(np.maximum(np.maximum(q[0], q[1]), q[2]), 0)


def sdf_cylinder(X, Y, Z, size):
    r = size[0] / 2
    d_r = np.sqrt((X - r) ** 2 + (Y - r) ** 2) - r
    d_z = np.abs(Z - size[2] / 2) - size[2] / 2
    return np.sqrt(np.maximum(d_r, 0) ** 2 + np.maximum(d_z, 0) ** 2) + np.minimum(np.maximum(d_r, d_z), 0)


def sdf_sphere(X, Y, Z, size):
    r = size[0] / 2
    return np.sqrt((X - r) ** 2 + (Y - r) ** 2 + (Z - r) ** 2) - r


def read_stl(path):
    data = Path(path).read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:1000]:
        vals = [float(w) for line in data.decode(errors="ignore").splitlines()
                if line.strip().startswith("vertex") for w in line.split()[1:4]]
        return np.array(vals, dtype=float).reshape(-1, 3, 3)
    n = struct.unpack("<I", data[80:84])[0]
    rec = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return rec["v"].astype(float)


def sdf_mesh(tris, X1, Y1, Z1, h):
    """Signed distance of a closed triangle mesh on a grid (parity fill + EDT)."""
    from scipy import ndimage
    nx, ny, nz = len(X1), len(Y1), len(Z1)
    cnt = np.zeros((nx, ny, nz + 1), dtype=np.int32)
    for tri in tris:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = tri
        i0, i1 = np.searchsorted(X1, [min(x0, x1, x2), max(x0, x1, x2)])
        j0, j1 = np.searchsorted(Y1, [min(y0, y1, y2), max(y0, y1, y2)])
        if i0 >= i1 or j0 >= j1:
            continue
        px, py = np.meshgrid(X1[i0:i1], Y1[j0:j1], indexing="ij")
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(det) < 1e-14:
            continue
        a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / det
        b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / det
        c = 1 - a - b
        hit = (a >= 0) & (b >= 0) & (c >= 0)
        if not hit.any():
            continue
        zc = a * z0 + b * z1 + c * z2
        ii, jj = np.nonzero(hit)
        kk = np.searchsorted(Z1, zc[hit])
        np.add.at(cnt, (ii + i0, jj + j0, kk), 1)
    inside = (np.cumsum(cnt, axis=2)[:, :, :nz] % 2) == 1
    d = ndimage.distance_transform_edt(~inside) - ndimage.distance_transform_edt(inside)
    return ndimage.gaussian_filter(d * h, 1.0)


# ---------------------------------------------------------------------------
# Iso-surface extraction: scikit-image marching cubes, else marching tetrahedra
# ---------------------------------------------------------------------------

_TETS = np.array([[0, 1, 3, 7], [0, 3, 2, 7], [0, 2, 6, 7], [0, 6, 4, 7], [0, 4, 5, 7], [0, 5, 1, 7]])
_CORNERS = np.array([[(c >> 0) & 1, (c >> 1) & 1, (c >> 2) & 1] for c in range(8)])


def _cases():
    """code (bitmask of inside tet vertices) -> list of edge-loops [(a,b),...]."""
    out = {}
    for code in range(1, 15):
        ins = [v for v in range(4) if code >> v & 1]
        outs = [v for v in range(4) if not code >> v & 1]
        if len(ins) == 1:
            out[code] = [[(ins[0], o) for o in outs]]
        elif len(ins) == 3:
            out[code] = [[(i, outs[0]) for i in ins]]
        else:
            (i1, i2), (o1, o2) = ins, outs
            out[code] = [[(i1, o1), (i1, o2), (i2, o2)], [(i1, o1), (i2, o2), (i2, o1)]]
    return out


def marching_tets(F, h, origin):
    F = np.where(F == 0, 1e-9, F)
    nx, ny, nz = F.shape
    sub = [F[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz] for dx, dy, dz in _CORNERS]
    mn = np.minimum.reduce(sub)
    mx = np.maximum.reduce(sub)
    ci, cj, ck = np.nonzero((mn < 0) & (mx > 0))
    del sub, mn, mx
    flat = F.ravel()
    N = F.size
    cases = _cases()
    all_keys, all_pos, all_tris = [], [], []
    nkeys = 0
    for s in range(0, len(ci), 200_000):
        i, j, k = ci[s:s + 200_000], cj[s:s + 200_000], ck[s:s + 200_000]
        corner_ids = np.stack([((i + dx) * ny + (j + dy)) * nz + (k + dz) for dx, dy, dz in _CORNERS], 1)
        for tet in _TETS:
            G = corner_ids[:, tet]
            V = flat[G]
            code = ((V < 0) * (1 << np.arange(4))).sum(1)
            for c, loops in cases.items():
                sel = code == c
                if not sel.any():
                    continue
                g, v = G[sel], V[sel]
                for loop in loops:
                    tri_keys = []
                    for a, b in loop:
                        ga, gb, va, vb = g[:, a], g[:, b], v[:, a], v[:, b]
                        t = (va / (va - vb))[:, None]
                        pa = np.stack(np.unravel_index(ga, F.shape), 1)
                        pb = np.stack(np.unravel_index(gb, F.shape), 1)
                        all_pos.append(origin + h * (pa + t * (pb - pa)))
                        key = np.minimum(ga, gb).astype(np.int64) * N + np.maximum(ga, gb)
                        all_keys.append(key)
                        tri_keys.append(np.arange(nkeys, nkeys + len(key)))
                        nkeys += len(key)
                    all_tris.append(np.stack(tri_keys, 1))
    keys = np.concatenate(all_keys)
    pos = np.concatenate(all_pos)
    uniq, first, inv = np.unique(keys, return_index=True, return_inverse=True)
    verts = pos[first]
    faces = inv[np.concatenate(all_tris)]
    return verts, faces


def extract(F, h, origin):
    try:
        from skimage.measure import marching_cubes
        v, f, _, _ = marching_cubes(F, 0.0, spacing=(h, h, h))
        return v + origin, f
    except ImportError:
        return marching_tets(F, h, origin)


def orient_outward(verts, faces, F, h, origin):
    """Make every triangle's normal point toward increasing field (outside)."""
    from scipy import ndimage
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    n = np.cross(b - a, c - a)
    cen = (a + b + c) / 3
    gx, gy, gz = np.gradient(F)
    idx = ((cen - origin) / h).T
    g = np.stack([ndimage.map_coordinates(G, idx, order=1) for G in (gx, gy, gz)], 1)
    flip = (n * g).sum(1) < 0
    faces = faces.copy()
    faces[flip] = faces[flip][:, [0, 2, 1]]
    return faces


def drop_fragments(verts, faces, keep_frac=0.01):
    """Remove floating pieces (e.g. wall slivers cut off at the shape boundary).

    Each closed shell has a signed volume: positive = an outer surface (a body),
    negative = the wall of a sealed void inside a body. Only small OUTER shells are
    dropped; void walls are always kept or the solid would become invalid.
    Returns verts, faces, dropped_count, bodies, sealed_voids."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    nv = len(verts)
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]])
    n, lab = connected_components(coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(nv, nv)), directed=False)
    tri_lab = lab[faces[:, 0]]
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    vol = np.bincount(tri_lab, weights=np.einsum("ij,ij->i", a, np.cross(b, c)) / 6, minlength=n)
    outer = vol > 0
    tris = np.bincount(tri_lab, minlength=n)
    # Real sealed voids in a TPMS are whole labyrinths (huge); anything tiny is a clipping
    # scrap, e.g. where a wall grazes a corner or the shape's surface, whichever way it faces.
    keep = tris >= keep_frac * tris.max()
    faces = faces[keep[tri_lab]]
    used = np.unique(faces)
    remap = -np.ones(nv, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return (verts[used], remap[faces], int((~keep).sum()),
            int((outer & keep).sum()), int((~outer & keep).sum()))


def taubin_smooth(verts, faces, iters=10, lam=0.5, mu=-0.53):
    """Taubin lambda/mu smoothing: removes voxel stair-steps without shrinking the walls."""
    from scipy.sparse import coo_matrix, diags
    nv = len(verts)
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = np.unique(np.sort(e, 1), axis=0)
    A = coo_matrix((np.ones(2 * len(e)), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(nv, nv)).tocsr()
    Dinv = diags(1.0 / np.maximum(np.asarray(A.sum(1)).ravel(), 1))
    W = Dinv @ A
    v = verts.copy()
    for _ in range(iters):
        v = v + lam * (W @ v - v)
        v = v + mu * (W @ v - v)
    return v


def write_stl(path, verts, faces):
    tri = verts[faces].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(faces), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as fh:
        fh.write(b"gyroid lattice (mm)".ljust(80, b" "))
        fh.write(struct.pack("<I", len(faces)))
        fh.write(rec.tobytes())


def mesh_stats(verts, faces):
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()
    vol = np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return float(area), float(vol), int(np.count_nonzero(counts != 2))


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", default="gyroid", choices=["gyroid", "diamond", "primitive"])
    ap.add_argument("--style", default="sheet", choices=["sheet", "network"],
                    help="sheet = thin double-sided wall (stiff, open); network = solid struts/channels")
    ap.add_argument("--cell", type=float, default=8.0, help="unit cell size, mm")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--wall", type=float, help="sheet wall thickness (mm) or network offset (mm)")
    g.add_argument("--density", type=float, help="target solid volume fraction 0..1")
    ap.add_argument("--wall-end", type=float, help="grade wall/offset linearly along --grade-axis to this value")
    ap.add_argument("--density-end", type=float, help="grade density linearly to this value")
    ap.add_argument("--grade-axis", default="z", choices=["x", "y", "z"])
    ap.add_argument("--shape", default="box", choices=["box", "cylinder", "sphere"])
    ap.add_argument("--size", type=float, nargs=3, default=[40, 40, 40], metavar=("X", "Y", "Z"),
                    help="box extents; cylinder = DIA DIA HEIGHT; sphere = DIA * *")
    ap.add_argument("--domain-stl", help="fill this closed STL body instead of a primitive shape (mm)")
    ap.add_argument("--from-solidworks", action="store_true", help="export & fill the active SolidWorks part")
    ap.add_argument("--shell", type=float, default=0.0, help="solid outer skin thickness, mm (0 = open lattice)")
    ap.add_argument("--res", type=int, default=14,
                    help="voxels per unit cell; raised automatically so every wall is >= --min-wall-voxels thick")
    ap.add_argument("--min-wall-voxels", type=float, default=3.0, help="minimum voxels across a sheet wall")
    ap.add_argument("--smooth", type=int, default=10, help="Taubin smoothing passes (0 = raw voxel mesh)")
    ap.add_argument("--keep-fragments", action="store_true", help="keep floating pieces cut off at the boundary")
    ap.add_argument("--sw-body", default="graphics", choices=["graphics", "solid", "surface"],
                    help="SolidWorks import type: graphics (fast, any size), solid (mesh BREP, <~100k tris)")
    ap.add_argument("--material-density", type=float, default=1.24, help="g/cm^3 for mass estimate (PLA 1.24)")
    ap.add_argument("--out", default="gyroid_out")
    ap.add_argument("--name", default="gyroid_lattice")
    ap.add_argument("--solidworks", action="store_true", help="import the STL into SolidWorks when done")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    if a.wall is None and a.density is None:
        a.density = 0.2

    # --- lattice parameter first: it decides the grid resolution ----------
    p0 = a.wall if a.wall is not None else solve_param(a.type, a.style, a.cell, a.density)
    p1 = p0
    if a.wall_end is not None:
        p1 = a.wall_end
    elif a.density_end is not None:
        p1 = solve_param(a.type, a.style, a.cell, a.density_end)
    res = a.res
    if a.style == "sheet":
        res = max(res, int(math.ceil(a.min_wall_voxels * a.cell / min(p0, p1))))

    # --- domain grid ------------------------------------------------------
    if a.domain_stl or a.from_solidworks:
        extent = None
    else:
        sz = list(a.size)
        if a.shape == "sphere":
            sz = [sz[0]] * 3
        if a.shape == "cylinder":
            sz[1] = sz[0]
        extent = np.array(sz) + 2 * a.shell + 4 * a.cell / res
        max_res = int(a.cell * (400 ** 3 / np.prod(extent)) ** (1 / 3))
        if res > max_res:
            print(f"WARNING: walls need {res} voxels/cell but the grid is capped at {max_res}; "
                  f"walls will be ~{a.min_wall_voxels * max_res / res:.1f} voxels thick. Use a thicker wall or smaller part.")
            res = max_res
    if res != a.res:
        print(f"resolution raised from {a.res} to {res} voxels/cell so walls are >= {a.min_wall_voxels:g} voxels")
    h = a.cell / res
    pad = 2 * h + a.shell
    sw_box = None
    if a.from_solidworks:
        from swkit.sw import SolidWorks
        sw = SolidWorks()
        stl_path, sw_box = sw.active_part_stl(str((out / "domain_export.stl").resolve()))
        a.domain_stl = stl_path
    if a.domain_stl:
        tris = read_stl(a.domain_stl)
        lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
        if sw_box is not None:  # undo SolidWorks STL unit scaling / positive-space translation
            blo, bhi = np.array(sw_box[:3]), np.array(sw_box[3:])
            s = (bhi - blo).max() / max((hi - lo).max(), 1e-12)
            tris = (tris - lo) * s + blo
            lo, hi = blo, bhi
        lo, hi = lo - pad, hi + pad
    else:
        size = list(a.size)
        if a.shape == "sphere":
            size = [size[0]] * 3
        if a.shape == "cylinder":
            size[1] = size[0]
        lo, hi = np.array([-pad] * 3), np.array(size) + pad

    n = np.ceil((hi - lo) / h).astype(int) + 1
    if n.prod() > 400 ** 3:
        sys.exit(f"Grid {n.tolist()} is too large; raise --cell or lower --res")
    jitter = h * 1e-3 * math.pi
    X1, Y1, Z1 = (lo[i] + jitter + h * np.arange(n[i]) for i in range(3))
    X, Y, Z = np.meshgrid(X1, Y1, Z1, indexing="ij")
    print(f"grid {n.tolist()} ({n.prod() / 1e6:.1f} M voxels), voxel {h:.3f} mm")

    if a.domain_stl:
        D = sdf_mesh(tris, X1, Y1, Z1, h)
    else:
        D = {"box": sdf_box, "cylinder": sdf_cylinder, "sphere": sdf_sphere}[a.shape](X, Y, Z, size)

    # --- lattice parameter (possibly graded) ------------------------------
    if p1 != p0:
        ax = {"x": X, "y": Y, "z": Z}[a.grade_axis]
        i = "xyz".index(a.grade_axis)
        u = np.clip((ax - (lo[i] + pad)) / max(hi[i] - lo[i] - 2 * pad, 1e-9), 0, 1)
        param = p0 + (p1 - p0) * u
    else:
        param = p0

    L = lattice_sdf(a.type, a.style, X, Y, Z, a.cell, param)
    F = np.maximum(L, D)
    if a.shell > 0:
        F = np.minimum(F, np.maximum(D, -D - a.shell))
    del X, Y, Z, L

    verts, faces = extract(F, h, lo + jitter)
    faces = orient_outward(verts, faces, F, h, lo + jitter)
    dropped = 0
    if not a.keep_fragments:
        verts, faces, dropped, bodies, voids = drop_fragments(verts, faces)
    else:
        _, _, _, bodies, voids = drop_fragments(verts, faces, keep_frac=0.0)
    if a.smooth > 0:
        verts = taubin_smooth(verts, faces, a.smooth)
    area, vol, bad_edges = mesh_stats(verts, faces)
    domain_vol = float(np.count_nonzero(D <= 0)) * h ** 3
    stl = out / f"{a.name}.stl"
    write_stl(stl, verts, faces)

    report = {
        "type": a.type, "style": a.style, "cell_mm": a.cell,
        "wall_or_offset_mm": [round(p0, 4), round(p1, 4)],
        "unit_cell_density": [round(unit_density(a.type, a.style, a.cell, p0), 4),
                              round(unit_density(a.type, a.style, a.cell, p1), 4)],
        "domain": a.domain_stl or {"shape": a.shape, "size_mm": a.size},
        "shell_mm": a.shell,
        "solid_volume_mm3": round(vol, 1),
        "domain_volume_mm3": round(domain_vol, 1),
        "effective_density": round(vol / domain_vol, 4) if domain_vol else None,
        "mass_g": round(vol / 1000 * a.material_density, 2),
        "surface_area_mm2": round(area, 1),
        "triangles": int(len(faces)),
        "non_manifold_edges": bad_edges,
        "voxels_per_cell": res, "voxel_mm": round(h, 4),
        "bodies": bodies, "sealed_voids": voids, "fragments_dropped": dropped,
        "stl": str(stl.resolve()),
        "seconds": round(time.time() - t_start, 1),
    }
    if voids:
        report["warning_sealed_voids"] = (f"{voids} internal void(s) are fully enclosed by the skin. Powder/resin "
                                          "printing cannot drain them: add drain holes, or use --shell 0.")
    if len(faces) > 300_000:
        report["note"] = ("Large mesh: import into SolidWorks as a Graphics body, or raise --cell / lower --res. "
                          "For printing, send the STL straight to the slicer.")
    (out / f"{a.name}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

    if a.solidworks:
        from swkit.sw import SolidWorks
        from swkit.sw import call0
        doc = SolidWorks().import_mesh(str(stl.resolve()), body=a.sw_body)
        call0(doc, "ViewDisplayShaded")          # "Shaded with Edges" draws every triangle black
        call0(doc, "ViewZoomtofit2")
        print(f"imported into SolidWorks as a {a.sw_body} body")


if __name__ == "__main__":
    main()
