"""Parsers HTML de listados y detalle de Guatecompras (independientes del browser)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from nuwa_fuentes_gt.models import (
    Sancion,
    clean_spaces,
    infer_tipo_persona,
    nit_digits,
    nombre_buscable,
)

NIT_NAME_RE = re.compile(
    r"^\(?\s*(?P<nit>[\d\-]+)\s*\)?\s*[-–—:]\s*(?P<nombre>.+)$",
    re.IGNORECASE,
)
NIT_ONLY_RE = re.compile(r"^\(?\s*(\d{6,12})\s*\)?$")
PAGER_RE = re.compile(r"^\d+$")


SKIP_LABELS = {
    "inicio",
    "menú",
    "menu",
    "siguiente",
    "anterior",
    "[--no especificado--]",
    "[-no especificado-]",
    "términos y referencias",
    "terminos y referencias",
    "tips para webmasters",
}

SECCION_MARKERS = (
    "ENTIDADES COMPRADORAS",
    "INSTITUTO GUATEMALTECO",
    "INSTITUTO NACIONAL",
    "REGISTRO GENERAL",
    "SUPERINTENDENCIA",
    "TRIBUNAL SUPREMO",
)


@dataclass
class ListRow:
    label: str
    href: str
    nit: str = ""
    nombre: str = ""
    extra: str = ""
    kind: str = "unknown"  # provider | motivo | entity | unknown


@dataclass
class MotivoRow:
    seccion: str
    motivo: str
    explicacion: str
    cantidad: int
    href: str


@dataclass
class ProviderDetail:
    nit: str
    nombre: str
    nombre_original: str
    situacion_actual: str
    sanciones: list[Sancion]
    url: str = ""


def parse_nit_nombre(text: str) -> tuple[str, str]:
    raw = clean_spaces(text)
    m = NIT_NAME_RE.match(raw)
    if m:
        return nit_digits(m.group("nit")), clean_spaces(m.group("nombre"))
    m2 = NIT_ONLY_RE.match(raw)
    if m2:
        return nit_digits(m2.group(1)), ""
    return "", raw


def _abs(href: str, base_url: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith("javascript:"):
        return href
    return urljoin(base_url, href)


def _is_provider_href(href: str) -> bool:
    h = (href or "").lower()
    return "consultadetproveeinhab" in h


def _is_motivo_href(href: str) -> bool:
    h = (href or "").lower()
    return "consultaproveeinhabtipo.aspx" in h


def classify_row(label: str, href: str) -> str:
    lab = clean_spaces(label)
    if lab.lower() in SKIP_LABELS or PAGER_RE.match(lab):
        return "unknown"
    if _is_provider_href(href) and NIT_NAME_RE.match(lab):
        return "provider"
    nit, _ = parse_nit_nombre(lab)
    if nit and (_is_provider_href(href) or NIT_NAME_RE.match(lab)):
        return "provider"
    if _is_motivo_href(href):
        return "motivo"
    return "unknown"


def extract_tables(html: str) -> list[Tag]:
    soup = BeautifulSoup(html, "lxml")
    return list(soup.find_all("table"))


def parse_list_rows(html: str, *, base_url: str) -> list[ListRow]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[ListRow] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href_raw = a.get("href") or ""
        label = clean_spaces(a.get_text(" ", strip=True))
        if not label or PAGER_RE.match(label) or label.lower() in SKIP_LABELS:
            continue
        href = _abs(href_raw, base_url)
        if href.startswith("javascript:") and not _looks_like_data_link(a):
            continue
        nit, nombre = parse_nit_nombre(label)
        kind = classify_row(label, href)
        if kind == "unknown":
            continue
        extra = _sibling_text(a)
        key = f"{kind}|{nit or label}|{href}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            ListRow(
                label=label,
                href=href,
                nit=nit,
                nombre=nombre or nombre_buscable(label),
                extra=extra,
                kind=kind,
            )
        )
    return rows


def _looks_like_data_link(a: Tag) -> bool:
    text = clean_spaces(a.get_text(" ", strip=True))
    return bool(NIT_NAME_RE.match(text) or NIT_ONLY_RE.match(text))


def _sibling_text(a: Tag) -> str:
    td = a.find_parent("td")
    if not td:
        return ""
    tr = td.find_parent("tr")
    if not tr:
        return ""
    cells = [clean_spaces(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
    link_text = clean_spaces(a.get_text(" ", strip=True))
    extras = [c for c in cells if c and c != link_text and not PAGER_RE.match(c)]
    return " | ".join(extras[1:] if extras and extras[0] == link_text else extras)


def parse_motivo_rows(html: str, *, base_url: str) -> list[MotivoRow]:
    """Tabla de consultaProveeInhabRes.aspx: secciones + motivos con conteo."""
    soup = BeautifulSoup(html, "lxml")
    out: list[MotivoRow] = []
    seccion = ""
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [clean_spaces(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            if len(cells) == 1 and any(m in cells[0].upper() for m in SECCION_MARKERS):
                seccion = cells[0]
                continue
            if len(cells) < 3:
                continue
            if cells[0].lower().startswith("motivo"):
                continue
            href = ""
            for a in tr.find_all("a", href=True):
                h = _abs(a.get("href") or "", base_url)
                if _is_motivo_href(h):
                    href = h
                    break
            try:
                cantidad = int(re.sub(r"[^\d]", "", cells[-1]) or "0")
            except ValueError:
                cantidad = 0
            if not cells[0] or (not href and cantidad == 0 and len(cells[0]) < 8):
                continue
            out.append(
                MotivoRow(
                    seccion=seccion,
                    motivo=cells[0],
                    explicacion=cells[1] if len(cells) > 2 else "",
                    cantidad=cantidad,
                    href=href,
                )
            )
    return out


def parse_pager_labels(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    labels: list[str] = []
    scope = soup
    for node in soup.find_all(string=re.compile(r"Ir a la página", re.I)):
        parent = getattr(node, "parent", None)
        if parent:
            scope = parent.find_parent("tr") or parent.find_parent("table") or parent
            break
    for a in scope.find_all("a"):
        text = clean_spaces(a.get_text(" ", strip=True))
        if PAGER_RE.match(text) or text in {"...", "»", "›", "Siguiente", "Next"}:
            labels.append(text)
    return labels


def current_page_number(html: str) -> Optional[int]:
    soup = BeautifulSoup(html, "lxml")
    # ASP.NET GridView marca la página actual como span (no link)
    for span in soup.find_all("span"):
        text = clean_spaces(span.get_text(" ", strip=True))
        if PAGER_RE.match(text) and span.find_parent("table"):
            parent_text = clean_spaces(span.parent.get_text(" ", strip=True)) if span.parent else ""
            if "página" in parent_text.lower() or "pagina" in parent_text.lower() or PAGER_RE.match(text):
                try:
                    return int(text)
                except ValueError:
                    continue
    return None


def _label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    pairs: dict[str, str] = {}

    def put(key: str, val: str) -> None:
        key = clean_spaces(key).lower().rstrip(":")
        val = clean_spaces(val)
        if key and val and len(key) < 80:
            pairs.setdefault(key, val)

    for node in soup.find_all(["td", "th", "span", "label", "div", "strong", "b", "p", "li"]):
        text = clean_spaces(node.get_text(" ", strip=True))
        if not text or ":" not in text:
            continue
        key, _, val = text.partition(":")
        put(key, val)

    # Label y valor en celdas hermanas: <td>Nombre:</td><td>(NIT) - ...</td>
    for tr in soup.find_all("tr"):
        cells = [clean_spaces(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
        if len(cells) >= 2 and cells[0].endswith(":"):
            put(cells[0], cells[1])
    return pairs


def _pick(pairs: dict[str, str], *needles: str) -> str:
    for key, val in pairs.items():
        if any(n in key for n in needles):
            return val
    return ""


def parse_detail(html: str, *, url: str = "") -> ProviderDetail:
    soup = BeautifulSoup(html, "lxml")
    pairs = _label_value_pairs(soup)
    raw_nombre = _pick(pairs, "nombre del proveedor", "nombre del provedor", "proveedor")
    situacion = _pick(pairs, "situación actual", "situacion actual", "estatus actual")
    nit, nombre = parse_nit_nombre(raw_nombre)
    if not nombre:
        nombre = raw_nombre
    sanciones = _parse_historial(soup)
    return ProviderDetail(
        nit=nit,
        nombre=nombre_buscable(nombre),
        nombre_original=nombre,
        situacion_actual=situacion,
        sanciones=sanciones,
        url=url,
    )


def _header_index(headers: list[str], *needles: str) -> Optional[int]:
    for i, h in enumerate(headers):
        hl = h.lower()
        if any(n in hl for n in needles):
            return i
    return None


def _parse_historial(soup: BeautifulSoup) -> list[Sancion]:
    sanciones: list[Sancion] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [clean_spaces(c.get_text(" ", strip=True)) for c in rows[0].find_all(["th", "td"])]
        i_inicio = _header_index(headers, "inicio")
        i_dur = _header_index(headers, "duración", "duracion")
        i_mot = _header_index(headers, "motivo")
        i_num = _header_index(headers, "número de", "numero de", "nº de", "n° de")
        if i_num is None:
            i_num = _header_index(headers, "número", "numero")
        i_est = _header_index(headers, "estatus", "status")
        if i_mot is None and i_num is None:
            continue
        if len(headers) < 3:
            continue
        for tr in rows[1:]:
            cells = [clean_spaces(c.get_text(" ", strip=True)) for c in tr.find_all("td")]
            if not cells or all(not c for c in cells):
                continue
            if cells[0].lower().startswith("ir a"):
                continue

            def cell(idx: Optional[int]) -> str:
                if idx is None or idx >= len(cells):
                    return ""
                return cells[idx]

            sanciones.append(
                Sancion(
                    fecha_inicio=cell(i_inicio),
                    duracion=cell(i_dur),
                    motivo=cell(i_mot),
                    numero_inhabilitacion=cell(i_num),
                    estatus=cell(i_est),
                )
            )
        if sanciones:
            break
    return sanciones


_CHALLENGE_MARKERS = (
    "just a moment",
    "un momento",
    "attention required",
    "security verification",
    "enable javascript and cookies",
    "cf-browser-verification",
    "performing security verification",
    "verifique que es un ser humano",
    "checking your browser",
)


def looks_blocked(html: str, title: str = "") -> bool:
    title_l = (title or "").lower()
    if any(s in title_l for s in ("un momento", "just a moment")):
        return True
    if "guatecompras" in title_l:
        return False
    blob = f"{title}\n{html[:2500]}".lower()
    return any(s in blob for s in _CHALLENGE_MARKERS)


def looks_like_error_page(html: str, title: str = "") -> bool:
    blob = f"{title}\n{html[:4000]}".lower()
    return any(
        s in blob
        for s in (
            "error del servidor",
            "server error",
            "servicio no disponible",
            "service unavailable",
            "http 503",
            "http 502",
        )
    )
