"""Exporta el corpus local a JSON/CSV listos para ingestión futura en Nuwa."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from nuwa_fuentes_gt.config import EXPORTS_DIR, PAIS, PAIS_CODIGO, ensure_dirs
from nuwa_fuentes_gt.store import iter_registros, save_registro, write_json

CSV_COLUMNS = [
    "pais",
    "pais_codigo",
    "fuente_pais",
    "fuente",
    "fuente_id",
    "nombre",
    "nombre_normalizado",
    "tipo_sociedad",
    "id",
    "NIT",
    "tipo_persona",
    "situacion_actual",
    "estado",
    "motivo",
    "inicio",
    "fecha",
    "fecha_inicio",
    "duracion",
    "numero_inhabilitacion",
    "estatus",
    "estatus_sancion",
    "autoridad",
    "motivo_catalogo",
    "entidad_compradora",
    "url",
    "jurisdiccion",
    "tipo_fuente",
    "registro_id",
]


def export_all(*, exports_dir: Path | None = None) -> dict[str, Any]:
    ensure_dirs()
    dest = exports_dir or EXPORTS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    regs = iter_registros()
    for reg in regs:
        save_registro(reg)
    chunks = [r.to_nuwa_chunk() for r in regs]
    full = [r.to_dict() for r in regs]

    write_json(dest / "nuwa_chunks.json", chunks)
    jsonl_path = dest / "nuwa_chunks.jsonl"
    jsonl_path.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks),
        encoding="utf-8",
    )
    write_json(dest / "registros.json", full)

    csv_path = dest / "nuwa_chunks.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for chunk, reg in zip(chunks, regs):
            row = {k: chunk.get(k, "") for k in CSV_COLUMNS}
            row["registro_id"] = reg.registro_id
            writer.writerow(row)

    summary = {
        "pais": PAIS,
        "pais_codigo": PAIS_CODIGO,
        "registros": len(regs),
        "archivos": {
            "json": str(dest / "nuwa_chunks.json"),
            "jsonl": str(jsonl_path),
            "csv": str(csv_path),
            "full": str(dest / "registros.json"),
        },
    }
    write_json(dest / "export_manifest.json", summary)
    return summary
