#!/usr/bin/env python3
"""Schwarz Primitive (P) TPMS lattice -> watertight STL -> optional SolidWorks import.

  python primitive.py --shape box --size 40 40 20 --cell 8 --density 0.25 --out out/
  python primitive.py --shape cylinder --size 30 30 50 --cell 6 --wall 0.8 --shell 1.2 --out out/ --solidworks
  python primitive.py --from-solidworks --cell 6 --density 0.2 --shell 1.0 --out out/   # fill the active part

Run with --help for every option (shared TPMS generator in swkit/tpms.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from swkit.tpms import main  # noqa: E402

if __name__ == "__main__":
    main(default_type="primitive")
