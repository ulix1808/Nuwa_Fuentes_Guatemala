#!/usr/bin/env python3
"""Descarga inhabilitaciones de Guatecompras a data/jsons/ (corpus local)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nuwa_fuentes_gt.config import HEADED, LIST_URL, REQUEST_DELAY_S
from nuwa_fuentes_gt.export import export_all
from nuwa_fuentes_gt.resilience import BatchInterrupted, TransientNetworkError
from nuwa_fuentes_gt.scrape import probe, run_extract


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=LIST_URL, help="URL inicial de listado")
    p.add_argument("--max", type=int, default=0, dest="max_registros", help="Tope de registros nuevos (0=sin tope)")
    p.add_argument("--max-proveedores", type=int, default=0, help="Tope de fichas de proveedor (0=sin tope)")
    p.add_argument("--delay", type=float, default=REQUEST_DELAY_S, help="Pausa entre navegaciones (s)")
    p.add_argument("--headed", action="store_true", default=HEADED, help="Browser visible")
    p.add_argument("--reset", action="store_true", help="Ignora batch_state.json (no borra JSON ya guardados)")
    p.add_argument("--refresh", action="store_true", help="Reescribe JSON existentes (sin delta)")
    p.add_argument("--probe", action="store_true", help="Solo inspecciona la primera página")
    p.add_argument("--no-export", action="store_true", help="No regenera CSV/JSON de export al terminar")
    p.add_argument(
        "--list-only",
        action="store_true",
        help="Solo listados (NIT/nombre/motivo). Las fichas piden Turnstile.",
    )
    args = p.parse_args()

    if args.probe:
        try:
            # Probe siempre visible: headless no pasa el «Un momento…» de Cloudflare.
            info = probe(args.url, headed=True)
        except TransientNetworkError as exc:
            print(
                f"[probe] Cloudflare no dejó pasar ({exc}).\n"
                "Vuelve a correr el mismo comando, espera el check en la ventana,\n"
                "o prueba: python scripts/run_extract.py --probe --headed"
            )
            return 2
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    try:
        run_extract(
            start_url=args.url,
            max_registros=args.max_registros,
            max_proveedores=args.max_proveedores,
            skip_existing=not args.refresh,
            headed=args.headed,
            delay_s=args.delay,
            reset=args.reset,
            list_only=args.list_only,
        )
    except BatchInterrupted:
        print("[extract] interrumpido — reanuda con el mismo comando")
        return 2

    if not args.no_export:
        summary = export_all()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
