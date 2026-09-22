"""Crawl de 3 niveles: entidades → proveedores → detalle de inhabilitaciones."""

from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.sync_api import Page

from nuwa_fuentes_gt.browser import (
    click_text,
    goto,
    launch_browser,
    page_html,
    site_is_up,
    wait_for_ficha,
    wait_for_listado,
)
from nuwa_fuentes_gt.config import (
    BATCH_STATE_PATH,
    LIST_URL,
    MAX_ATTEMPTS,
    REQUEST_DELAY_S,
    RETRY_BASE_S,
    RETRY_MAX_S,
    SITE_DOWN_PAUSE_MAX_S,
    SITE_DOWN_PAUSE_S,
    ensure_dirs,
)
from nuwa_fuentes_gt.delta import ControlFile
from nuwa_fuentes_gt.models import (
    RegistroInhabilitacion,
    Sancion,
    infer_tipo_persona,
    registro_id,
)
from nuwa_fuentes_gt.parse import (
    ListRow,
    current_page_number,
    parse_detail,
    parse_list_rows,
    parse_motivo_rows,
    parse_pager_labels,
)
from nuwa_fuentes_gt.resilience import (
    BatchInterrupted,
    SiteUnavailable,
    TransientNetworkError,
    polite_sleep,
    retry_call,
    wait_until_available,
)
from nuwa_fuentes_gt.store import registro_is_complete, save_registro


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BatchState:
    start_url: str
    phase: str = "start"  # start | entities | providers | done
    entity_page: int = 1
    provider_page: int = 1
    current_entity_key: Optional[str] = None
    current_entity_label: Optional[str] = None
    current_entity_url: Optional[str] = None
    processed_entity_keys: list[str] = field(default_factory=list)
    processed_registro_ids: list[str] = field(default_factory=list)
    pending_urls: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    interrupted: bool = False
    done: bool = False
    last_checkpoint_at: Optional[str] = None
    saved_this_run: int = 0
    skipped_this_run: int = 0
    skip_detail: bool = False
    headed: bool = False

    def save(self, path: Path | None = None) -> None:
        dest = path or BATCH_STATE_PATH
        self.last_checkpoint_at = utc_now()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, dest)

    @classmethod
    def load(cls, path: Path | None = None) -> "BatchState":
        dest = path or BATCH_STATE_PATH
        data = json.loads(dest.read_text(encoding="utf-8"))
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def _install_signal_handlers(save_fn: Callable[[], None]) -> None:
    def _handler(signum: int, _frame: Any) -> None:
        print(f"\n[extract] Señal {signum} — guardando checkpoint…")
        save_fn()
        raise BatchInterrupted("interrupted_by_user")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass


def _entity_key(row: ListRow) -> str:
    if row.nit:
        return f"nit:{row.nit}"
    return f"ent:{row.label.strip().upper()[:120]}"


def records_from_detail(
    *,
    html: str,
    url: str,
    list_url: str,
    entidad_label: str,
    entidad_url: str,
    fallback_nit: str = "",
    fallback_nombre: str = "",
    autoridad: str = "",
    motivo_catalogo: str = "",
) -> list[RegistroInhabilitacion]:
    detail = parse_detail(html, url=url)
    nit = detail.nit or fallback_nit
    nombre = detail.nombre or fallback_nombre
    tipo = infer_tipo_persona(detail.nombre_original or nombre)
    historial = [s.to_dict() for s in detail.sanciones]
    sanciones = list(detail.sanciones)
    if not sanciones:
        sanciones = [
            Sancion(
                motivo="(ficha sin historial de inhabilitaciones)",
                estatus=detail.situacion_actual,
            )
        ]

    out: list[RegistroInhabilitacion] = []
    for s in sanciones:
        rid = registro_id(nit, s.numero_inhabilitacion, s.fecha_inicio, s.motivo)
        out.append(
            RegistroInhabilitacion(
                registro_id=rid,
                id=nit,
                nombre=nombre,
                nit=nit,
                tipo_persona=tipo,
                estado=detail.situacion_actual,
                motivo=s.motivo,
                fecha=s.fecha_inicio,
                fecha_inicio=s.fecha_inicio,
                inicio=s.fecha_inicio,
                duracion=s.duracion,
                numero_inhabilitacion=s.numero_inhabilitacion,
                estatus=s.estatus,
                estatus_sancion=s.estatus,
                nombre_original=detail.nombre_original or nombre,
                autoridad=autoridad or entidad_label,
                motivo_catalogo=motivo_catalogo or s.motivo,
                entidad_compradora=entidad_label,
                entidad_compradora_url=entidad_url,
                situacion_actual=detail.situacion_actual,
                url=url or detail.url,
                url_listado=list_url,
                historial=historial,
            )
        )
    return out


