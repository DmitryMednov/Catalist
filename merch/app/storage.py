"""Хранилище модуля мерч-кодов: SQLite вместо имитации из прототипа.

Схема версионируется таблицей schema_migrations: миграции аддитивные и
применяются автоматически при старте, поэтому база предыдущих сборок
обновляется на месте без потери данных (обратная совместимость сборок).

Таблицы:
  config            — одна строка: ключ шифрования, каталог, реквизиты
                      сертификата (JSON), дата создания;
  ledger            — журнал выданных номеров: снимок изделия на момент
                      выдачи, число проверок, владелец, кем выдан;
  app_config        — служебные ключ-значения (например, секрет сессий);
  users             — учётные записи персонала (вход через Google);
  sessions          — серверные сессии (в базе — только хэш токена);
  verify_log        — все проверки номеров: время, код, статус, IP;
  audit_log         — действия персонала: кто, когда, что сделал.

Гарантии уникальности номера — на уровне БД: PRIMARY KEY(code) и
UNIQUE(slot); slot = type-color-month-place-seq. Одновременные запросы
на одну комбинацию разрешаются констрейнтом, а не проверкой в коде.

Ключ шифрования генерируется при первом запуске и дублируется в файл
serial-key.backup.json рядом с базой; его нужно хранить отдельно от
резервной копии базы (см. docs/merch-module.md, раздел «Бэкапы»).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from . import serials
from .catalog_seed import SEED_CATALOG, SEED_CERTIFICATE

_LEDGER_COLUMNS = (
    "code, slot, type, color, month, place, seq, product, color_name, hex, img, "
    "site, sheet, edition, issued_at, issued_by, checks, last_check, "
    "owner_email, owner_first, owner_last, owner_dob, registered_at"
)

ROLES = ("admin", "config", "production", "ledger", "none")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- миграции схемы ----------
# Правило: только добавление таблиц/колонок. Изменение или удаление
# существующих — повод для MAJOR-версии и отдельного плана перехода.

def _m1_base(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            key TEXT NOT NULL,
            catalog TEXT NOT NULL,
            certificate TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
    db.execute("""
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


