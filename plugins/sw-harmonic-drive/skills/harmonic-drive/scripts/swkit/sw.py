"""Thin SolidWorks COM driver (Windows + pywin32).

Only uses long-stable API calls (NewDocument, SketchManager.Create*,
FeatureExtrusion3, AddComponent5, MathUtility). Geometry comes in as
swkit.geometry.Profile objects in millimetres; SolidWorks wants metres.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

MM = 0.001

try:
    import pythoncom
    import win32com.client
    from win32com.client import VARIANT
except ImportError:  # pragma: no cover - non-Windows / no pywin32
    win32com = None


def _arr(vals):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in vals])


def _nothing():
    return VARIANT(pythoncom.VT_DISPATCH, None)


def connect():
    """Attach to a running SolidWorks (or start one), always late-bound so
    behaviour does not change when a gen_py type-library cache exists."""
    from win32com.client import dynamic
    try:
        import pywintypes
        clsid = pywintypes.IID("SldWorks.Application")  # IID() resolves ProgIDs
        obj = pythoncom.GetActiveObject(clsid)
        return dynamic.Dispatch(obj.QueryInterface(pythoncom.IID_IDispatch))
    except pythoncom.com_error:
        pass
    try:
        return dynamic.Dispatch("SldWorks.Application")
    except Exception as e:
        raise SolidWorksError(f"Could not start SolidWorks over COM: {e}") from e


def flag_methods(obj, *names):
    """Tell late-bound pywin32 these members are methods, not properties."""
    if hasattr(obj, "_FlagAsMethod"):
        for n in names:
            try:
                obj._FlagAsMethod(n)
            except Exception:       # not a member of this interface
                pass


def call0(obj, name):
    """Call a zero-argument COM method. pywin32 late binding often exposes these
    as properties (already evaluated), so only call when we got a bound method."""
    v = getattr(obj, name)
    if callable(v) and not hasattr(v, "_oleobj_"):
        return v()
    return v


# swUserPreferenceStringValue_e
_TEMPLATE_PART, _TEMPLATE_ASM = 8, 9
# swEndConditions_e / swStartConditions_e
_BLIND, _START_SKETCH_PLANE, _START_OFFSET = 0, 0, 3


class SolidWorksError(RuntimeError):
    pass


class SolidWorks:
    def __init__(self, visible: bool = True):
        if win32com is None:
            raise SolidWorksError("pywin32 is not installed: run  python -m pip install pywin32")
        self.app = connect()
        self.app.Visible = visible
        flag_methods(self.app, "OpenDoc6", "ActivateDoc3", "LoadFile4", "GetImportFileData", "NewDocument",
                               "GetOpenDocumentByName", "GetUserPreferenceStringValue", "CloseDoc")
        self.math = call0(self.app, "GetMathUtility")
        # late binding mistakes these for properties; force method calls
        flag_methods(self.math, "CreatePoint", "CreateVector", "CreateTransformRotateAxis", "CreateTransform")

    def _template(self, idx: int) -> str:
        t = self.app.GetUserPreferenceStringValue(idx)
        if not t or not os.path.exists(t):
            raise SolidWorksError("No default part/assembly template. Set one in Tools > Options > "
                                  "System Options > Default Templates.")
        return t

    def new_part(self, name: str) -> "Part":
        doc = self.app.NewDocument(self._template(_TEMPLATE_PART), 0, 0, 0)
        if doc is None:
            raise SolidWorksError("NewDocument(part) failed")
        return Part(self, doc, name)

    def new_assembly(self) -> "Assembly":
        doc = self.app.NewDocument(self._template(_TEMPLATE_ASM), 0, 0, 0)
        if doc is None:
            raise SolidWorksError("NewDocument(assembly) failed")
        return Assembly(self, doc)

    def rotz_transform(self, angle: float, x_mm=0.0, y_mm=0.0, z_mm=0.0):
        """Rotation about world Z then translation. Rotation block comes from
        SolidWorks itself so we never depend on its matrix layout convention."""
        origin = self.math.CreatePoint(_arr([0, 0, 0]))
        axis = self.math.CreateVector(_arr([0, 0, 1]))
        r = self.math.CreateTransformRotateAxis(origin, axis, float(angle))
        data = list(r.ArrayData)
        data[9], data[10], data[11] = x_mm * MM, y_mm * MM, z_mm * MM
        return self.math.CreateTransform(_arr(data))

    def import_mesh(self, path: str, body: str | None = None, units_mm: bool = True):
        """Open an STL as a new part.

        body: "graphics" | "surface" | "solid" sets Tools > Options > Import > STL/OBJ/OFF/PLY
        "Import as" for this import only (None keeps the user's setting). units_mm reads
        the file in millimetres. Both preferences are restored afterwards."""
        # swUserPreferenceIntegerValue_e / swImportStlVrmlModelType_e / swLengthUnit_e (swconst.tlb, SW 2025)
        PREF_MODEL_TYPE, PREF_UNITS = 208, 210
        types = {"graphics": 0, "surface": 1, "solid": 2}
        flag_methods(self.app, "GetUserPreferenceIntegerValue", "SetUserPreferenceIntegerValue")
        saved = {}
        wanted = {}
        if body is not None:
            wanted[PREF_MODEL_TYPE] = types[body]
        if units_mm:
            wanted[PREF_UNITS] = 0                       # swMM
        for pref, val in wanted.items():
            saved[pref] = self.app.GetUserPreferenceIntegerValue(pref)
            self.app.SetUserPreferenceIntegerValue(pref, val)
        try:
            errs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            data = None
            try:
                data = self.app.GetImportFileData(str(path))
            except Exception:
                pass
            doc = self.app.LoadFile4(str(path), "r", data if data is not None else _nothing(), errs)
        finally:
            for pref, val in saved.items():
                self.app.SetUserPreferenceIntegerValue(pref, val)
        if doc is None:
            raise SolidWorksError(f"LoadFile4 failed for {path} (error {errs.value}); open it via File > Open instead")
        return doc

    def active_part_stl(self, path: str):
        """Export the active part to STL and return (stl_path, part_box_mm)."""
        doc = self.app.ActiveDoc
        if doc is None or call0(doc, "GetType") != 1:
            raise SolidWorksError("Open (and activate) the part you want to fill first")
        box = [v / MM for v in doc.GetPartBox(True)]
        doc.SaveAs3(str(path), 0, 1)
        if not os.path.exists(path):
            raise SolidWorksError("STL export failed")
        return path, box


class Part:
    def __init__(self, sw: SolidWorks, doc, name: str):
        self.sw, self.doc, self.name = sw, doc, name
        self.sm = doc.SketchManager
        self.fm = doc.FeatureManager

    def _front_plane(self):
        f = call0(self.doc, "FirstFeature")
        while f is not None:
            if call0(f, "GetTypeName2") == "RefPlane":
                return f  # first reference plane is Front (XY) in every language
            f = call0(f, "GetNextFeature")
        raise SolidWorksError("No reference plane found")

    def sketch(self, profile):
        self.doc.ClearSelection2(True)
        self._front_plane().Select2(False, 0)
        self.sm.InsertSketch(True)
        self.sm.AddToDB = True
        self.sm.DisplayWhenAdded = False
        try:
            for it in profile.items:
                self._draw(it)
        finally:
            self.sm.DisplayWhenAdded = True
            self.sm.AddToDB = False
        self.sm.InsertSketch(True)
        sk = self.doc.FeatureByPositionReverse(0)
        return sk

    def _draw(self, it):
        k = it["kind"]
        if k == "line":
            (x1, y1), (x2, y2) = it["p1"], it["p2"]
            seg = self.sm.CreateLine(x1 * MM, y1 * MM, 0, x2 * MM, y2 * MM, 0)
        elif k == "arc":
            (cx, cy), (x1, y1), (x2, y2) = it["c"], it["p1"], it["p2"]
            seg = self.sm.CreateArc(cx * MM, cy * MM, 0, x1 * MM, y1 * MM, 0, x2 * MM, y2 * MM, 0,
                                    1 if it["ccw"] else -1)
        elif k == "circle":
            (cx, cy), r = it["c"], it["r"]
            seg = self.sm.CreateCircleByRadius(cx * MM, cy * MM, 0, r * MM)
        elif k == "spline":
            flat = []
            for x, y in it["pts"]:
                flat += [x * MM, y * MM, 0.0]
            try:
                seg = self.sm.CreateSpline2(_arr(flat), False)
            except Exception:
                seg = self.sm.CreateSpline(_arr(flat))
        elif k == "ellipse":
            (cx, cy), a, b, th = it["c"], it["a"], it["b"], it["angle"]
            seg = self.sm.CreateEllipse(cx * MM, cy * MM, 0,
                                        (cx + a * math.cos(th)) * MM, (cy + a * math.sin(th)) * MM, 0,
                                        (cx - b * math.sin(th)) * MM, (cy + b * math.cos(th)) * MM, 0)
        else:
            raise SolidWorksError(f"unknown primitive {k}")
        if seg is None:
            raise SolidWorksError(f"SolidWorks rejected a {k} in {self.name}")

    def extrude(self, profile, depth_mm: float, z0_mm: float = 0.0):
        """Sketch `profile` on Front plane and extrude +Z from z0 by depth (merged)."""
        sk = self.sketch(profile)
        self.doc.ClearSelection2(True)
        sk.Select2(False, 0)
        t0 = _START_OFFSET if abs(z0_mm) > 1e-9 else _START_SKETCH_PLANE
        args = (True, False, False, _BLIND, 0, depth_mm * MM, 0, False, False, False, False, 0, 0,
                False, False, False, False, True, True, True, t0, z0_mm * MM, False)
        feat = None
        for fn in ("FeatureExtrusion3", "FeatureExtrusion2"):
            try:
                feat = getattr(self.fm, fn)(*args)
                break
            except AttributeError:
                continue
        if feat is None:
            raise SolidWorksError(f"Extrusion failed in {self.name}: check the profile is closed "
                                  "and non-self-intersecting (see the SVG preview)")
        return feat

    def save(self, folder) -> str:
        path = str(Path(folder).resolve() / f"{self.name}.SLDPRT")
        self.doc.ForceRebuild3(False)
        self.doc.ShowNamedView2("*Isometric", 7)
        call0(self.doc, "ViewZoomtofit2")
        self.doc.SaveAs3(path, 0, 1)
        if not os.path.exists(path):
            raise SolidWorksError(f"Could not save {path}")
        return path


class Assembly:
    def __init__(self, sw: SolidWorks, doc):
        self.sw, self.doc = sw, doc

    def add(self, part_path: str, x=0.0, y=0.0, z=0.0, rotz=0.0):
        comp = self.doc.AddComponent5(part_path, 0, "", False, "", x * MM, y * MM, z * MM)
        if comp is None:
            raise SolidWorksError(f"AddComponent5 failed for {part_path}")
        # AddComponent5 places by bounding-box centre; always re-place by part origin
        comp.Transform2 = self.sw.rotz_transform(rotz, x, y, z)
        return comp

    def save(self, path) -> str:
        path = str(Path(path).resolve())
        call0(self.doc, "EditRebuild3")
        self.doc.ShowNamedView2("*Isometric", 7)
        call0(self.doc, "ViewZoomtofit2")
        self.doc.SaveAs3(path, 0, 1)
        return path


def build(parts: dict, out_dir, assembly: list | None = None, asm_name: str = "assembly"):
    """parts: {name: [(profile, depth_mm, z0_mm), ...]}
    assembly: [(part_name, x, y, z, rotz), ...] placed with world-Z rotations."""
    sw = SolidWorks()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, ops in parts.items():
        p = sw.new_part(name)
        for prof, depth, z0 in ops:
            p.extrude(prof, depth, z0)
        paths[name] = p.save(out_dir)
        print(f"  built {paths[name]}")
    if assembly:
        asm = sw.new_assembly()
        for name, x, y, z, rz in assembly:
            asm.add(paths[name], x, y, z, rz)
        ap = asm.save(out_dir / f"{asm_name}.SLDASM")
        print(f"  built {ap}")
    return paths
