"""Хранилище модуля мерч-кодов: SQLite вместо имитации из прототипа.

Схема:
  config — одна строка: ключ шифрования, каталог (JSON), реквизиты
           сертификата (JSON), дата создания;
  ledger — журнал выданных номеров: снимок изделия на момент выдачи,
           число проверок, данные владельца (если зарегистрирован).

Слот (type-color-month-place-seq) уникален на уровне БД — это защита от
гонок при одновременном сохранении одной комбинации.

Ключ шифрования генерируется при первом запуске и дублируется в файл
serial-key.backup.json рядом с базой; его нужно хранить отдельно от
резервной копии базы (см. docs/merch-module.md, раздел «Бэкапы»).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

from . import serials
from .catalog_seed import SEED_CATALOG, SEED_CERTIFICATE

_LEDGER_COLUMNS = (
    "code, slot, type, color, month, place, seq, product, color_name, hex, img, "
    "site, sheet, edition, issued_at, checks, last_check, "
    "owner_email, owner_first, owner_last, owner_dob, registered_at"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, data_dir: str, serial_key_override: str | None = None):
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, "merch.db")
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self._provision(serial_key_override)

    def _migrate(self) -> None:
        with self._lock, self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    key TEXT NOT NULL,
                    catalog TEXT NOT NULL,
                    certificate TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )""")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS ledger (
                    code TEXT PRIMARY KEY,
                    slot TEXT NOT NULL UNIQUE,
                    type INTEGER NOT NULL,
                    color INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    place INTEGER NOT NULL,
                    seq INTEGER NOT NULL,
                    product TEXT NOT NULL,
                    color_name TEXT NOT NULL,
                    hex TEXT,
                    img TEXT,
                    site TEXT NOT NULL,
                    sheet TEXT NOT NULL DEFAULT 'a5',
                    edition INTEGER,
                    issued_at TEXT NOT NULL,
                    checks INTEGER NOT NULL DEFAULT 0,
                    last_check TEXT,
                    owner_email TEXT,
                    owner_first TEXT,
                    owner_last TEXT,
                    owner_dob TEXT,
                    registered_at TEXT
                )""")

    def _provision(self, key_override: str | None) -> None:
        with self._lock:
            row = self._db.execute("SELECT key FROM config WHERE id = 1").fetchone()
            if row:
                if key_override and key_override != row["key"]:
                    raise RuntimeError(
                        "MERCH_SERIAL_KEY не совпадает с ключом, уже сохранённым в базе. "
                        "Уберите переменную или восстановите правильный ключ — иначе "
                        "выпущенные номера перестанут проверяться."
                    )
                return
            key = (key_override or serials.random_key()).strip().lower()
            if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
                raise RuntimeError("MERCH_SERIAL_KEY должен быть 32 hex-символа (128 бит)")
            with self._db:
                self._db.execute(
                    "INSERT INTO config (id, key, catalog, certificate, created_at) VALUES (1, ?, ?, ?, ?)",
                    (key, json.dumps(SEED_CATALOG), json.dumps(SEED_CERTIFICATE), _now()),
                )
            self._write_key_backup(key)

    def _write_key_backup(self, key: str) -> None:
        backup = os.path.join(self.data_dir, "serial-key.backup.json")
        payload = {
            "warning": "Ключ шифрования серийных номеров. Хранить отдельно от базы. "
                       "Потеря ключа делает нечитаемой всю выпущенную маркировку.",
            "key": key,
            "fingerprint": serials.key_fingerprint(key),
            "createdAt": _now(),
        }
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---------- config ----------

    @property
    def key(self) -> str:
        with self._lock:
            return self._db.execute("SELECT key FROM config WHERE id = 1").fetchone()["key"]

    def key_fingerprint(self) -> str:
        return serials.key_fingerprint(self.key)

    def catalog(self) -> dict:
        with self._lock:
            row = self._db.execute("SELECT catalog FROM config WHERE id = 1").fetchone()
        return json.loads(row["catalog"])

    def save_catalog(self, catalog: dict) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE config SET catalog = ? WHERE id = 1", (json.dumps(catalog),))

    def certificate(self) -> dict:
        with self._lock:
            row = self._db.execute("SELECT certificate FROM config WHERE id = 1").fetchone()
        return json.loads(row["certificate"])

    def save_certificate(self, certificate: dict) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE config SET certificate = ? WHERE id = 1", (json.dumps(certificate),))

    # ---------- ledger ----------

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        r = {
            "code": row["code"], "slot": row["slot"],
            "type": row["type"], "color": row["color"], "month": row["month"],
            "place": row["place"], "seq": row["seq"],
            "product": row["product"], "colorName": row["color_name"], "hex": row["hex"],
            "img": row["img"], "site": row["site"], "sheet": row["sheet"], "edition": row["edition"],
            "issuedAt": row["issued_at"], "checks": row["checks"], "lastCheck": row["last_check"],
        }
        if row["registered_at"]:
            r["owner"] = {
                "email": row["owner_email"], "firstName": row["owner_first"],
                "lastName": row["owner_last"], "dob": row["owner_dob"],
                "registeredAt": row["registered_at"],
            }
        else:
            r["owner"] = None
        return r

    def find_by_slot(self, slot: str) -> dict | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_LEDGER_COLUMNS} FROM ledger WHERE slot = ?", (slot,)).fetchone()
        return self._record(row) if row else None

    def find_by_code(self, code: str) -> dict | None:
        with self._lock:
            row = self._db.execute(f"SELECT {_LEDGER_COLUMNS} FROM ledger WHERE code = ?", (code,)).fetchone()
        return self._record(row) if row else None

    def insert_record(self, rec: dict) -> bool:
        """Возвращает False, если код или слот уже заняты (гонка)."""
        with self._lock:
            try:
                with self._db:
                    self._db.execute(
                        """INSERT INTO ledger (code, slot, type, color, month, place, seq,
                               product, color_name, hex, img, site, sheet, edition, issued_at, checks)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (rec["code"], rec["slot"], rec["type"], rec["color"], rec["month"],
                         rec["place"], rec["seq"], rec["product"], rec["colorName"], rec["hex"],
                         rec["img"], rec["site"], rec["sheet"], rec["edition"], _now()),
                    )
                return True
            except sqlite3.IntegrityError:
                return False

    def used_seqs(self, type_: int, color: int, month: int, place: int) -> set[int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT seq FROM ledger WHERE type = ? AND color = ? AND month = ? AND place = ?",
                (type_, color, month, place),
            ).fetchall()
        return {r["seq"] for r in rows}

    def all_records(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_LEDGER_COLUMNS} FROM ledger ORDER BY issued_at DESC, code DESC"
            ).fetchall()
        return [self._record(r) for r in rows]

    def count_records(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()["n"]

    def delete_record(self, code: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM ledger WHERE code = ?", (code,))
            return cur.rowcount > 0

    def clear_ledger(self) -> int:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM ledger")
            return cur.rowcount

    def bump_checks(self, code: str) -> int:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE ledger SET checks = checks + 1, last_check = ? WHERE code = ?",
                (_now(), code),
            )
            return self._db.execute("SELECT checks FROM ledger WHERE code = ?", (code,)).fetchone()["checks"]

    def register_owner(self, code: str, owner: dict) -> bool:
        """Одноразовая регистрация владельца; False — уже зарегистрирован."""
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE ledger SET owner_email = ?, owner_first = ?, owner_last = ?,
                       owner_dob = ?, registered_at = ?
                   WHERE code = ? AND registered_at IS NULL""",
                (owner["email"], owner["firstName"], owner["lastName"], owner["dob"], _now(), code),
            )
            return cur.rowcount > 0