def _goto_resilient(page: Page, url: str, persist: Callable[[], None]) -> None:
    def attempt() -> None:
        goto(page, url, challenge_timeout_ms=180_000)

    try:
        retry_call(
            attempt,
            label=f"goto {url[:80]}",
            max_attempts=MAX_ATTEMPTS,
            base_delay_s=RETRY_BASE_S,
            max_delay_s=RETRY_MAX_S,
        )
        try:
            low = url.lower()
            if "consultadetproveeinhab" in low:
                wait_for_ficha(page)
            elif "consultaproveeinhabtipo.aspx" in low:
                wait_for_listado(page, tipo=True)
            elif "consultaproveeinhab" in low:
                wait_for_listado(page, tipo=False)
        except TransientNetworkError:
            pass
    except TransientNetworkError:
        persist()
        wait_until_available(
            lambda: site_is_up(page, url),
            label="Guatecompras",
            pause_s=SITE_DOWN_PAUSE_S,
            max_pause_s=SITE_DOWN_PAUSE_MAX_S,
            on_pause=lambda delay, exc: (
                persist(),
                print(
                    f"[extract] sitio caído ({type(exc).__name__}) — "
                    f"checkpoint guardado, pausa {delay:.0f}s…"
                ),
            ),
        )
        goto(page, url)


def _click_page(page: Page, label: str) -> bool:
    try:
        click_text(page, label)
        return True
    except TransientNetworkError:
        return False


def _advance_pager(page: Page, current: Optional[int]) -> bool:
    html = page_html(page)
    labels = parse_pager_labels(html)
    target: Optional[str] = None
    if current:
        nxt = str(current + 1)
        if nxt in labels:
            target = nxt
    if target is None:
        for cand in ("Siguiente", "›", "»", "..."):
            if cand in labels:
                target = cand
                break
    if target is None:
        return False
    return _click_page(page, target)


def _collect_rows(page: Page) -> list[ListRow]:
    return parse_list_rows(page_html(page), base_url=page.url)


