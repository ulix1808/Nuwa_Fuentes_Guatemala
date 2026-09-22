from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local")

# Identidad de esta fuente (se copia a cada JSON).
# pais / pais_codigo distinguen Guatemala de otras fuentes-país en Nuwa.
PAIS = "Guatemala"
PAIS_CODIGO = "GT"
FUENTE_ID = "guatecompras_inhabilitaciones"
FUENTE_NOMBRE = "Guatecompras — Inhabilitaciones de proveedores"
FUENTE_URL = "https://www.guatecompras.gt/inhabilitaciones/consultaProveeInhabRes.aspx"
LIST_URL = os.getenv("GUATECOMPRAS_LIST_URL", FUENTE_URL).strip()
DETAIL_PATH = "consultaDetProveeinhab.aspx"
PROVIDER_LIST_PATH = "consultaProveeInhab.aspx"

# Riesgo sugerido al ingestir en Nuwa (0=bajo … 3=crítico). Solo metadata local.
RISK_LEVEL_SUGERIDO = 3


def _path(env_key: str, default: str) -> Path:
    raw = (os.getenv(env_key) or default).strip()
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def _float(env_key: str, default: float) -> float:
    raw = (os.getenv(env_key) or "").strip()
    return float(raw) if raw else default


def _int(env_key: str, default: int) -> int:
    raw = (os.getenv(env_key) or "").strip()
    return int(raw) if raw else default


def _bool(env_key: str, default: bool = False) -> bool:
    raw = (os.getenv(env_key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


DATA_DIR = _path("DATA_DIR", "data")
JSONS_DIR = DATA_DIR / "jsons"
EXPORTS_DIR = DATA_DIR / "exports"
CONTROL_PATH = DATA_DIR / "control.json"
BATCH_STATE_PATH = DATA_DIR / "batch_state.json"
BROWSER_STATE_PATH = DATA_DIR / "browser_state.json"
CHROME_PROFILE_DIR = DATA_DIR / "chrome_profile"

REQUEST_DELAY_S = _float("REQUEST_DELAY_S", 2.5)
SITE_DOWN_PAUSE_S = _float("SITE_DOWN_PAUSE_S", 180.0)
SITE_DOWN_PAUSE_MAX_S = _float("SITE_DOWN_PAUSE_MAX_S", 900.0)
MAX_ATTEMPTS = _int("MAX_ATTEMPTS", 8)
RETRY_BASE_S = _float("RETRY_BASE_S", 5.0)
RETRY_MAX_S = _float("RETRY_MAX_S", 120.0)
NAV_TIMEOUT_MS = _int("NAV_TIMEOUT_MS", 60_000)
HEADED = _bool("HEADED", False)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JSONS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
