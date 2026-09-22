from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from nuwa_fuentes_gt.config import (
    FUENTE_ID,
    FUENTE_NOMBRE,
    FUENTE_URL,
    PAIS,
    PAIS_CODIGO,
    RISK_LEVEL_SUGERIDO,
)

TipoPersona = Literal["fisica", "moral", "desconocido"]

# Sufijos al FINAL del nombre (Guatecompras + variantes de traducción).
# Más largos primero. No se quitan palabras que forman parte del nombre
# (p. ej. "ASOCIACION NACIONAL DE SORDOS").
_TIPO_SOCIEDAD_RES = tuple(
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        r",?\s+SOCIEDAD\s+DE\s+RESPONSABILIDAD\s+LIMITADA\s*$",
        r",?\s+SOCIEDADE?\s+AN[OÓ]NIM[AO]\s*$",
        r",?\s+SOCIEDAD\s+EN\s+COMANDITA(?:\s+POR\s+ACCIONES)?\s*$",
        r",?\s+SOCIEDAD\s+COLECTIVA\s*$",
        r",?\s+EMPRESA\s+INDIVIDUAL\s*$",
        r",?\s+COMPA[NÑ][IÍ]A\s+LIMITADA\s*$",
        r",?\s+S\.?\s*A\.?\s*DE\s+C\.?\s*V\.?\s*$",
        r",?\s+C\.?\s*POR\s*A\.?\s*$",
        r",?\s+CIA\.?\s*LTDA\.?\s*$",
        r",?\s+S\.?\s*R\.?\s*L\.?\s*$",
        r",?\s+\bSRL\s*$",
        r",?\s+S\.?\s*A\.?\s*$",
        r",?\s+\bSA\s*$",
        r",?\s+\bONG\s*$",
    )
)