def run_extract(
    *,
    start_url: str = LIST_URL,
    max_registros: int = 0,
    max_proveedores: int = 0,
    skip_existing: bool = True,
    headed: Optional[bool] = None,
    delay_s: Optional[float] = None,
    reset: bool = False,
    state_path: Optional[Path] = None,
    list_only: bool = False,
) -> BatchState:
    """
    Descarga inhabilitaciones a data/jsons/.

    max_registros / max_proveedores <= 0: sin tope.
    skip_existing: delta — no reescribe JSON ya completo (sí visita fichas nuevas).
    """
    ensure_dirs()
    path = state_path or BATCH_STATE_PATH
    delay = REQUEST_DELAY_S if delay_s is None else delay_s
    unlimited_reg = int(max_registros) <= 0
    unlimited_prov = int(max_proveedores) <= 0
    reg_limit = 10**12 if unlimited_reg else int(max_registros)
    prov_limit = 10**12 if unlimited_prov else int(max_proveedores)

    if reset or not path.exists():
        state = BatchState(start_url=start_url)
    else:
        state = BatchState.load(path)
        if state.start_url != start_url and not state.interrupted:
            state = BatchState(start_url=start_url)
        elif state.done and not state.interrupted:
            print("[extract] corrida anterior completada — nueva pasada (delta)")
            state = BatchState(start_url=start_url)
        else:
            print(
                f"[extract] reanudando phase={state.phase} "
                f"entidad={state.current_entity_label!r} "
                f"guardados={len(state.processed_registro_ids)}"
            )

    state.interrupted = False
    state.done = False
    state.saved_this_run = 0
    state.skipped_this_run = 0
    if list_only:
        state.skip_detail = True
    state.headed = bool(headed if headed is not None else False)
    control = ControlFile.load()
    proveedores_vistos = 0

    def persist() -> None:
        state.save(path)
        control.save()

    _install_signal_handlers(persist)

    if state.headed:
        print(
            "[extract] Ventana de Chrome: si sale Cloudflare, marca "
            "«Verifico que soy un ser humano». El perfil queda en data/chrome_profile."
        )

    with launch_browser(headed=headed) as (_pw, _browser, page):
        def pause_nav(url: str) -> None:
            _goto_resilient(page, url, persist)
            if delay:
                polite_sleep(delay)

        pause_nav(start_url)
        motivos = parse_motivo_rows(page_html(page), base_url=page.url)
        rows = _collect_rows(page)
        providers = [r for r in rows if r.kind == "provider"]
        con_link = [m for m in motivos if m.href]

        if con_link:
            print(f"[extract] {len(con_link)} motivos con listado (de {len(motivos)})")
            _scrape_motivos(
                page,
                motivos=con_link,
                state=state,
                control=control,
                persist=persist,
                pause_nav=pause_nav,
                skip_existing=skip_existing,
                delay=delay,
                reg_limit=reg_limit,
                prov_limit=prov_limit,
            )
        elif providers:
            print(f"[extract] listado de proveedores ({len(providers)} en página 1)")
            _scrape_provider_listing(
                page,
                state=state,
                control=control,
                persist=persist,
                pause_nav=pause_nav,
                entidad_label="",
                entidad_url="",
                list_url=page.url,
                skip_existing=skip_existing,
                delay=delay,
                reg_limit=reg_limit,
                prov_limit=prov_limit,
                proveedores_vistos_start=proveedores_vistos,
            )
        else:
            print("[extract] no se detectó tabla de motivos ni de proveedores")

    state.done = True
    state.phase = "done"
    control.run_completed = True
    control.last_completed_at = utc_now()
    persist()
    print(
        f"[extract] listo — nuevos={state.saved_this_run} "
        f"omitidos={state.skipped_this_run} "
        f"total_local={control.registros_indexados}"
    )
    return state


def _scrape_motivos(
    page: Page,
    *,
    motivos: list,
    state: BatchState,
    control: ControlFile,
    persist: Callable[[], None],
    pause_nav: Callable[[str], None],
    skip_existing: bool,
    delay: float,
    reg_limit: int,
    prov_limit: int,
) -> None:
    state.phase = "entities"
    for motivo in motivos:
        if state.saved_this_run >= reg_limit:
            return
        key = f"mot:{motivo.seccion}|{motivo.motivo}|{motivo.href}"
        if skip_existing and key in state.processed_entity_keys:
            continue
        state.current_entity_key = key
        state.current_entity_label = f"{motivo.seccion} / {motivo.motivo}"
        print(f"[extract] motivo ({motivo.cantidad}) {state.current_entity_label}")
        pause_nav(motivo.href)
        state.current_entity_url = page.url
        state.phase = "providers"
        state.provider_page = 1
        persist()
        _scrape_provider_listing(
            page,
            state=state,
            control=control,
            persist=persist,
            pause_nav=pause_nav,
            entidad_label=motivo.seccion,
            entidad_url=motivo.href,
            list_url=page.url,
            skip_existing=skip_existing,
            delay=delay,
            reg_limit=reg_limit,
            prov_limit=prov_limit,
            proveedores_vistos_start=0,
            autoridad=motivo.seccion,
            motivo_catalogo=motivo.motivo,
        )
        state.processed_entity_keys.append(key)
        control.mark_entidad(key)
        state.phase = "entities"
        persist()
        pause_nav(state.start_url)


def _restore_entity_page(page: Page, target: int, *, delay: float) -> None:
    if target <= 1:
        return
    seen = 0
    while seen < 40:
        current = current_page_number(page_html(page)) or 1
        if current >= target:
            return
        if not _advance_pager(page, current):
            return
        seen += 1
        if delay:
            polite_sleep(delay)


