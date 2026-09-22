#!/usr/bin/env python3
"""Estado del corpus local y del archivo de control (deltas)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nuwa_fuentes_gt.config import BATCH_STATE_PATH, CONTROL_PATH, JSONS_DIR
from nuwa_fuentes_gt.delta import ControlFile
from nuwa_fuentes_gt.store import iter_registros


def main() -> int:
    control = ControlFile.load()
    regs = iter_registros()
    nits = {r.nit for r in regs if r.nit}
    vigentes = sum(1 for r in regs if "vigente" in (r.estatus_sancion or "").lower())
    batch = None
    if BATCH_STATE_PATH.exists():
        batch = json.loads(BATCH_STATE_PATH.read_text(encoding="utf-8"))
    out = {
        "control_path": str(CONTROL_PATH),
        "jsons_dir": str(JSONS_DIR),
        "control": control.to_public_dict(),
        "disk": {
            "json_files": len(regs),
            "nits": len(nits),
            "sanciones_vigentes": vigentes,
        },
        "batch_state": None
        if batch is None
        else {
            "phase": batch.get("phase"),
            "done": batch.get("done"),
            "interrupted": batch.get("interrupted"),
            "entity_page": batch.get("entity_page"),
            "provider_page": batch.get("provider_page"),
            "current_entity": batch.get("current_entity_label"),
            "saved_this_run": batch.get("saved_this_run"),
            "last_checkpoint_at": batch.get("last_checkpoint_at"),
            "errors": len(batch.get("errors") or []),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
