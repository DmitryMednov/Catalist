"""v2: миграции схемы, ролевая модель, Google OAuth, журналы проверок и действий."""

import os
import sqlite3
import tempfile
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.main import app, auth as auth_mgr, store
from app.storage import SCHEMA_VERSION, Storage

ADMIN = {"X-Pin": "9999"}
PROD = {"X-Pin": "2222"}


def _client():
    return TestClient(app)


def _google_login(client, profile, mode="staff", next_path="/admin"):
    """Проходит OAuth-флоу с подменённым обменом кода на профиль."""
    orig = auth_mgr._exchange_code
    auth_mgr._exchange_code = lambda code: profile
    try:
        r = client.get(f"/auth/google?mode={mode}&next={next_path}", follow_redirects=False)
        assert r.status_code == 302
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        r = client.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert r.status_code == 302
        return r
    finally:
        auth_mgr._exchange_code = orig


def _staff_profile(email, first="Ann", last="Smith", sub=None):
    return {"sub": sub or "sub-" + email, "email": email, "email_verified": True,
            "name": f"{first} {last}", "given_name": first, "family_name": last, "picture": ""}


# ---------- миграции ----------

def test_v1_database_upgrades_in_place():
    d = tempfile.mkdtemp(prefix="merch-migrate-")
    db = sqlite3.connect(os.path.join(d, "merch.db"))
    # схема сборки 1.x: только config + ledger, без schema_migrations
    db.execute("""CREATE TABLE config (id INTEGER PRIMARY KEY CHECK (id = 1), key TEXT NOT NULL,
                  catalog TEXT NOT NULL, certificate TEXT NOT NULL, created_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE ledger (code TEXT PRIMARY KEY, slot TEXT NOT NULL UNIQUE,
                  type INTEGER NOT NULL, color INTEGER NOT NULL, month INTEGER NOT NULL,
                  place INTEGER NOT NULL, seq INTEGER NOT NULL, product TEXT NOT NULL,
                  color_name TEXT NOT NULL, hex TEXT, img TEXT, site TEXT NOT NULL,
                  sheet TEXT NOT NULL DEFAULT 'a5', edition INTEGER, issued_at TEXT NOT NULL,
                  checks INTEGER NOT NULL DEFAULT 0, last_check TEXT, owner_email TEXT,
                  owner_first TEXT, owner_last TEXT, owner_dob TEXT, registered_at TEXT)""")
    db.execute("INSERT INTO config VALUES (1, '0123456789abcdef0123456789abcdef', '{\"types\":[],\"places\":[]}', '{}', 'x')")
    db.execute("""INSERT INTO ledger (code, slot, type, color, month, place, seq, product, color_name,
                  site, issued_at) VALUES ('AAAA1111', '0-0-0-0-1', 0, 0, 0, 0, 1, 'P', 'C', 'S', 'x')""")
    db.commit()
    db.close()

    st = Storage(d)  # миграции применяются в конструкторе
    assert st.schema_version() == SCHEMA_VERSION
    rec = st.find_by_code("AAAA1111")
    assert rec and rec["product"] == "P" and rec["issuedBy"] is None  # данные 1.x целы
    assert st.list_users() == []
    st.audit("t", "test", "")
    assert st.recent_audit(1)[0]["action"] == "test"


def test_fresh_database_at_latest_schema():
    assert store.schema_version() == SCHEMA_VERSION


# ---------- вход через Google ----------

def test_google_login_bootstrap_admin():
    c = _client()
    r = _google_login(c, _staff_profile("boss@example.com"))
    assert r.headers["location"] == "/admin"
    assert "merch_session" in r.headers.get("set-cookie", "")
    me = c.get("/api/me").json()["auth"]
    assert me["kind"] == "user" and me["role"] == "admin" and me["email"] == "boss@example.com"
    st = c.get("/api/status").json()
    assert st["role"] == "admin" and st["googleAuth"] is True


