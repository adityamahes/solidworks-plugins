#!/usr/bin/env python3
"""Download McMaster-Carr CAD files and put them into SolidWorks.

The McMaster MCP (mcmaster_open on a part number) returns a link with text
"Download" pointing at .../mvC/Library/CAD2/.../<part>_<name>.SLDPRT. Pass that
URL here. Only https://www.mcmaster.com URLs are accepted.

  python mcmaster_cad.py fetch  --url "<Download link>" --part 91290A115 --dir cad/mcmaster
  python mcmaster_cad.py fetch  --url "..." --part 91290A115 --dir cad/mcmaster --open
  python mcmaster_cad.py fetch  --url "..." --part 91290A115 --dir cad/mcmaster --insert --at 10 0 5 --count 4
  python mcmaster_cad.py insert --file cad/mcmaster/91290A115.SLDPRT --at 0 0 0
  python mcmaster_cad.py bom    --dir cad/mcmaster          # list what has been fetched

Files are cached: an existing <dir>/<part>.SLDPRT is reused, not downloaded again.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ALLOWED_HOSTS = {"www.mcmaster.com", "mcmaster.com"}
CAD_EXT = {".sldprt", ".sldasm", ".step", ".stp", ".igs", ".iges", ".stl", ".dxf", ".dwg", ".x_t"}
PART_RE = re.compile(r"^[0-9]{4,5}[A-Z][0-9]{1,4}(?:-[A-Z0-9]+)?$")


def check_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        sys.exit(f"Refusing non-McMaster URL: {url}")
    ext = Path(urllib.parse.unquote(u.path)).suffix.lower()
    if ext not in CAD_EXT:
        sys.exit(f"URL does not point at a CAD file ({ext or 'no extension'})")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(urllib.parse.unquote(u.path)), u.query, ""))


def fetch(url: str, part: str, folder: Path) -> Path:
    if not PART_RE.match(part):
        sys.exit(f"'{part}' does not look like a McMaster part number")
    url = check_url(url)
    ext = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).suffix
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{part}{ext.upper() if ext.lower().startswith('.sld') else ext.lower()}"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"cached {dest}")
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "solidworks-claude-plugins/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        data = b""
        if e.code not in (401, 403):
            raise
    if not data or data[:15].lower().startswith((b"<!doctype", b"<html")):
        print("BROWSER_REQUIRED: McMaster only serves CAD to a browser session. Open this URL in the "
              f"browser, then run:  mcmaster_cad.py collect --part {part} --dir {folder}\n{url}")
        sys.exit(3)
    dest.write_bytes(data)
    record(folder, part, dest, url)
    print(f"saved {dest} ({len(data) / 1024:.0f} KB)")
    return dest


def record(folder: Path, part: str, dest: Path, url: str):
    meta_path = folder / "mcmaster_parts.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta[part] = {"file": dest.name, "source": url, "fetched": time.strftime("%Y-%m-%d"),
                  "page": f"https://www.mcmaster.com/{part}/"}
    meta_path.write_text(json.dumps(meta, indent=2))


def collect(part: str, folder: Path, downloads: Path, max_age_min: float) -> Path:
    """Move the newest browser download for `part` from Downloads into the project."""
    cutoff = time.time() - max_age_min * 60
    hits = [p for p in downloads.iterdir()
            if p.is_file() and p.name.upper().startswith(part) and p.suffix.lower() in CAD_EXT
            and p.stat().st_mtime >= cutoff]
    if not hits:
        sys.exit(f"No {part}* CAD file in {downloads} from the last {max_age_min:.0f} min")
    src = max(hits, key=lambda p: p.stat().st_mtime)
    folder.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.upper() if src.suffix.lower().startswith(".sld") else src.suffix.lower()
    dest = folder / f"{part}{ext}"
    dest.write_bytes(src.read_bytes())
    src.unlink()
    record(folder, part, dest, f"browser download: {src.name}")
    print(f"collected {src.name} -> {dest}")
    return dest


def sw_open(path: Path):
    from swkit.sw import SolidWorks
    import pythoncom
    from win32com.client import VARIANT
    sw = SolidWorks()
    kind = {".sldprt": 1, ".sldasm": 2}.get(path.suffix.lower())
    if kind is None:
        return sw.import_mesh(str(path.resolve()))  # STEP/IGES/STL via LoadFile4
    errs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warns = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = sw.app.OpenDoc6(str(path.resolve()), kind, 1, "", errs, warns)  # 1 = silent
    if doc is None:
        sys.exit(f"SolidWorks could not open {path} (error {errs.value})")
    print(f"opened {path.name} in SolidWorks")
    return sw, doc


def sw_insert(path: Path, at, count: int, spacing):
    from swkit.sw import SolidWorks, SolidWorksError, call0
    import pythoncom
    from win32com.client import VARIANT
    sw = SolidWorks()
    asm = sw.app.ActiveDoc
    if asm is None or call0(asm, "GetType") != 2:
        sys.exit("Activate the assembly you want to insert into first")
    errs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warns = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    kind = 2 if path.suffix.lower() == ".sldasm" else 1
    sw.app.OpenDoc6(str(path.resolve()), kind, 1 | 2, "", errs, warns)  # silent + read-only, loads it for AddComponent5
    sw.app.ActivateDoc3(call0(asm, "GetTitle"), False, 0, errs)
    for i in range(count):
        x, y, z = (at[j] + i * spacing[j] for j in range(3))
        comp = asm.AddComponent5(str(path.resolve()), 0, "", False, "", x / 1000, y / 1000, z / 1000)
        if comp is None:
            raise SolidWorksError(f"AddComponent5 failed for {path}")
        print(f"inserted {comp.Name2} at ({x}, {y}, {z}) mm")
    call0(asm, "EditRebuild3")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--url", required=True)
    f.add_argument("--part", required=True)
    f.add_argument("--dir", default="cad/mcmaster")
    f.add_argument("--open", action="store_true", help="open the part in SolidWorks")
    f.add_argument("--insert", action="store_true", help="insert into the active assembly")
    c = sub.add_parser("collect", help="file a browser download from ~/Downloads into the project")
    c.add_argument("--part", required=True)
    c.add_argument("--dir", default="cad/mcmaster")
    c.add_argument("--downloads", default=str(Path.home() / "Downloads"))
    c.add_argument("--max-age", type=float, default=30, help="only files newer than this many minutes")
    c.add_argument("--open", action="store_true")
    c.add_argument("--insert", action="store_true")
    for p in (f, c, sub.add_parser("insert")):
        if p.prog.endswith("insert"):
            p.add_argument("--file", required=True)
        p.add_argument("--at", type=float, nargs=3, default=[0, 0, 0], metavar=("X", "Y", "Z"), help="mm")
        p.add_argument("--count", type=int, default=1)
        p.add_argument("--spacing", type=float, nargs=3, default=[0, 0, 0], metavar=("DX", "DY", "DZ"))
    b = sub.add_parser("bom")
    b.add_argument("--dir", default="cad/mcmaster")
    a = ap.parse_args(argv)

    if a.cmd in ("fetch", "collect"):
        if a.cmd == "fetch":
            path = fetch(a.url, a.part.upper(), Path(a.dir))
        else:
            path = collect(a.part.upper(), Path(a.dir), Path(a.downloads), a.max_age)
        if a.insert:
            sw_insert(path, a.at, a.count, a.spacing)
        elif a.open:
            sw_open(path)
    elif a.cmd == "insert":
        sw_insert(Path(a.file), a.at, a.count, a.spacing)
    else:
        meta_path = Path(a.dir) / "mcmaster_parts.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
