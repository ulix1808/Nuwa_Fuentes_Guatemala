#!/usr/bin/env python3
"""Regenera CSV/JSON de ingestión Nuwa a partir de data/jsons/ (sin tocar el portal)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nuwa_fuentes_gt.export import export_all


def main() -> int:
    print(json.dumps(export_all(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