def test_google_login_new_user_gets_none_role():
    c = _client()
    _google_login(c, _staff_profile("worker@example.com"))
    me = c.get("/api/me").json()["auth"]
    assert me["role"] == "none"
    r = c.get("/api/catalog")
    assert r.status_code == 403  # роль ещё не назначена
    assert "no role yet" in r.json()["error"]


def test_google_login_rejects_unverified_email():
    c = _client()
    prof = {**_staff_profile("fake@example.com"), "email_verified": False}
    r = _google_login(c, prof)
    assert "auth_error" in r.headers["location"]
    assert c.get("/api/me").json()["auth"] is None


def test_buyer_prefill_flow():
    c = _client()
    r = _google_login(c, _staff_profile("buyer@example.com", first="Iva", last="Petrova"),
                      mode="buyer", next_path="/AAAA1111")
    assert r.headers["location"] == "/AAAA1111"
    assert "merch_prefill" in r.headers.get("set-cookie", "")
    pf = c.get("/api/me/prefill").json()["prefill"]
    assert pf == {"firstName": "Iva", "lastName": "Petrova", "email": "buyer@example.com"}
    # staff-учётка для покупателя не создаётся
    assert all(u["email"] != "buyer@example.com" for u in store.list_users())


def test_logout_clears_session():
    c = _client()
    _google_login(c, _staff_profile("boss@example.com"))
    assert c.get("/api/me").json()["auth"] is not None
    c.post("/api/auth/logout")
    assert c.get("/api/me").json()["auth"] is None


# ---------- ролевая модель ----------

def _user_with_role(c, email, role):
    _google_login(c, _staff_profile(email))
    u = next(u for u in store.list_users() if u["email"] == email)
    store.update_user(u["id"], role=role)
    return u


def test_config_role_edits_catalog_but_cannot_issue():
    c = _client()
    _user_with_role(c, "cfg@example.com", "config")
    cat = c.get("/api/catalog").json()
    assert "catalog" in cat  # config видит полный каталог
    r = c.put("/api/catalog", json={"catalog": cat["catalog"]})
    assert r.status_code == 200
    r = c.post("/api/issue/preview", json={"type": 0, "color": 0, "month": 0, "place": 0, "seq": 1})
    assert r.status_code == 403
    assert c.get("/api/ledger").status_code == 403


def test_ledger_role_reads_and_exports_only():
    c = _client()
    _user_with_role(c, "audit@example.com", "ledger")
    assert c.get("/api/ledger").status_code == 200
    csv_r = c.get("/api/ledger/export.csv")
    assert csv_r.status_code == 200 and csv_r.text.startswith("code,product")
    assert c.post("/api/issue/preview", json={"type": 0, "color": 0, "month": 0, "place": 0, "seq": 1}).status_code == 403
    assert c.put("/api/catalog", json={"catalog": {"types": [], "places": []}}).status_code == 403
    assert c.delete("/api/ledger/XXXXXXXX").status_code == 403  # удаление — только admin


def test_pin_roles_still_work():
    c = _client()
    assert c.get("/api/ledger", headers=PROD).status_code == 200
    assert c.get("/api/admin/stats", headers=PROD).status_code == 403
    assert c.get("/api/admin/stats", headers=ADMIN).status_code == 200


# ---------- администрирование ----------

def test_admin_users_management_and_self_guard():
    c = _client()
    _google_login(c, _staff_profile("boss@example.com"))
    users = c.get("/api/admin/users").json()["users"]
    worker = next(u for u in users if u["email"] == "worker@example.com")
    me = next(u for u in users if u["email"] == "boss@example.com")
    r = c.patch(f"/api/admin/users/{worker['id']}", json={"role": "production"})
    assert r.status_code == 200
    assert store.get_user(worker["id"])["role"] == "production"
    assert c.patch(f"/api/admin/users/{worker['id']}", json={"role": "boss"}).status_code == 400
    assert c.patch(f"/api/admin/users/{me['id']}", json={"role": "ledger"}).status_code == 409
    assert c.patch(f"/api/admin/users/{me['id']}", json={"active": False}).status_code == 409


