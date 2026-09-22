from nuwa_fuentes_gt.delta import ControlFile
from nuwa_fuentes_gt.models import (
    RegistroInhabilitacion,
    normalize_nombre_nuwa,
    registro_id,
    strip_tipo_sociedad,
)
from nuwa_fuentes_gt.store import load_registro, registro_is_complete, save_registro


def test_strip_tipo_sociedad() -> None:
    limpio, tipo = strip_tipo_sociedad(
        "AGUIRRE CHINCHILLA INGENIEROS CONSULTORES, SOCIEDAD ANÓNIMA"
    )
    assert limpio == "AGUIRRE CHINCHILLA INGENIEROS CONSULTORES"
    assert tipo == "SOCIEDAD ANONIMA"
    limpio2, tipo2 = strip_tipo_sociedad("AGROINDUSTRIAS LA JOYA SOCIEDAD ANONIMA")
    assert limpio2 == "AGROINDUSTRIAS LA JOYA"
    assert tipo2 == "SOCIEDAD ANONIMA"
    # Traducción PT del browser
    limpio3, tipo3 = strip_tipo_sociedad("AGROINDUSTRIAS LA JOYA SOCIEDADE ANÓNIMA")
    assert limpio3 == "AGROINDUSTRIAS LA JOYA"
    assert tipo3 == "SOCIEDAD ANONIMA"
    # No recortar el nombre de una asociación
    limpio4, tipo4 = strip_tipo_sociedad("ASOCIACION NACIONAL DE SORDOS DE GUATEMALA")
    assert "ASOCIACION NACIONAL" in limpio4
    assert tipo4 == ""


def test_normalize_nombre_nuwa_matches_apis() -> None:
    assert normalize_nombre_nuwa("José Peña") == "jose pena"
    assert normalize_nombre_nuwa("AGUIRRE CHINCHILLA INGENIEROS CONSULTORES") == (
        "aguirre chinchilla ingenieros consultores"
    )


def test_registro_limpia_sociedad_anonima() -> None:
    reg = RegistroInhabilitacion(
        registro_id="gt-gc-inh-12112917-SANC2018219",
        id="12112917",
        nombre="AGROINDUSTRIAS LA JOYA SOCIEDAD ANÓNIMA",
        nit="12112917",
        tipo_persona="moral",
        estado="INHABILITADO",
        motivo="Insolvencia de Seguridad Social",
        fecha="15/11/2017",
        duracion="18/12/2018",
        numero_inhabilitacion="SANC2018219",
        estatus="Vigente",
        situacion_actual="INHABILITADO",
    )
    assert reg.nombre == "AGROINDUSTRIAS LA JOYA"
    assert reg.tipo_sociedad == "SOCIEDAD ANONIMA"
    assert reg.nombre_normalizado == "agroindustrias la joya"
    chunk = reg.to_nuwa_chunk()
    assert chunk["nombre"] == "AGROINDUSTRIAS LA JOYA"
    assert "sociedad" not in chunk["nombre"].lower()
    assert chunk["Estatus"] == "Vigente"
    assert chunk["Duración de la inhabilitación"] == "18/12/2018"


def test_registro_id_stable() -> None:
    a = registro_id("95021816", "SANC202251")
    b = registro_id("95-021-816", "SANC202251")
    assert a == b == "gt-gc-inh-95021816-SANC202251"


def test_chunk_has_guatemala_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nuwa_fuentes_gt.store.JSONS_DIR", tmp_path)
    reg = RegistroInhabilitacion(
        registro_id="gt-gc-inh-95021816-SANC202251",
        id="95021816",
        nombre="ABAL, NORIEGA, VICTOR, ESTUARDO",
        nit="95021816",
        tipo_persona="fisica",
        estado="INHABILITADO",
        motivo="Insolvencia de Seguridad Social",
        fecha="14/06/2022",
        numero_inhabilitacion="SANC202251",
    )
    path = save_registro(reg)
    assert path.exists()
    assert registro_is_complete(reg.registro_id)
    loaded = load_registro(reg.registro_id)
    assert loaded is not None
    chunk = loaded.to_nuwa_chunk()
    assert chunk["pais"] == "Guatemala"
    assert chunk["pais_codigo"] == "GT"
    assert loaded.nombre == "ABAL NORIEGA VICTOR ESTUARDO"
    assert loaded.nombre_normalizado == "abal noriega victor estuardo"
    assert chunk["nombre_normalizado"] == "abal noriega victor estuardo"
    assert chunk["Situación actual"] == "INHABILITADO"
    assert chunk["Inicio"] == "14/06/2022"
    assert chunk["Motivo"] == "Insolvencia de Seguridad Social"
    assert chunk["Número de inhabilitación"] == "SANC202251"


def test_control_knows_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nuwa_fuentes_gt.store.JSONS_DIR", tmp_path)
    monkeypatch.setattr("nuwa_fuentes_gt.delta.indexed_ids", lambda: set())
    ctrl = ControlFile()
    ctrl.mark_registro("gt-gc-inh-1-A")
    assert ctrl.knows("gt-gc-inh-1-A")
    assert not ctrl.knows("gt-gc-inh-2-B")
    dest = tmp_path / "control.json"
    ctrl.save(dest)
    loaded = ControlFile.load(dest)
    assert loaded.pais_codigo == "GT"
    assert "gt-gc-inh-1-A" in loaded.registro_ids
