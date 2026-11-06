"""Copy shared/swkit into every plugin skill's scripts/ folder.

Plugins are installed (copied) individually, so each one has to carry its own
copy of the shared toolkit. Edit shared/swkit, then run:  python tools/sync_shared.py
"""
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "shared" / "swkit"
for scripts in sorted(root.glob("plugins/*/skills/*/scripts")):
    dst = scripts / "swkit"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    for stale in dst.glob("*.py"):
        if not (src / stale.name).exists():
            stale.unlink()
    print("synced", dst.relative_to(root))