def test_deactivated_user_loses_session():
    c = _client()
    _google_login(c, _staff_profile("gone@example.com"))
    u = next(u for u in store.list_users() if u["email"] == "gone@example.com")
    store.update_user(u["id"], active=False)
    assert c.get("/api/me").json()["auth"] is None


def test_verify_log_records_all_checks():
    c = _client()
    code = c.post("/api/issue/confirm",
                  json={"type": 0, "color": 1, "month": 3, "place": 0, "seq": 900},
                  headers=ADMIN).json()["code"]
    c.post("/api/verify", json={"code": code})
    c.post("/api/verify", json={"code": "AAAAAAAB"})
    c.post("/api/verify", json={"code": "XYZ"})
    entries = c.get("/api/admin/verify-log?limit=10", headers=ADMIN).json()["entries"]
    statuses = [e["status"] for e in entries[:3]]
    assert "issued" in statuses and "malformed" in statuses
    only_issued = c.get("/api/admin/verify-log?status=issued", headers=ADMIN).json()["entries"]
    assert all(e["status"] == "issued" for e in only_issued)
    assert any(e["code"] == code for e in only_issued)


def test_audit_log_tracks_actions():
    c = _client()
    code = c.post("/api/issue/confirm",
                  json={"type": 0, "color": 1, "month": 3, "place": 0, "seq": 901},
                  headers=ADMIN).json()["code"]
    c.delete(f"/api/ledger/{code}", headers=ADMIN)
    entries = c.get("/api/admin/audit-log?limit=20", headers=ADMIN).json()["entries"]
    actions = [e["action"] for e in entries]
    assert "issue_save" in actions and "ledger_delete" in actions
    save = next(e for e in entries if e["action"] == "issue_save")
    assert save["actor"] == "pin:admin" and code in save["details"]


def test_admin_stats_shape():
    r = _client().get("/api/admin/stats", headers=ADMIN).json()
    assert r["ok"] and set(r["verify7d"]) == {"issued", "not_issued", "mismatch", "malformed"}
    assert isinstance(r["byProduct"], list) and r["dbSchema"] == SCHEMA_VERSION
    assert r["version"].count(".") == 2


def test_issued_by_recorded():
    c = _client()
    code = c.post("/api/issue/confirm",
                  json={"type": 0, "color": 1, "month": 3, "place": 0, "seq": 902},
                  headers=PROD).json()["code"]
    rec = next(x for x in c.get("/api/ledger", headers=PROD).json()["records"] if x["code"] == code)
    assert rec["issuedBy"] == "pin:production"


def test_admin_page_served():
    r = _client().get("/admin")
    assert r.status_code == 200


# ---------- исправления по итогам ревизии ----------

def test_non_ascii_pin_is_401_not_500():
    from app.security import Roles
    assert Roles().role_of("ÿéßü\xff") is None  # не падает TypeError
    c = _client()
    # заголовок с байтами вне ASCII (Starlette декодирует их как latin-1)
    r = c.get("/api/catalog", headers={b"x-pin": "ÿéßü".encode("latin-1")})
    assert r.status_code == 401


def test_catalog_deep_validation_rejects_broken_shapes():
    c = _client()
    ok_place = [{"name": "Dubai", "on": True}]
    cases = [
        {"types": [{"name": "X", "on": True, "colors": ["red"]}], "places": ok_place},
        {"types": [{"name": "X", "on": True, "colors": [{"hex": "#fff"}]}], "places": ok_place},
        {"types": ["x"], "places": ok_place},
        {"types": [], "places": ["Dubai"]},
        {"types": [{"name": "X", "on": True, "colors": [], "site": 5}], "places": ok_place},
    ]
    for cat in cases:
        r = c.put("/api/catalog", json={"catalog": cat}, headers=ADMIN)
        assert r.status_code == 400, f"accepted broken catalog: {cat}"
    # валидный каталог по-прежнему принимается, и GET после этого жив
    good = {"types": [{"name": "X", "on": True, "sheet": "a5", "site": 0, "edition": 10,
                       "colors": [{"name": "Red", "hex": "#f00", "on": True, "img": None}]}],
            "places": ok_place}
    assert c.put("/api/catalog", json={"catalog": good}, headers=ADMIN).status_code == 200
    assert c.get("/api/catalog", headers=ADMIN).status_code == 200
    # возвращаем сид, чтобы не мешать другим тестам
    from app.catalog_seed import SEED_CATALOG
    assert c.put("/api/catalog", json={"catalog": SEED_CATALOG}, headers=ADMIN).status_code == 200