def _m2_auth_and_logs(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        )""")
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            google_sub TEXT UNIQUE,
            name TEXT,
            picture TEXT,
            role TEXT NOT NULL DEFAULT 'none',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )""")
    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            ip TEXT
        )""")
    db.execute("""
        CREATE TABLE IF NOT EXISTS verify_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            code TEXT NOT NULL,
            status TEXT NOT NULL,
            ip TEXT
        )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_verify_log_at ON verify_log(at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_verify_log_code ON verify_log(code)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT
        )""")
    cols = {r[1] for r in db.execute("PRAGMA table_info(ledger)")}
    if "issued_by" not in cols:
        db.execute("ALTER TABLE ledger ADD COLUMN issued_by TEXT")


MIGRATIONS: list[tuple[int, callable]] = [(1, _m1_base), (2, _m2_auth_and_logs)]
SCHEMA_VERSION = MIGRATIONS[-1][0]


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
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r["version"] for r in self._db.execute("SELECT version FROM schema_migrations")}
            if not done:
                # База, созданная сборкой 1.x, существовала до появления
                # schema_migrations — засчитываем ей миграцию 1 как применённую.
                has_v1 = self._db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'"
                ).fetchone()
                if has_v1:
                    self._db.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)", (_now(),)
                    )
                    done.add(1)
            for version, apply in MIGRATIONS:
                if version in done:
                    continue
                apply(self._db)
                self._db.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, _now())
                )

    def schema_version(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        return row["v"] or 0

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

    def app_config_get(self, k: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT v FROM app_config WHERE k = ?", (k,)).fetchone()
        return row["v"] if row else None

    def app_config_set(self, k: str, v: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO app_config (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                (k, v),
            )

    # ---------- ledger ----------

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        r = {
            "code": row["code"], "slot": row["slot"],
            "type": row["type"], "color": row["color"], "month": row["month"],
            "place": row["place"], "seq": row["seq"],
            "product": row["product"], "colorName": row["color_name"], "hex": row["hex"],
            "img": row["img"], "site": row["site"], "sheet": row["sheet"], "edition": row["edition"],
            "issuedAt": row["issued_at"], "issuedBy": row["issued_by"],
            "checks": row["checks"], "lastCheck": row["last_check"],
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
                               product, color_name, hex, img, site, sheet, edition,
                               issued_at, issued_by, checks)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (rec["code"], rec["slot"], rec["type"], rec["color"], rec["month"],
                         rec["place"], rec["seq"], rec["product"], rec["colorName"], rec["hex"],
                         rec["img"], rec["site"], rec["sheet"], rec["edition"],
                         _now(), rec.get("issuedBy")),
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

    def bump_checks(self, code: str) -> int | None:
        """None — запись успели удалить между поиском и инкрементом."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE ledger SET checks = checks + 1, last_check = ? WHERE code = ?",
                (_now(), code),
            )
            row = self._db.execute("SELECT checks FROM ledger WHERE code = ?", (code,)).fetchone()
            return row["checks"] if row else None

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

    # ---------- пользователи и сессии ----------

    @staticmethod
    def _user(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "email": row["email"], "name": row["name"], "picture": row["picture"],
            "role": row["role"], "active": bool(row["active"]),
            "createdAt": row["created_at"], "lastLoginAt": row["last_login_at"],
        }

    def upsert_google_user(self, sub: str, email: str, name: str, picture: str,
                           admin_emails: set[str]) -> dict:
        """Создаёт или обновляет пользователя при входе через Google.

        Email из allowlist администраторов получает роль admin при каждом
        входе (bootstrap и страховка от случайного самопонижения).
        """
        email = email.lower()
        is_admin = email in admin_emails
        with self._lock, self._db:
            row_email = self._db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            row_sub = self._db.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
            if row_email and row_sub and row_email["id"] != row_sub["id"]:
                # почта Google-аккаунта сменилась на адрес другой учётки:
                # идентичность персонала — это email, поэтому sub переезжает
                # к учётке с этим адресом, а со старой снимается
                self._db.execute("UPDATE users SET google_sub = NULL WHERE id = ?", (row_sub["id"],))
                row_sub = None
            row = row_email or row_sub
            if row:
                role = "admin" if is_admin else row["role"]
                self._db.execute(
                    """UPDATE users SET google_sub = ?, email = ?, name = ?, picture = ?,
                           role = ?, last_login_at = ? WHERE id = ?""",
                    (sub, email, name, picture, role, _now(), row["id"]),
                )
                row = self._db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            else:
                self._db.execute(
                    """INSERT INTO users (email, google_sub, name, picture, role, active, created_at, last_login_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (email, sub, name, picture, "admin" if is_admin else "none", _now(), _now()),
                )
                row = self._db.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
        return self._user(row)

    def list_users(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return [self._user(r) for r in rows]

    def get_user(self, user_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user(row) if row else None

    def update_user(self, user_id: int, role: str | None = None, active: bool | None = None) -> bool:
        with self._lock, self._db:
            if role is not None:
                self._db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            if active is not None:
                self._db.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
                if not active:  # деактивация сразу гасит открытые сессии
                    self._db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            return self._db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is not None

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_session(self, user_id: int, ip: str, ttl_hours: int = 12) -> str:
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)",
                (self._token_hash(token), user_id, _now(), expires, ip),
            )
            self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
        return token

    def session_user(self, token: str) -> dict | None:
        """Пользователь по токену сессии: не истёк, учётка активна."""
        if not token:
            return None
        with self._lock:
            row = self._db.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at >= ? AND u.active = 1""",
                (self._token_hash(token), _now()),
            ).fetchone()
        return self._user(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),))

    # ---------- журналы проверок и действий ----------

    def log_verify(self, code: str, status: str, ip: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO verify_log (at, code, status, ip) VALUES (?, ?, ?, ?)",
                (_now(), code, status, ip),
            )

    def recent_verifies(self, limit: int = 200, status: str | None = None) -> list[dict]:
        q = "SELECT at, code, status, ip FROM verify_log"
        args: tuple = ()
        if status:
            q += " WHERE status = ?"
            args = (status,)
        q += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(q, args + (limit,)).fetchall()
        return [dict(r) for r in rows]

    def verify_stats_since(self, days: int = 7) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            rows = self._db.execute(
                "SELECT status, COUNT(*) AS n FROM verify_log WHERE at >= ? GROUP BY status", (since,)
            ).fetchall()
        out = {"issued": 0, "not_issued": 0, "mismatch": 0, "malformed": 0}
        for r in rows:
            out[r["status"]] = r["n"]
        return out

    def prune_verify_log(self, days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock, self._db:
            return self._db.execute("DELETE FROM verify_log WHERE at < ?", (cutoff,)).rowcount

    def audit(self, actor: str, action: str, details: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO audit_log (at, actor, action, details) VALUES (?, ?, ?, ?)",
                (_now(), actor, action, details),
            )

    def recent_audit(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT at, actor, action, details FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- статистика ----------

    def stats(self) -> dict:
        with self._lock:
            issued = self._db.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()["n"]
            registered = self._db.execute(
                "SELECT COUNT(*) AS n FROM ledger WHERE registered_at IS NOT NULL"
            ).fetchone()["n"]
            checks = self._db.execute("SELECT COALESCE(SUM(checks), 0) AS n FROM ledger").fetchone()["n"]
            by_product = self._db.execute(
                """SELECT product, COUNT(*) AS issued,
                          SUM(CASE WHEN registered_at IS NOT NULL THEN 1 ELSE 0 END) AS registered
                   FROM ledger GROUP BY product ORDER BY issued DESC"""
            ).fetchall()
        return {
            "issued": issued, "registered": registered, "checksTotal": checks,
            "byProduct": [dict(r) for r in by_product],
        }