_MORAL_MARKERS = (
    "SOCIEDAD",
    "S.A",
    "SA DE",
    "ANONIMA",
    "ANÓNIMA",
    "ANONIMO",
    "ANÓNIMO",
    "ASOCIACION",
    "ASOCIACIÓN",
    "FUNDACION",
    "FUNDACIÓN",
    "COOPERATIVA",
    "EMPRESA",
    "MUNICIPALIDAD",
    "ONG",
    "LIMITADA",
    "RESPONSABILIDAD",
    "COMPAÑIA",
    "COMPANIA",
    "CORPORACION",
    "CORPORACIÓN",
    "INSTITUTO",
    "MINISTERIO",
    "ORGANIZACION",
    "ORGANIZACIÓN",
    "CONSTRUCTORA",
    "COMERCIALIZADORA",
    "DISTRIBUIDORA",
    "SERVICIOS",
    "INVERSIONES",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def nit_digits(nit: str) -> str:
    return re.sub(r"[^\d]", "", nit or "")


def nombre_buscable(nombre: str) -> str:
    """Quita comas de listados GT (APELLIDO, APELLIDO, NOMBRE) para matching Nuwa."""
    return clean_spaces((nombre or "").replace(",", " "))


def normalize_nombre_nuwa(value: str) -> str:
    """Misma regla que APIs `normalize_name` / `normalize_chunk_search_text`."""
    if not value:
        return ""
    nfd = unicodedata.normalize("NFD", value)
    no_acc = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    cleaned = re.sub(r"[^a-z0-9\s]", "", no_acc.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def strip_tipo_sociedad(nombre: str) -> tuple[str, str]:
    """Separa 'SOCIEDAD ANÓNIMA' y variantes del nombre comercial."""
    rest = nombre_buscable(nombre)
    found: list[str] = []
    changed = True
    while changed:
        changed = False
        for pat in _TIPO_SOCIEDAD_RES:
            m = pat.search(rest)
            if not m:
                continue
            label = clean_spaces(m.group(0)).strip(" ,")
            if label:
                found.append(label.upper())
            rest = clean_spaces(pat.sub("", rest))
            changed = True
            break
    # Canónico para el tipo más común
    tipo = ""
    if found:
        joined = " ".join(found)
        if re.search(r"AN[OÓ]NIM", joined, re.I):
            tipo = "SOCIEDAD ANONIMA"
        elif re.search(r"RESPONSABILIDAD|SRL|S\.?\s*R", joined, re.I):
            tipo = "SOCIEDAD DE RESPONSABILIDAD LIMITADA"
        else:
            tipo = found[0]
    return rest, tipo


def infer_tipo_persona(nombre: str) -> TipoPersona:
    upper = (nombre or "").upper()
    if any(m in upper for m in _MORAL_MARKERS):
        return "moral"
    # "ABAL, NORIEGA, VICTOR, ESTUARDO" — patrón típico PF en Guatecompras
    parts = [p.strip() for p in (nombre or "").split(",") if p.strip()]
    if len(parts) >= 3 and all(len(p.split()) <= 2 for p in parts):
        return "fisica"
    if nombre and "," not in nombre and len(nombre.split()) <= 5:
        return "fisica"
    return "desconocido"


def registro_id(nit: str, numero_inhabilitacion: str, fecha_inicio: str = "", motivo: str = "") -> str:
    nit_key = nit_digits(nit) or "sinnit"
    sanc = re.sub(r"[^A-Za-z0-9_-]", "", (numero_inhabilitacion or "").strip())
    if sanc:
        return f"gt-gc-inh-{nit_key}-{sanc}"
    digest = hashlib.sha1(f"{nit_key}|{fecha_inicio}|{motivo}".encode("utf-8")).hexdigest()[:10]
    return f"gt-gc-inh-{nit_key}-{digest}"


def safe_filename(registro: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", registro)[:180]


@dataclass
class Sancion:
    fecha_inicio: str = ""
    duracion: str = ""
    motivo: str = ""
    numero_inhabilitacion: str = ""
    estatus: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "inicio": self.fecha_inicio,
            "fecha_inicio": self.fecha_inicio,
            "duracion": self.duracion,
            "Duración de la inhabilitación": self.duracion,
            "motivo": self.motivo,
            "numero_inhabilitacion": self.numero_inhabilitacion,
            "estatus": self.estatus,
        }


@dataclass
class RegistroInhabilitacion:
    """
    Un JSON local = una inhabilitación (una fila del historial).

    pais / pais_codigo identifican Guatemala frente a otras fuentes-país.
    id + nombre son las claves que Nuwa usa para matching PF/PM.
    """

    registro_id: str
    id: str
    nombre: str
    nit: str
    tipo_persona: TipoPersona
    estado: str
    motivo: str
    fecha: str
    fecha_inicio: str = ""
    inicio: str = ""
    duracion: str = ""
    numero_inhabilitacion: str = ""
    estatus: str = ""
    estatus_sancion: str = ""
    nombre_original: str = ""
    nombre_normalizado: str = ""
    tipo_sociedad: str = ""
    autoridad: str = ""
    motivo_catalogo: str = ""
    entidad_compradora: str = ""
    entidad_compradora_url: str = ""
    situacion_actual: str = ""
    url: str = ""
    url_listado: str = ""
    pais: str = PAIS
    pais_codigo: str = PAIS_CODIGO
    fuente_pais: str = PAIS_CODIGO
    fuente: str = FUENTE_NOMBRE
    fuente_id: str = FUENTE_ID
    fuente_url: str = FUENTE_URL
    tipo_fuente: str = "inhabilitacion"
    jurisdiccion: str = PAIS_CODIGO
    risk_level_sugerido: int = RISK_LEVEL_SUGERIDO
    historial: list[dict[str, str]] = field(default_factory=list)
    extraido_en: str = field(default_factory=utc_now)
    contenido_hash: str = ""

    def __post_init__(self) -> None:
        crudo = self.nombre_original or self.nombre
        if not self.nombre_original:
            self.nombre_original = nombre_buscable(crudo)
        if not self.tipo_persona or self.tipo_persona == "desconocido":
            self.tipo_persona = infer_tipo_persona(self.nombre_original)
        limpio, tipo_soc = strip_tipo_sociedad(crudo)
        self.nombre = limpio
        if not self.tipo_sociedad:
            self.tipo_sociedad = tipo_soc
        self.nombre_normalizado = normalize_nombre_nuwa(self.nombre)
        self.id = nit_digits(self.nit) or self.id
        self.nit = self.id
        if not self.situacion_actual:
            self.situacion_actual = self.estado
        if not self.estado:
            self.estado = self.situacion_actual
        self.inicio = self.inicio or self.fecha_inicio or self.fecha
        self.fecha_inicio = self.fecha_inicio or self.inicio or self.fecha
        if not self.fecha:
            self.fecha = self.inicio or self.fecha_inicio
        self.estatus = self.estatus or self.estatus_sancion
        self.estatus_sancion = self.estatus_sancion or self.estatus
        if not self.contenido_hash:
            self.contenido_hash = self.compute_hash()

    def compute_hash(self) -> str:
        key = "|".join(
            [
                self.nit,
                self.numero_inhabilitacion,
                self.fecha_inicio,
                self.motivo,
                self.estatus_sancion,
                self.situacion_actual,
            ]
        )
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["contenido_hash"] = self.compute_hash()
        return data

    def to_nuwa_chunk(self) -> dict[str, Any]:
        """Objeto listo para JSON.stringify → chunkText en /v1/chunks/ingest.

        `nombre` va sin tipo societario para no contaminar word_similarity.
        `nombre_normalizado` usa la misma regla que APIs (`ñ→n`, sin acentos).
        """
        return {
            "pais": self.pais,
            "pais_codigo": self.pais_codigo,
            "fuente_pais": self.fuente_pais,
            "fuente": self.fuente,
            "fuente_id": self.fuente_id,
            "nombre": self.nombre,
            "nombre_normalizado": self.nombre_normalizado,
            "Nombre del Contribuyente": self.nombre,
            "Razon Social": self.nombre,
            "id": self.id,
            "NIT": self.nit,
            "tipo_persona": self.tipo_persona,
            "tipo_sociedad": self.tipo_sociedad,
            "estado": self.situacion_actual or self.estado,
            "situacion_actual": self.situacion_actual,
            "Situación actual": self.situacion_actual,
            "motivo": self.motivo,
            "Motivo": self.motivo,
            "fecha": self.inicio or self.fecha_inicio or self.fecha,
            "inicio": self.inicio or self.fecha_inicio,
            "Inicio": self.inicio or self.fecha_inicio,
            "fecha_inicio": self.fecha_inicio or self.inicio,
            "duracion": self.duracion,
            "Duración de la inhabilitación": self.duracion,
            "numero_inhabilitacion": self.numero_inhabilitacion,
            "Número de inhabilitación": self.numero_inhabilitacion,
            "estatus": self.estatus or self.estatus_sancion,
            "Estatus": self.estatus or self.estatus_sancion,
            "autoridad": self.autoridad,
            "motivo_catalogo": self.motivo_catalogo,
            "entidad_compradora": self.entidad_compradora,
            "url": self.url,
            "jurisdiccion": self.jurisdiccion,
            "tipo_fuente": self.tipo_fuente,
        }


def from_dict(data: dict[str, Any]) -> RegistroInhabilitacion:
    allowed = {k: data[k] for k in RegistroInhabilitacion.__dataclass_fields__ if k in data}
    return RegistroInhabilitacion(**allowed)