def test_next_seq_exhaustion_returns_409():
    month = 199  # изолированная комбинация
    for s in range(1, 4096):
        assert store.insert_record({
            "code": f"T{month}{s:04d}", "slot": f"0-0-{month}-0-{s}",
            "type": 0, "color": 0, "month": month, "place": 0, "seq": s,
            "product": "P", "colorName": "C", "hex": None, "img": None,
            "site": "S", "sheet": "a5", "edition": None, "issuedBy": None,
        })
    r = _client().get("/api/issue/next-seq",
                      params={"type": 0, "color": 0, "month": month, "place": 0}, headers=PROD)
    assert r.status_code == 409
    assert "taken" in r.json()["error"]


def test_prefill_token_rejected_as_state():
    c = _client()
    prefill = auth_mgr.sign({"firstName": "A", "lastName": "B", "email": "a@b.co"}, 600, "prefill")
    r = c.get(f"/auth/google/callback?code=x&state={prefill}", follow_redirects=False)
    assert r.status_code == 302 and "auth_error" in r.headers["location"]


def test_callback_without_nonce_cookie_is_rejected():
    c = _client()
    r = c.get("/auth/google?mode=staff&next=/admin", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    fresh = _client()  # другой «браузер»: nonce-cookie нет — login CSRF
    orig = auth_mgr._exchange_code
    auth_mgr._exchange_code = lambda code: _staff_profile("boss@example.com")
    try:
        r2 = fresh.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
    finally:
        auth_mgr._exchange_code = orig
    assert r2.status_code == 302 and "auth_error" in r2.headers["location"]
    assert fresh.get("/api/me").json()["auth"] is None


def test_csv_export_escapes_formulas():
    c = _client()
    code = c.post("/api/issue/confirm",
                  json={"type": 0, "color": 3, "month": 5, "place": 0, "seq": 903},
                  headers=ADMIN).json()["code"]
    r = c.post("/api/register", json={
        "code": code, "firstName": "=HYPERLINK(\"https://evil.tld\")", "lastName": "Doe",
        "dob": "1990-01-01", "email": "x@y.co"})
    assert r.status_code == 200
    body = c.get("/api/ledger/export.csv", headers=ADMIN).text
    assert "'=HYPERLINK" in body and "\n=HYPERLINK" not in body


def test_oversized_public_fields_rejected():
    c = _client()
    assert c.post("/api/verify", json={"code": "A" * 100000}).status_code == 422
    assert c.post("/api/register", json={"code": "AAAA1111", "firstName": "x" * 100000,
                                         "lastName": "y", "dob": "1990-01-01",
                                         "email": "a@b.co"}).status_code == 422


def test_google_email_moved_to_existing_account():
    c = _client()
    a = store.upsert_google_user("sub-move-1", "old@example.com", "Old", "", set())
    b = store.upsert_google_user("sub-move-2", "new@example.com", "New", "", set())
    # почта аккаунта sub-move-1 сменилась на адрес существующей учётки B
    merged = store.upsert_google_user("sub-move-1", "new@example.com", "New Name", "", set())
    assert merged["id"] == b["id"]  # идентичность — по email
    old = store.get_user(a["id"])
    assert old is not None  # старая учётка осталась, но без google_sub


def test_bump_checks_after_delete_returns_none():
    code = "ZZQQ0001"
    store.insert_record({"code": code, "slot": "9-9-200-9-9", "type": 9, "color": 9,
                         "month": 200, "place": 9, "seq": 9, "product": "P", "colorName": "C",
                         "hex": None, "img": None, "site": "S", "sheet": "a5",
                         "edition": None, "issuedBy": None})
    store.delete_record(code)
    assert store.bump_checks(code) is None
