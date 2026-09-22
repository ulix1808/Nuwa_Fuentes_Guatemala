"""Playwright: Chrome real + perfil persistente para pasar Cloudflare."""

from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from nuwa_fuentes_gt.config import CHROME_PROFILE_DIR, HEADED, NAV_TIMEOUT_MS
from nuwa_fuentes_gt.parse import looks_blocked, looks_like_error_page
from nuwa_fuentes_gt.resilience import SiteUnavailable, TransientNetworkError

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


@contextmanager
def launch_browser(*, headed: Optional[bool] = None) -> Iterator[tuple[Playwright, BrowserContext, Page]]:
    """Abre el Chrome instalado con un perfil en data/chrome_profile (cookies CF)."""
    headed_flag = HEADED if headed is None else headed
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    kwargs = dict(
        user_data_dir=str(CHROME_PROFILE_DIR),
        headless=not headed_flag,
        locale="es-GT",
        timezone_id="America/Guatemala",
        viewport={"width": 1440, "height": 1100},
        ignore_https_errors=True,
        chromium_sandbox=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context: BrowserContext
    try:
        context = pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        print("[browser] Chrome del sistema + perfil persistente")
    except Exception as exc:
        print(f"[browser] Chrome del sistema no disponible ({exc}); uso Chromium de Playwright")
        context = pw.chromium.launch_persistent_context(**kwargs)
    context.add_init_script(_STEALTH_JS)
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    try:
        yield pw, context, page
    finally:
        context.close()
        pw.stop()


def page_html(page: Page) -> str:
    return page.content()


def assert_usable_page(page: Page) -> None:
    title = page.title() or ""
    html = ""
    try:
        html = page.content()
    except Exception as exc:
        raise TransientNetworkError(f"no se pudo leer HTML: {exc}") from exc
    if looks_blocked(html, title):
        raise TransientNetworkError(f"Cloudflare/challenge activo: {title or page.url}")
    if looks_like_error_page(html, title):
        raise SiteUnavailable(f"portal con error: {title or page.url}")
    if not html or len(html) < 200:
        raise SiteUnavailable(f"respuesta vacía: {page.url}")


def _page_still_challenged(page: Page) -> bool:
    try:
        return looks_blocked(page.content(), page.title() or "")
    except Exception:
        return True


def _click_box_left(page: Page, box: dict, label: str) -> bool:
    """Clic en el cuadrado izquierdo de la tarjeta Turnstile."""
    x = box["x"] + min(28.0, max(16.0, box["width"] * 0.08))
    y = box["y"] + box["height"] / 2.0
    try:
        page.mouse.move(x - random.uniform(30, 70), y + random.uniform(-10, 10))
        page.mouse.move(x, y, steps=random.randint(10, 18))
        time.sleep(random.uniform(0.2, 0.5))
        page.mouse.click(x, y)
        print(f"[browser] clic en casilla Cloudflare ({label})")
        return True
    except Exception:
        return False


def captcha_widget_visible(page: Page) -> bool:
    sels = (
        ".cf-turnstile",
        "#modalCaptcha",
        "#MasterGC_ContentBlockHolder_WucCaptcha_WucGcCaptcha_divCaptcha",
        "iframe[src*='challenges.cloudflare.com']",
    )
    for sel in sels:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                return True
        except Exception:
            continue
    try:
        return page.get_by_text("ser humano", exact=False).count() > 0
    except Exception:
        return False


def try_click_cloudflare_checkbox(page: Page) -> bool:
    """
    Clic en la casilla de la tarjeta inferior «Verifique que es un ser humano».
    No resuelve puzzles de imágenes.
    """
    clicked = False
    time.sleep(0.8)

    # 1) Tarjeta visible por texto (lo que se ve en la captura).
    try:
        card = page.get_by_text("ser humano", exact=False).first
        if card.count():
            box = card.bounding_box()
            if box:
                # El texto está a la derecha; la casilla queda ~90px a la izquierda.
                target = {
                    "x": max(0.0, box["x"] - 90),
                    "y": box["y"] - 8,
                    "width": 48,
                    "height": box["height"] + 16,
                }
                clicked = _click_box_left(page, target, "texto ser humano")
    except Exception:
        pass

    widget_sels = (
        ".cf-turnstile",
        "#MasterGC_ContentBlockHolder_WucCaptcha_WucGcCaptcha_divCaptcha",
        "#modalCaptcha .cf-turnstile",
        "iframe[src*='challenges.cloudflare.com']",
        "iframe[src*='turnstile']",
        ".cf-turnstile iframe",
    )
    if not clicked:
        for sel in widget_sels:
            loc = page.locator(sel).first
            try:
                if loc.count() == 0:
                    continue
                loc.wait_for(state="visible", timeout=3_000)
            except Exception:
                continue
            box = loc.bounding_box()
            if box and _click_box_left(page, box, sel):
                clicked = True
                break

    if not clicked:
        for frame in page.frames:
            try:
                cb = frame.locator("input[type='checkbox']")
                if cb.count() == 0:
                    continue
                cb.first.click(timeout=1_500, force=True)
                clicked = True
                print("[browser] clic checkbox dentro de iframe")
                break
            except Exception:
                continue

    try:
        btn = page.locator("#MasterGC_ContentBlockHolder_WucCaptcha_btnValidarCaptcha")
        if btn.count() and btn.is_visible():
            time.sleep(0.5)
            btn.click(timeout=2_000)
            print("[browser] clic en Aceptar del captcha de ficha")
            clicked = True
    except Exception:
        pass

    if clicked:
        time.sleep(random.uniform(1.5, 2.8))
    return clicked


def goto(page: Page, url: str, *, wait: str = "domcontentloaded", challenge_timeout_ms: int = 40_000) -> None:
    try:
        page.goto(url, wait_until=wait)
        _wait_challenge(page, timeout_ms=min(8_000, challenge_timeout_ms))
        if _page_still_challenged(page) or captcha_widget_visible(page):
            print(
                "[browser] Cloudflare a la vista — marca TÚ la casilla "
                "«Verifique que es un ser humano». No la pulse el script "
                "(Cloudflare lo rechaza y sale «verificación falló»)."
            )
            _wait_challenge(page, timeout_ms=max(120_000, challenge_timeout_ms))
        assert_usable_page(page)
    except SiteUnavailable:
        raise
    except TransientNetworkError:
        raise
    except Exception as exc:
        raise TransientNetworkError(f"navegación falló {url}: {exc}") from exc


def _wait_challenge(page: Page, timeout_ms: int = 40_000) -> None:
    try:
        page.wait_for_function(
            """() => {
                const t = (document.title || '').toLowerCase();
                const b = (document.body && document.body.innerText || '').toLowerCase();
                const blocked = t.includes('just a moment')
                    || t.includes('un momento')
                    || t.includes('attention required')
                    || t.includes('verificaci')
                    || b.includes('performing security verification')
                    || b.includes('enable javascript and cookies')
                    || b.includes('verifique que es un ser humano')
                    || b.includes('verifica que t')
                    || b.includes('verifico que soy')
                    || b.includes('verifico que es un ser humano');
                return !blocked && (t.includes('guatecompras') || (document.body && document.body.innerText.length > 200));
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        pass


def click_and_wait(page: Page, selector: str) -> None:
    try:
        page.locator(selector).first.click()
        page.wait_for_load_state("domcontentloaded")
        _wait_challenge(page)
        assert_usable_page(page)
    except SiteUnavailable:
        raise
    except TransientNetworkError:
        raise
    except Exception as exc:
        raise TransientNetworkError(f"click falló {selector}: {exc}") from exc


def click_text(page: Page, text: str) -> None:
    try:
        page.get_by_role("link", name=text, exact=True).first.click()
        page.wait_for_load_state("domcontentloaded")
        _wait_challenge(page)
        assert_usable_page(page)
    except Exception as exc:
        raise TransientNetworkError(f"click texto '{text}' falló: {exc}") from exc


def site_is_up(page: Page, url: str) -> bool:
    try:
        goto(page, url)
        return True
    except TransientNetworkError:
        return False


def wait_for_listado(page: Page, timeout_ms: int = 25_000, *, tipo: bool = False) -> None:
    """Espera links de ficha (página tipo) o de motivo (portada)."""
    sel = (
        "a[href*='consultaDetProveeInhab']"
        if tipo
        else "a[href*='consultaProveeInhabTipo.aspx'], a[href*='consultaDetProveeInhab']"
    )
    try:
        page.wait_for_selector(sel, timeout=timeout_ms)
    except Exception as exc:
        raise TransientNetworkError(f"listado no cargó: {exc}") from exc


def wait_for_ficha(page: Page, timeout_ms: int = 180_000) -> None:
    """Espera el historial. Si hay Turnstile, lo marca el usuario (no el script)."""
    try:
        page.wait_for_function(
            """() => {
                const el = document.getElementById('MasterGC_ContentBlockHolder_upContenido');
                if (!el) return false;
                const t = (el.innerText || '').toLowerCase();
                return t.includes('nombre') || t.includes('situaci') || t.includes('historial');
            }""",
            timeout=4_000,
        )
        return
    except Exception:
        pass
    print(
        "[browser] Ficha con captcha. Marca la casilla en la ventana "
        "(un clic humano). Espero hasta 3 minutos…"
    )
    try:
        page.wait_for_function(
            """() => {
                const el = document.getElementById('MasterGC_ContentBlockHolder_upContenido');
                if (!el) return false;
                const t = (el.innerText || '').toLowerCase();
                return t.includes('nombre') || t.includes('situaci') || t.includes('historial');
            }""",
            timeout=max(180_000, timeout_ms),
        )
    except Exception as exc:
        raise TransientNetworkError(
            "ficha no cargó — hay que marcar el captcha a mano en la ventana"
        ) from exc
