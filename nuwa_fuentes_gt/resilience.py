"""Reintentos, backoff y pausa cuando Guatecompras / Cloudflare cae."""

from __future__ import annotations

import random
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

DEFAULT_BASE_DELAY_S = 5.0
DEFAULT_MAX_DELAY_S = 120.0
DEFAULT_MAX_ATTEMPTS = 8


class TransientNetworkError(Exception):
    """Red caída, timeout, 429/5xx o challenge de Cloudflare."""


class SiteUnavailable(TransientNetworkError):
    """El portal no responde; el batch debe pausar y reanudar."""


class BatchInterrupted(TransientNetworkError):
    """Batch pausado a propósito; reanudar con el mismo comando."""


def is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (TransientNetworkError, BatchInterrupted, SiteUnavailable)):
        return True
    name = type(exc).__name__.lower()
    if any(s in name for s in ("timeout", "net", "connect", "targetclosed", "protocol")):
        return True
    msg = str(exc).lower()
    needles = (
        "network",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "name or service not known",
        "nodename nor servname",
        "failed to establish",
        "err_connection",
        "err_timed_out",
        "err_failed",
        "net::",
        "429",
        "503",
        "502",
        "504",
        "cloudflare",
        "just a moment",
        "attention required",
        "security verification",
        "enable javascript and cookies",
        "ray id",
    )
    return any(n in msg for n in needles)


def backoff_delay(attempt: int, *, base: float, max_delay: float) -> float:
    delay = min(max_delay, base * (2 ** (attempt - 1)))
    jitter = delay * random.uniform(-0.15, 0.15)
    return max(1.0, delay + jitter)


def polite_sleep(seconds: float) -> None:
    if seconds <= 0:
        return
    jitter = seconds * random.uniform(-0.20, 0.35)
    time.sleep(max(0.4, seconds + jitter))


def retry_call(
    fn: Callable[[], T],
    *,
    label: str = "operación",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> T:
    last: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            last = exc
            if not is_transient_error(exc) or attempt >= max_attempts:
                raise
            wait = backoff_delay(attempt, base=base_delay_s, max_delay=max_delay_s)
            if on_retry:
                on_retry(attempt, exc, wait)
            else:
                print(
                    f"[retry] {label} intento {attempt}/{max_attempts} "
                    f"({type(exc).__name__}) — espera {wait:.0f}s…"
                )
            time.sleep(wait)
    assert last is not None
    raise TransientNetworkError(f"{label} falló tras {max_attempts} intentos: {last}") from last


def wait_until_available(
    check_fn: Callable[[], bool],
    *,
    label: str = "sitio",
    pause_s: float = 180.0,
    max_pause_s: float = 900.0,
    on_pause: Optional[Callable[[float, BaseException], None]] = None,
) -> None:
    """Pausa el proceso hasta que el portal vuelva (no aborta el batch)."""
    delay = pause_s
    while True:
        try:
            if check_fn():
                print(f"[resilience] {label} volvió — reanudando")
                return
            exc: BaseException = SiteUnavailable(f"{label} no disponible")
        except BaseException as caught:
            exc = caught
            if not is_transient_error(caught):
                raise
        if on_pause:
            on_pause(delay, exc)
        else:
            print(
                f"[resilience] {label} caído ({type(exc).__name__}) — "
                f"pausa {delay:.0f}s hasta que vuelva…"
            )
        time.sleep(delay)
        delay = min(max_pause_s, delay * 1.5)
