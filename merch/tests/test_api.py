"""API-сценарии: generate → save → verify → register, роли, удаление."""

from fastapi.testclient import TestClient

from app.main import app, store

client = TestClient(app)
PROD = {"X-Pin": "2222"}
ADMIN = {"X-Pin": "9999"}

REQ = {"type": 0, "color": 2, "month": 7, "place": 0, "seq": 77}


def _issue(seq=77, **over):
    body = {**REQ, "seq": seq, **over}
    r = client.post("/api/issue/confirm", json=body, headers=PROD)
    assert r.status_code == 200, r.text
    return r.json()["code"]


def test_status_public():
    r = client.get("/api/status").json()
    assert r["ok"] and r["provisioned"]
    assert len(r["keyFingerprint"]) == 9


def test_staff_requires_pin():
    assert client.get("/api/catalog").status_code == 401
    assert client.post("/api/issue/preview", json=REQ).status_code == 401
    assert client.get("/api/ledger").status_code == 401


def test_catalog_roles():
    r = client.get("/api/catalog", headers=PROD).json()
    assert r["ok"] and r["types"] and r["places"]
    assert "catalog" not in r  # полный каталог — только администратору
    r = client.get("/api/catalog", headers=ADMIN).json()
    assert "catalog" in r


def test_preview_does_not_burn_slot():
    before = store.count_records()
    for _ in range(3):
        r = client.post("/api/issue/preview", json={**REQ, "seq": 500}, headers=PROD)
        assert r.status_code == 200 and r.json()["ok"]
    assert store.count_records() == before  # generate ничего не записывает


def test_confirm_writes_once_and_slot_is_unique():
    code = _issue(seq=101)
    r = client.post("/api/issue/confirm", json={**REQ, "seq": 101}, headers=PROD)
    assert r.status_code == 409
    assert r.json()["code"] == code  # подсказывает, каким кодом занят слот
    r = client.post("/api/issue/preview", json={**REQ, "seq": 101}, headers=PROD)
    assert r.status_code == 409


def test_expected_code_guard():
    r = client.post("/api/issue/confirm", json={**REQ, "seq": 102, "expectedCode": "AAAAAAAA"}, headers=PROD)
    assert r.status_code == 409
    assert "generate again" in r.json()["error"]


def test_issue_validation():
    bad = client.post("/api/issue/confirm", json={**REQ, "place": 1}, headers=PROD)
    assert bad.status_code == 422  # Balloon Cat делается только в Dubai (site 0)
    bad = client.post("/api/issue/confirm", json={**REQ, "seq": 4096}, headers=PROD)
    assert bad.status_code == 422
    bad = client.post("/api/issue/confirm", json={**REQ, "type": 30}, headers=PROD)
    assert bad.status_code == 422


def test_next_seq_skips_used():
    _issue(seq=1, month=20)
    _issue(seq=2, month=20)
    r = client.get("/api/issue/next-seq", params={**{k: REQ[k] for k in ("type", "color", "place")}, "month": 20}, headers=PROD).json()
    assert r["seq"] == 3 and r["used"] == 2


def test_verify_full_flow():
    code = _issue(seq=103)
    r = client.post("/api/verify", json={"code": code}).json()
    assert r["ok"] and r["status"] == "issued"
    assert r["product"] == "Balloon Cat" and r["seq"] == 103 and r["edition"] == 500
    assert r["monthLabel"] == "Aug 2026" and r["site"] == "Dubai"
    assert r["checks"] == 1 and not r["registered"]
    r2 = client.post("/api/verify", json={"code": code.lower()}).json()
    assert r2["checks"] == 2  # нормализация регистра + счётчик проверок


def test_verify_not_issued_and_malformed():
    r = client.post("/api/verify", json={"code": "AAAAAAAA"}).json()
    assert r["status"] in ("malformed", "not_issued")
    r = client.post("/api/verify", json={"code": "ABC"}).json()
    assert r["status"] == "malformed" and r["reason"] == "length"


def test_verify_mismatch_after_foreign_record():
    # запись есть, но расшифровка не сходится со слотом (например, сменили ключ)
    code = _issue(seq=104)
    with store._lock, store._db:
        store._db.execute("UPDATE ledger SET slot = '9-9-9-9-9' WHERE code = ?", (code,))
    r = client.post("/api/verify", json={"code": code}).json()
    assert r["status"] == "mismatch"


def test_register_once():
    code = _issue(seq=105)
    owner = {"code": code, "firstName": "Ada", "lastName": "Lovelace", "dob": "1990-12-10", "email": "ada@example.com"}
    assert client.post("/api/register", json={**owner, "email": "bad"}).status_code == 422
    assert client.post("/api/register", json={**owner, "dob": "10.12.1990"}).status_code == 422
    r = client.post("/api/register", json=owner)
    assert r.status_code == 200 and r.json()["owner"]["firstName"] == "Ada"
    assert client.post("/api/register", json=owner).status_code == 409  # один раз на номер
    v = client.post("/api/verify", json={"code": code}).json()
    assert v["registered"] and v["owner"] == {"firstName": "Ada", "lastName": "Lovelace"}
    led = client.get("/api/ledger", headers=PROD).json()["records"]
    rec = next(x for x in led if x["code"] == code)
    assert rec["owner"] == {"firstName": "Ada", "lastName": "Lovelace"}  # email наружу не отдаём


def test_delete_admin_only_and_frees_slot():
    code = _issue(seq=106)
    assert client.delete(f"/api/ledger/{code}", headers=PROD).status_code == 401
    assert client.delete(f"/api/ledger/{code}", headers=ADMIN).status_code == 200
    assert client.post("/api/verify", json={"code": code}).json()["status"] == "not_issued"
    code2 = _issue(seq=106)  # слот освободился — комбинация выдана заново тем же кодом
    assert code2 == code


def test_clear_requires_confirm():
    assert client.delete("/api/ledger", headers=ADMIN).status_code == 400


def test_deep_link_serves_check_page():
    r = client.get("/A1B2C3D4")
    assert r.status_code == 200 and "Check authenticity" in r.text
    assert client.get("/api").status_code == 404
    r = client.get("/")
    assert r.status_code == 200 and "Catalist" in r.text


def test_rate_limiter_unit():
    from app.security import RateLimiter
    rl = RateLimiter()
    allowed = sum(rl.allow("1.2.3.4", "verify", 5) for _ in range(10))
    assert allowed == 5
    assert rl.allow("5.6.7.8", "verify", 5)  # другой IP не задет
