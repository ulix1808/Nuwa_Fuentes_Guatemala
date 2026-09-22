"""Control de deltas: watermark + IDs ya indexados para no recargar toda la fuente."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nuwa_fuentes_gt.config import CONTROL_PATH, ensure_dirs
from nuwa_fuentes_gt.store import indexed_ids


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ControlFile:
    """
    Archivo de control para corridas incrementales.

    last_sync_at: última corrida que terminó (o se interrumpió).
    registro_ids: llaves ya en data/jsons/ (se rehidratan al cargar).
    entidades_completadas: entidades compradoras ya recorridas en una corrida full.
    """

    pais: str = "Guatemala"
    pais_codigo: str = "GT"
    fuente_id: str = "guatecompras_inhabilitaciones"
    last_sync_at: Optional[str] = None
    last_completed_at: Optional[str] = None
    registros_indexados: int = 0
    proveedores_indexados: int = 0
    registro_ids: list[str] = field(default_factory=list)
    entidades_completadas: list[str] = field(default_factory=list)
    last_entidad: Optional[str] = None
    last_list_url: Optional[str] = None
    run_completed: bool = False

    def save(self, path: Path | None = None) -> None:
        ensure_dirs()
        dest = path or CONTROL_PATH
        self.last_sync_at = utc_now()
        self.registro_ids = sorted(set(self.registro_ids) | indexed_ids())
        self.registros_indexados = len(self.registro_ids)
        nits = {rid.split("-")[3] for rid in self.registro_ids if rid.startswith("gt-gc-inh-")}
        self.proveedores_indexados = len(nits)
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, dest)

    @classmethod
    def load(cls, path: Path | None = None) -> "ControlFile":
        dest = path or CONTROL_PATH
        if not dest.exists():
            ctrl = cls()
            ctrl.registro_ids = sorted(indexed_ids())
            ctrl.registros_indexados = len(ctrl.registro_ids)
            return ctrl
        data = json.loads(dest.read_text(encoding="utf-8"))
        known = set(cls.__dataclass_fields__)
        ctrl = cls(**{k: v for k, v in data.items() if k in known})
        ctrl.registro_ids = sorted(set(ctrl.registro_ids) | indexed_ids())
        ctrl.registros_indexados = len(ctrl.registro_ids)
        return ctrl

    def knows(self, registro_id: str) -> bool:
        return registro_id in set(self.registro_ids)

    def mark_registro(self, registro_id: str) -> None:
        if registro_id not in self.registro_ids:
            self.registro_ids.append(registro_id)

    def mark_entidad(self, key: str) -> None:
        if key not in self.entidades_completadas:
            self.entidades_completadas.append(key)
        self.last_entidad = key

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "pais": self.pais,
            "pais_codigo": self.pais_codigo,
            "fuente_id": self.fuente_id,
            "last_sync_at": self.last_sync_at,
            "last_completed_at": self.last_completed_at,
            "registros_indexados": self.registros_indexados,
            "proveedores_indexados": self.proveedores_indexados,
            "entidades_completadas": len(self.entidades_completadas),
            "run_completed": self.run_completed,
        }
