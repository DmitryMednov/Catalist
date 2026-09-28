"""v2.3: три страницы (/, /factory, /admin), сертификат, партия запуска."""

import os

from fastapi.testclient import TestClient

from app.main import app, store
from app import serials
from app.catalog_seed import SEED_CATALOG

ADMIN = {"X-Pin": "9999"}
PROD = {"X-Pin": "2222"}

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _client():
    return TestClient(app)


def _issue(c, seq, type_=0, color=0, place=0, month=30):
    r = c.post("/api/issue/confirm",
               json={"type": type_, "color": color, "month": month, "place": place, "seq": seq},
               headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["code"]


# ---------- три ссылки ----------

def test_pages_split_into_three_links():
    c = _client()
    home = c.get("/").text
    factory = c.get("/factory").text
    # клиентская страница: только проверка, без выдачи и журнала
    assert 'id="check-input"' in home
    assert 'id="gen-app"' not in home and 'id="journal-app"' not in home
    # страница производства: выдача + журнал + печать сертификата, без формы проверки
    assert 'id="gen-app"' in factory and 'id="journal-app"' in factory
    assert 'id="gen-cert"' in factory and "cert.js" in factory
    assert 'id="check-input"' not in factory
    # /factory и /cert зарезервированы и не считаются серийными номерами
    assert c.get("/admin").status_code == 200
    assert c.get("/cert").status_code == 404


def test_catalog_seed_matches_launch_lineup():
    cat = {t["name"]: t for t in SEED_CATALOG["types"]}
    colors = [c["name"] for c in cat["Balloon Cat"]["colors"]]
    assert colors == ["Purple Chrome", "Burgundy Chrome", "Gold", "Matte Black", "Crystal White"]
    assert "Matte white" not in colors
    # форматы бумаги по требованию заказчика: кот A5, памятник A7, маленький A8
    assert cat["Balloon Cat"]["sheet"] == "a5"
    assert cat["Guardian of Cyprus"]["sheet"] == "a7"
    assert cat["Guardian of Cyprus S"]["sheet"] == "a8"
    # у каждого цвета есть фотография, и файл действительно лежит в web/
    for t in SEED_CATALOG["types"]:
        for col in t["colors"]:
            img = col["img"]
            assert img and img.startswith("/static/products/")
            path = os.path.join(WEB_DIR, img.removeprefix("/static/"))
            assert os.path.isfile(path), f"нет файла {path}"


def test_verify_shows_photo_in_right_colour():
    c = _client()
    code = _issue(c, seq=901, type_=0, color=4)  # Crystal White
    r = c.post("/api/verify", json={"code": code}).json()
    assert r["status"] == "issued"
    assert r["img"] == "/static/products/balloon-cat-crystal.jpg"
    assert r["color"] == "Crystal White"


# ---------- сертификат ----------

def test_cert_api_payload_and_roles():
    c = _client()
    code = _issue(c, seq=902, type_=1, color=0, place=1)  # Guardian of Cyprus, Cyprus
    r = c.get(f"/api/cert/{code}", headers=PROD)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["product"] == "Guardian of Cyprus" and d["sheet"] == "a7"
    assert d["seq"] == 902 and d["edition"] == 500
    assert d["img"] == "/static/products/guardian.jpg"
    assert d["verifyUrl"] == f"http://testserver/{code}"
    assert d["qrSvg"].lstrip().startswith("<?xml") or d["qrSvg"].lstrip().startswith("<svg")
    assert "<svg" in d["qrSvg"]
    # без авторизации закрыто; чужой код — 404; кривой код нормализуется
    assert TestClient(app).get(f"/api/cert/{code}").status_code == 401
    assert c.get("/api/cert/AAAAAAAA", headers=ADMIN).status_code == 404
    low = c.get(f"/api/cert/{code.lower()}", headers=ADMIN)
    assert low.status_code == 200 and low.json()["code"] == code


def test_cert_api_closed_for_config_role():
    # роль config каталог видит, но журнал и сертификаты — нет
    from urllib.parse import parse_qs, urlparse
    from app.main import auth as auth_mgr
    c = _client()
    code = _issue(c, seq=903)
    orig = auth_mgr._exchange_code
    auth_mgr._exchange_code = lambda _code: {
        "sub": "cfg-1", "email": "cfg@example.com", "email_verified": True,
        "name": "Cfg Only", "picture": ""}
    try:
        r = c.get("/auth/google?mode=staff&next=/factory", follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        r = c.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
        assert r.status_code == 302
    finally:
        auth_mgr._exchange_code = orig
    uid = next(u["id"] for u in store.list_users() if u["email"] == "cfg@example.com")
    store.update_user(uid, role="config", active=True)
    r = c.get(f"/api/cert/{code}")  # cookie сессии уже в клиенте, PIN не передаём
    assert r.status_code == 403


# ---------- партия запуска (seed_batch) ----------

def test_seed_batch_issues_launch_lineup(tmp_path, monkeypatch, capsys):
    from app import seed_batch
    monkeypatch.setenv("MERCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MERCH_PUBLIC_URL", "https://code.catalist.world")
    monkeypatch.setattr("sys.argv", ["seed_batch", "--yes"])
    seed_batch.main()
    out = capsys.readouterr().out
    assert "Выпущено 45 кодов" in out

    from app.storage import Storage
    s = Storage(str(tmp_path))
    recs = s.all_records()
    assert len(recs) == 45
    by_product = {}
    for r in recs:
        by_product.setdefault((r["product"], r["colorName"]), []).append(r)
        # каждый код обязан проверяться тем же ключом
        dec = serials.decode_serial(r["code"], s.key)
        assert dec.ok and serials.slot_of(dec.fields) == r["slot"]
        assert r["issuedBy"] == "seed-batch"
    assert len(by_product[("Balloon Cat", "Crystal White")]) == 5
    assert len(by_product[("Guardian of Cyprus", "Grey")]) == 10
    assert len(by_product[("Guardian of Cyprus S", "Grey")]) == 10
    assert all(len(v) == 5 for (p, _), v in by_product.items() if p == "Balloon Cat")
    guardian = by_product[("Guardian of Cyprus", "Grey")][0]
    assert guardian["site"] == "Cyprus" and guardian["sheet"] == "a7"

    listing = (tmp_path / "issued-codes.txt").read_text(encoding="utf-8")
    assert listing.count("№") == 45
    for r in recs:
        assert r["code"] in listing

    # повторный запуск с --no-reset не создаёт дублей
    monkeypatch.setattr("sys.argv", ["seed_batch", "--yes", "--no-reset"])
    seed_batch.main()
    assert len(Storage(str(tmp_path)).all_records()) == 45


def test_seed_batch_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    from app import seed_batch
    monkeypatch.setenv("MERCH_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["seed_batch"])
    seed_batch.main()
    out = capsys.readouterr().out
    assert "--yes" in out
    from app.storage import Storage
    assert Storage(str(tmp_path)).count_records() == 0


def test_reset_business_data_clears_test_records():
    c = _client()
    code = _issue(c, seq=904)
    c.post("/api/register", json={
        "code": code, "firstName": "Test", "lastName": "Reset",
        "dob": "1990-01-01", "email": "reset@example.com"})
    assert store.count_records() > 0
    counts = store.reset_business_data()
    assert counts["ledger"] > 0 and counts["discounts"] >= 1 and counts["buyers"] >= 1
    assert store.count_records() == 0
    assert store.list_discounts() == []
