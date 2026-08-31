"""Доступ и ограничение частоты запросов.

Роли (упрощённая версия ролей прототипа, см. docs/merch-module.md):
  production — генерация и сохранение номеров, просмотр журнала
               (PIN из MERCH_PRODUCTION_PIN);
  admin      — всё то же плюс правка каталога и удаление записей
               (PIN из MERCH_ADMIN_PIN).
Проверка кода (verify) и регистрация владельца — публичные, но с
ограничением частоты на IP.

PIN передаётся в заголовке X-Pin. Если PIN-ы не заданы в окружении,
служебные эндпоинты отвечают 503 — модуль сознательно не работает с
кодами по умолчанию.
"""

from __future__ import annotations

import hmac
import os
import threading
import time


class Roles:
    def __init__(self) -> None:
        self.production_pin = (os.environ.get("MERCH_PRODUCTION_PIN") or "").strip()
        self.admin_pin = (os.environ.get("MERCH_ADMIN_PIN") or "").strip()

    @property
    def configured(self) -> bool:
        # PIN-ы должны быть заданы, различаться и быть не короче 4 знаков —
        # иначе служебные эндпоинты остаются выключенными (503).
        return (
            len(self.production_pin) >= 4
            and len(self.admin_pin) >= 4
            and self.production_pin != self.admin_pin
        )

    def role_of(self, pin: str | None) -> str | None:
        if not pin or not self.configured:
            return None
        if hmac.compare_digest(pin, self.admin_pin):
            return "admin"
        if hmac.compare_digest(pin, self.production_pin):
            return "production"
        return None


class RateLimiter:
    """Скользящее окно на IP и класс операции; состояние в памяти процесса."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], list[float]] = {}

    def allow(self, ip: str, bucket: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        key = (ip, bucket)
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < window_s]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10000:  # защита от разрастания на переборе IP
                cutoff = now - window_s
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}
            return True


def client_ip(request) -> str:
    """IP клиента; за прокси (Caddy) берём первый адрес из X-Forwarded-For."""
    if os.environ.get("MERCH_BEHIND_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