def _scrape_provider_listing(
    page: Page,
    *,
    state: BatchState,
    control: ControlFile,
    persist: Callable[[], None],
    pause_nav: Callable[[str], None],
    entidad_label: str,
    entidad_url: str,
    list_url: str,
    skip_existing: bool,
    delay: float,
    reg_limit: int,
    prov_limit: int,
    proveedores_vistos_start: int,
    autoridad: str = "",
    motivo_catalogo: str = "",
) -> int:
    state.phase = "providers"
    proveedores_vistos = proveedores_vistos_start
    more = True
    listing_url = page.url or list_url

    while more:
        html_now = page_html(page)
        rows = [r for r in parse_list_rows(html_now, base_url=page.url) if r.kind == "provider"]
        page_no = current_page_number(html_now) or state.provider_page
        state.provider_page = page_no
        persist()
        det_n = html_now.lower().count("consultadetproveeinhab")
        print(
            f"[extract] proveedores p.{page_no} ({len(rows)}) "
            f"entidad={entidad_label or '-'} title={page.title()!r} "
            f"url={page.url} det={det_n} html_len={len(html_now)}"
        )
        if not rows:
            from pathlib import Path

            from nuwa_fuentes_gt.config import DATA_DIR

            dbg = DATA_DIR / "debug_last_list.html"
            dbg.write_text(html_now, encoding="utf-8")

        for row in rows:
            if state.saved_this_run >= reg_limit or proveedores_vistos >= prov_limit:
                return proveedores_vistos
            if state.skip_detail:
                _persist_detail(
                    "",
                    url=row.href,
                    list_url=listing_url,
                    entidad_label=entidad_label,
                    entidad_url=entidad_url,
                    fallback_nit=row.nit,
                    fallback_nombre=row.nombre,
                    skip_existing=skip_existing,
                    state=state,
                    control=control,
                    autoridad=autoridad,
                    motivo_catalogo=motivo_catalogo,
                )
                proveedores_vistos += 1
                persist()
                continue
            dest = row.href
            if dest.startswith("javascript:"):
                try:
                    click_text(page, row.label)
                    if delay:
                        polite_sleep(delay)
                    dest = page.url
                    html = page_html(page)
                    saved = _persist_detail(
                        html,
                        url=dest,
                        list_url=listing_url,
                        entidad_label=entidad_label,
                        entidad_url=entidad_url,
                        fallback_nit=row.nit,
                        fallback_nombre=row.nombre,
                        skip_existing=skip_existing,
                        state=state,
                        control=control,
                        autoridad=autoridad,
                        motivo_catalogo=motivo_catalogo,
                    )
                    proveedores_vistos += 1
                    persist()
                    pause_nav(listing_url)
                    _restore_provider_page(page, page_no, delay=delay)
                    if not saved and state.saved_this_run >= reg_limit:
                        return proveedores_vistos
                except TransientNetworkError as exc:
                    state.errors.append({"proveedor": row.label, "error": str(exc)[:400], "at": utc_now()})
                    persist()
                    try:
                        pause_nav(listing_url)
                    except TransientNetworkError:
                        pass
                continue

            try:
                pause_nav(dest)
                html = page_html(page)
                _persist_detail(
                    html,
                    url=page.url,
                    list_url=listing_url,
                    entidad_label=entidad_label,
                    entidad_url=entidad_url,
                    fallback_nit=row.nit,
                    fallback_nombre=row.nombre,
                    skip_existing=skip_existing,
                    state=state,
                    control=control,
                    autoridad=autoridad,
                    motivo_catalogo=motivo_catalogo,
                )
                proveedores_vistos += 1
                persist()
            except TransientNetworkError as exc:
                state.errors.append({"proveedor": row.label, "error": str(exc)[:400], "at": utc_now()})
                persist()
            # Volver al listado por URL (más estable que history.back en ASP.NET).
            pause_nav(listing_url)
            _restore_provider_page(page, page_no, delay=delay)

        listing_url = page.url or listing_url
        more = _advance_pager(page, page_no)
        if more:
            listing_url = page.url
            if delay:
                polite_sleep(delay)
    return proveedores_vistos


