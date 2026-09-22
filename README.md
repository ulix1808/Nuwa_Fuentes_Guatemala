# Nuwa Fuentes Guatemala

Extractor **local** de inhabilitaciones de [Guatecompras](https://www.guatecompras.gt/inhabilitaciones/consultaProveeInhabRes.aspx). Igual que Nuwa Legal: primero se arma el corpus en disco; la ingestión a Nuwa 2.0 es un paso posterior.

Cada registro JSON lleva `pais`, `pais_codigo` y `fuente_pais` = Guatemala / `GT` para poder mezclar fuentes de varios países.

## Flujo del portal

1. `consultaProveeInhabRes.aspx` — motivos agrupados por autoridad (Entidades compradoras, IGSS, SAT, TSE, RGAE, INDE). El número de cada motivo abre el listado.
2. `consultaProveeInhabTipo.aspx` — proveedores actualmente inhabilitados por ese motivo, con paginación (`Ir a la página`).
3. `consultaDetProveeInhab.aspx` — situación actual + historial completo (inicio, duración, motivo, número, estatus).

Un JSON local = **una fila del historial** (una inhabilitación), con el nombre/NIT del proveedor.

## Instalación (esta u otra máquina)

Hace falta **Python 3.9+** y **Google Chrome** instalado (Playwright abre el Chrome del sistema para Cloudflare). En Linux: `google-chrome` o `google-chrome-stable`.

```bash
git clone git@github.com:ulix1808/Nuwa_Fuentes_Guatemala.git
cd Nuwa_Fuentes_Guatemala
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

No se versionan `.venv`, `.env`, `data/chrome_profile/` ni el corpus extraído. En la máquina nueva el perfil de Chrome se crea solo al correr.

## Uso

### Inspeccionar la primera página (sin guardar)

```bash
.venv/bin/python scripts/run_extract.py --probe
```

### Carga inicial (tope de prueba)

```bash
# Listados (NIT, nombre, autoridad, motivo) — recomendado para armar la base
.venv/bin/python scripts/run_extract.py --list-only --max 20 --delay 3

# Con fichas (historial). Requiere --headed por Turnstile de Cloudflare
.venv/bin/python scripts/run_extract.py --headed --max 10 --max-proveedores 5 --delay 3
```

### Carga completa

```bash
.venv/bin/python scripts/run_extract.py --delay 3
```

Si Cloudflare reta o la ficha pide Turnstile, usa `--headed` y **marca la casilla tú** (un clic automático lo rechaza). El listado sí se puede bajar con `--list-only`: NIT, nombre, autoridad y motivo. El perfil queda en `data/chrome_profile/` (local, no se sube al repo).

### Delta (solo registros nuevos)

```bash
.venv/bin/python scripts/run_extract.py
.venv/bin/python scripts/status.py
```

- **Dedup:** no reescribe `data/jsons/{registro_id}.json` si ya está completo.
- **Control:** `data/control.json` (`registro_ids`, `last_sync_at`, `registros_indexados`).
- **Reanudación:** `data/batch_state.json` (página, entidad actual, errores). Ctrl+C guarda checkpoint.

### Export para Nuwa (sin pegarle al portal)

```bash
.venv/bin/python scripts/export_nuwa.py
```

Genera `data/exports/nuwa_chunks.json`, `.jsonl` y `.csv`.

## JSON local (ejemplo)

```json
{
  "registro_id": "gt-gc-inh-12112917-SANC2018219",
  "id": "12112917",
  "nombre": "AGROINDUSTRIAS LA JOYA",
  "nombre_normalizado": "agroindustrias la joya",
  "nombre_original": "AGROINDUSTRIAS LA JOYA SOCIEDAD ANONIMA",
  "tipo_sociedad": "SOCIEDAD ANONIMA",
  "tipo_persona": "moral",
  "pais": "Guatemala",
  "pais_codigo": "GT",
  "situacion_actual": "INHABILITADO",
  "inicio": "15/11/2017",
  "duracion": "18/12/2018",
  "motivo": "Insolvencia de Seguridad Social",
  "numero_inhabilitacion": "SANC2018219",
  "estatus": "Vigente"
}
```

Campos que Nuwa usa al ingestir después: `nombre`, `id` (NIT), `pais`, `estado`, `fecha`, `motivo`.

## Resiliencia

- Playwright (Chrome) para pasar Cloudflare y postbacks ASP.NET.
- Pausa entre requests (`REQUEST_DELAY_S` / `--delay`).
- Reintentos con backoff ante 429/5xx/timeout.
- Si el portal se cae: checkpoint + espera (`SITE_DOWN_PAUSE_S`, hasta 15 min) y sigue.
- Escrituras atómicas (`.tmp` → rename).

## Estructura

```
nuwa_fuentes_gt/   # parse, browser, scrape, delta, export
scripts/           # run_extract, status, export_nuwa
data/jsons/        # un JSON por inhabilitación
data/control.json  # watermark / ids para delta
data/batch_state.json
data/exports/      # CSV + JSON para Nuwa
```

Uso interno Nuwa. Respetar términos de Guatecompras y no saturar el portal.
