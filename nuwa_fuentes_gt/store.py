from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from nuwa_fuentes_gt.config import JSONS_DIR, ensure_dirs
from nuwa_fuentes_gt.models import RegistroInhabilitacion, from_dict, safe_filename


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def json_path(registro: str) -> Path:
    return JSONS_DIR / f"{safe_filename(registro)}.json"


def registro_is_complete(registro: str) -> bool:
    path = json_path(registro)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        motivo = str(data.get("motivo") or "")
        if motivo.startswith("(ficha sin"):
            return False
        return bool(data.get("registro_id") == registro and data.get("id") and data.get("nombre"))
    except (json.JSONDecodeError, OSError):
        return False


def load_registro(registro: str) -> Optional[RegistroInhabilitacion]:
    path = json_path(registro)
    if not path.is_file():
        return None
    try:
        return from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def save_registro(reg: RegistroInhabilitacion) -> Path:
    ensure_dirs()
    path = json_path(reg.registro_id)
    _atomic_write_text(path, json.dumps(reg.to_dict(), ensure_ascii=False, indent=2))
    return path


def iter_registros() -> list[RegistroInhabilitacion]:
    ensure_dirs()
    out: list[RegistroInhabilitacion] = []
    for path in sorted(JSONS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("registro_id"):
            try:
                out.append(from_dict(data))
            except TypeError:
                continue
    return out


def indexed_ids() -> set[str]:
    ids: set[str] = set()
    for path in JSONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rid = data.get("registro_id")
        if rid:
            ids.add(str(rid))
    return ids


def write_json(path: Path, payload: Any) -> None:
    ensure_dirs()
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