def _restore_provider_page(page: Page, target: int, *, delay: float) -> None:
    if target <= 1:
        return
    hops = 0
    while hops < 40:
        current = current_page_number(page_html(page)) or 1
        if current >= target:
            return
        if not _advance_pager(page, current):
            return
        hops += 1
        if delay:
            polite_sleep(delay)


def _persist_detail(
    html: str,
    *,
    url: str,
    list_url: str,
    entidad_label: str,
    entidad_url: str,
    fallback_nit: str,
    fallback_nombre: str,
    skip_existing: bool,
    state: BatchState,
    control: ControlFile,
    autoridad: str = "",
    motivo_catalogo: str = "",
) -> int:
    regs = records_from_detail(
        html=html,
        url=url,
        list_url=list_url,
        entidad_label=entidad_label,
        entidad_url=entidad_url,
        fallback_nit=fallback_nit,
        fallback_nombre=fallback_nombre,
        autoridad=autoridad,
        motivo_catalogo=motivo_catalogo,
    )
    saved = 0
    for reg in regs:
        if skip_existing and (registro_is_complete(reg.registro_id) or control.knows(reg.registro_id)):
            state.skipped_this_run += 1
            continue
        save_registro(reg)
        state.processed_registro_ids.append(reg.registro_id)
        control.mark_registro(reg.registro_id)
        state.saved_this_run += 1
        saved += 1
        print(f"  + {reg.registro_id}  {reg.nombre}  {reg.numero_inhabilitacion or reg.motivo[:40]}")
    if not regs or (
        len(regs) == 1 and (regs[0].motivo or "").startswith("(ficha sin")
    ):
        # Fallback: el listado ya trae NIT + nombre + motivo de catálogo.
        if fallback_nit and fallback_nombre:
            fb = RegistroInhabilitacion(
                registro_id=registro_id(fallback_nit, "", "", motivo_catalogo),
                id=fallback_nit,
                nombre=fallback_nombre,
                nit=fallback_nit,
                tipo_persona=infer_tipo_persona(fallback_nombre),
                estado="",
                motivo=motivo_catalogo or "Inhabilitación Guatecompras",
                fecha="",
                autoridad=autoridad,
                motivo_catalogo=motivo_catalogo,
                entidad_compradora=entidad_label,
                entidad_compradora_url=entidad_url,
                url=url,
                url_listado=list_url,
            )
            if skip_existing and registro_is_complete(fb.registro_id):
                state.skipped_this_run += 1
                return saved
            save_registro(fb)
            state.processed_registro_ids.append(fb.registro_id)
            control.mark_registro(fb.registro_id)
            state.saved_this_run += 1
            saved += 1
            print(f"  + {fb.registro_id}  {fb.nombre}  (desde listado; ficha con captcha)")
            if not state.headed:
                state.skip_detail = True
            return saved
        print(f"  ! sin registros parseables: {url}")
    return saved


def probe(start_url: str = LIST_URL, *, headed: Optional[bool] = None) -> dict[str, Any]:
    """Abre la URL inicial y reporta qué tablas/enlaces ve (sin guardar)."""
    use_headed = True if headed is None else headed
    print(
        "[probe] Abriendo tu Chrome. Si sale el recuadro de Cloudflare, "
        "márcalo («Verifico que soy un ser humano») y espera. "
        "El perfil se guarda en data/chrome_profile para no pedirlo cada vez."
    )
    with launch_browser(headed=use_headed) as (_pw, _browser, page):
        goto(page, start_url, challenge_timeout_ms=180_000)
        html = page_html(page)
        rows = parse_list_rows(html, base_url=page.url)
        motivos = parse_motivo_rows(html, base_url=page.url)
        return {
            "url": page.url,
            "title": page.title(),
            "page": current_page_number(html),
            "pager": parse_pager_labels(html)[:20],
            "motivos": [asdict(m) for m in motivos],
            "rows": [asdict(r) for r in rows[:30]],
            "counts": {
                "motivos": len(motivos),
                "motivos_con_link": sum(1 for m in motivos if m.href),
                "provider": sum(1 for r in rows if r.kind == "provider"),
                "entity": sum(1 for r in rows if r.kind == "entity"),
                "unknown": sum(1 for r in rows if r.kind == "unknown"),
            },
        }
