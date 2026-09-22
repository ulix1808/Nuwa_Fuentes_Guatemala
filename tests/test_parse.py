from pathlib import Path

from nuwa_fuentes_gt.models import infer_tipo_persona, registro_id
from nuwa_fuentes_gt.parse import (
    looks_blocked,
    parse_detail,
    parse_list_rows,
    parse_motivo_rows,
    parse_nit_nombre,
)
from nuwa_fuentes_gt.scrape import records_from_detail

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.guatecompras.gt/inhabilitaciones/"


def test_looks_blocked_spanish_challenge() -> None:
    assert looks_blocked("<html></html>", "Un momento…")
    assert not looks_blocked("<html>tabla</html>", "Guatecompras - Proveedores Inhabilitados Por Tipo")


def test_parse_nit_nombre() -> None:
    nit, nombre = parse_nit_nombre("(95021816) - ABAL, NORIEGA, VICTOR, ESTUARDO")
    assert nit == "95021816"
    assert "ABAL" in nombre


def test_infer_tipo_persona() -> None:
    assert infer_tipo_persona("ALIMENTOS INDUSTRIALIZADOS SANTO DOMINGO, SOCIEDAD ANONIMA") == "moral"
    assert infer_tipo_persona("ABAL, NORIEGA, VICTOR, ESTUARDO") == "fisica"


def test_parse_provider_list() -> None:
    html = (FIXTURES / "list_providers.html").read_text(encoding="utf-8")
    rows = parse_list_rows(html, base_url=BASE)
    providers = [r for r in rows if r.kind == "provider"]
    assert len(providers) == 2
    assert providers[1].nit == "95021816"
    assert "consultaDetProveeinhab" in providers[0].href


def test_parse_motivo_list() -> None:
    html = (FIXTURES / "list_motivos.html").read_text(encoding="utf-8")
    motivos = parse_motivo_rows(html, base_url=BASE)
    assert len(motivos) == 3
    sat = [m for m in motivos if "SAT" in m.seccion][0]
    assert sat.cantidad == 637
    assert "consultaProveeInhabTipo.aspx" in sat.href
    assert "Tributarias" in sat.motivo


def test_parse_detail_and_chunks() -> None:
    html = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    detail = parse_detail(html, url="https://example/det")
    assert detail.nit == "95021816"
    assert detail.situacion_actual == "INHABILITADO"
    assert len(detail.sanciones) == 2
    assert detail.sanciones[0].numero_inhabilitacion == "SANC202251"

    regs = records_from_detail(
        html=html,
        url="https://example/det",
        list_url="https://example/list",
        entidad_label="MINISTERIO DE FINANZAS PUBLICAS",
        entidad_url="https://example/ent",
        autoridad="MINISTERIO DE FINANZAS PUBLICAS",
    )
    assert len(regs) == 2
    chunk = regs[0].to_nuwa_chunk()
    assert chunk["pais"] == "Guatemala"
    assert chunk["pais_codigo"] == "GT"
    assert chunk["fuente_pais"] == "GT"
    assert chunk["id"] == "95021816"
    assert chunk["nombre"] == "ABAL NORIEGA VICTOR ESTUARDO"
    assert chunk["nombre_normalizado"] == "abal noriega victor estuardo"
    assert chunk["tipo_persona"] == "fisica"
    assert chunk["numero_inhabilitacion"] == "SANC202251"
    assert chunk["Situación actual"] == "INHABILITADO"
    assert chunk["Inicio"] == "14/06/2022"
    assert chunk["Duración de la inhabilitación"]
    assert chunk["Estatus"] == "Vigente"
    assert chunk["autoridad"] == "MINISTERIO DE FINANZAS PUBLICAS"
    assert chunk["entidad_compradora"] == "MINISTERIO DE FINANZAS PUBLICAS"
    assert regs[0].registro_id == registro_id("95021816", "SANC202251")
