"""v2.1: скидка за регистрацию, письма, личный кабинет покупателя, QR."""

import threading

from fastapi.testclient import TestClient

from app.main import app, mailer, store

ADMIN = {"X-Pin": "9999"}
PROD = {"X-Pin": "2222"}


def _client():
    return TestClient(app)


def _issue(c, seq, month=30):
    r = c.post("/api/issue/confirm",
               json={"type": 0, "color": 0, "month": month, "place": 0, "seq": seq},
               headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["code"]


def _register(c, code, email, first="Nia", last="Kotova"):
    return c.post("/api/register", json={
        "code": code, "firstName": first, "lastName": last,
        "dob": "1995-05-20", "email": email,
    })


class _MailTrap:
    """Включает «SMTP» и перехватывает доставку; ждём фоновый поток по Event."""

    def __init__(self):
        self.messages = []
        self.event = threading.Event()

    def __enter__(self):
        self._saved = (mailer.host, mailer.sender, mailer._deliver)
        mailer.host, mailer.sender = "smtp.test", "noreply@test"

        def fake_deliver(msg):
            self.messages.append(msg)
            self.event.set()
        mailer._deliver = fake_deliver
        return self

    def __exit__(self, *a):
        mailer.host, mailer.sender, mailer._deliver = self._saved

    def wait(self, n=1, timeout=3):
        assert self.event.wait(timeout), "письмо не ушло из фонового потока"
        return self.messages


def test_register_grants_discount_and_sets_cabinet_cookie():
    c = _client()
    code = _issue(c, seq=10)
    with _MailTrap() as trap:
        r = _register(c, code, "nia@example.com")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["discount"]["percent"] == 10
        assert body["discount"]["status"] == "active"
        assert body["discount"]["token"].startswith("CAT-") and len(body["discount"]["token"]) == 13
        assert body["cabinetUrl"] == "/my" and body["emailQueued"] is True
        assert "merch_buyer" in r.headers.get("set-cookie", "")
        msgs = trap.wait()
    # письмо: скидка + magic-ссылка в кабинет
    msg = msgs[0]
    assert msg["To"] == "nia@example.com"
    assert "10%" in msg["Subject"]
    text = msg.get_body(("plain",)).get_content()
    assert body["discount"]["token"] in text and "/my?k=" in text
    # флаг отправки зафиксирован в БД
    d = store.discount_by_token(body["discount"]["token"])
    assert d["emailSent"] is True and d["code"] == code and d["email"] == "nia@example.com"


def test_cabinet_lists_figurines_with_discounts():
    c = _client()
    code = _issue(c, seq=11)
    _register(c, code, "cab@example.com")  # cookie кабинета осталась в клиенте
    r = c.get("/api/my")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == "cab@example.com"
    fig = next(f for f in data["figurines"] if f["code"] == code)
    assert fig["product"] == "Balloon Cat" and fig["discount"]["percent"] == 10
    assert fig["registeredAt"] and fig["monthLabel"]
    # без cookie кабинет закрыт
    assert TestClient(app).get("/api/my").status_code == 401


def test_magic_link_signs_in_and_rotates():
    c = _client()
    code = _issue(c, seq=12)
    _register(c, code, "link@example.com")
    token1 = store.issue_buyer_token("link@example.com")
    fresh = TestClient(app)
    r = fresh.get(f"/my?k={token1}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/my"
    assert "merch_buyer" in r.headers.get("set-cookie", "")
    assert fresh.get("/api/my").json()["email"] == "link@example.com"
    # ротация: новая ссылка гасит старую
    token2 = store.issue_buyer_token("link@example.com")
    assert store.buyer_email_by_token(token1) is None
    assert store.buyer_email_by_token(token2) == "link@example.com"


def test_magic_link_email_flow_is_uniform():
    c = _client()
    code = _issue(c, seq=13)
    _register(c, code, "known@example.com")
    with _MailTrap() as trap:
        r = c.post("/api/my/link", json={"email": "known@example.com"})
        assert r.status_code == 200 and "on its way" in r.json()["message"]
        msgs = trap.wait()
        assert "/my?k=" in msgs[0].get_body(("plain",)).get_content()
    with _MailTrap() as trap2:
        r = c.post("/api/my/link", json={"email": "stranger@example.com"})
        # ответ одинаковый, письма нет — email-ы не перебрать
        assert r.status_code == 200 and "on its way" in r.json()["message"]
        assert not trap2.event.wait(0.4) and trap2.messages == []


def test_discount_qr_only_for_owner():
    c = _client()
    code = _issue(c, seq=14)
    token = _register(c, code, "qr@example.com").json()["discount"]["token"]
    r = c.get(f"/api/my/qr/{token}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in r.content
    assert TestClient(app).get(f"/api/my/qr/{token}").status_code == 401  # чужой браузер
    # владелец другого кабинета не видит чужой QR
    c2 = _client()
    code2 = _issue(c2, seq=15)
    _register(c2, code2, "other@example.com")
    assert c2.get(f"/api/my/qr/{token}").status_code == 404


def test_public_discount_check_and_admin_mark_used():
    c = _client()
    code = _issue(c, seq=16)
    token = _register(c, code, "cashier@example.com", first="Vera").json()["discount"]["token"]
    pub = TestClient(app)
    r = pub.get(f"/api/discount/{token}").json()
    assert r["status"] == "active" and r["percent"] == 10
    assert r["product"] == "Balloon Cat" and r["ownerFirstName"] == "Vera"
    # кассир открывает страницу /d/<токен>
    page = pub.get(f"/d/{token}")
    assert page.status_code == 200
    # админ отмечает использование
    assert pub.patch(f"/api/admin/discounts/{token}", json={"status": "used"}, headers=ADMIN).status_code == 200
    r = pub.get(f"/api/discount/{token.lower()}").json()  # регистр не важен
    assert r["status"] == "used" and r["usedAt"]
    assert pub.get("/api/discount/CAT-0000-0000").status_code == 404
    # смена статуса — только admin
    assert pub.patch(f"/api/admin/discounts/{token}", json={"status": "active"}, headers=PROD).status_code == 403


def test_admin_discount_list():
    c = _client()
    r = c.get("/api/admin/discounts", headers=ADMIN).json()
    assert r["ok"] and len(r["discounts"]) >= 1
    d = r["discounts"][0]
    assert {"token", "code", "email", "percent", "status", "product"} <= set(d)
    assert c.get("/api/admin/discounts", headers=PROD).status_code == 403


def test_discount_survives_reregistration_cycle():
    """Удаление записи и повторная выдача не плодят вторую скидку на код."""
    c = _client()
    code = _issue(c, seq=17)
    t1 = _register(c, code, "cycle@example.com").json()["discount"]["token"]
    assert c.delete(f"/api/ledger/{code}", headers=ADMIN).status_code == 200
    code2 = _issue(c, seq=17)
    assert code2 == code
    r = _register(c, code, "cycle@example.com")
    assert r.status_code == 200
    assert r.json()["discount"]["token"] == t1  # та же скидка, дубля нет


def test_my_page_served_and_deep_link_reserved():
    pub = TestClient(app)
    assert pub.get("/my").status_code == 200
    from app.version import APP_VERSION
    assert pub.get("/api/status").json()["version"] == APP_VERSION


def test_mailer_prefers_brevo_api_when_key_set():
    calls, evt = [], threading.Event()
    saved = (mailer.brevo_key, mailer.host, mailer.sender, mailer._deliver_api)
    mailer.brevo_key, mailer.host, mailer.sender = "xkeysib-test", "", "noreply@test"
    mailer._deliver_api = lambda msg: (calls.append(msg), evt.set())
    try:
        ok = mailer.send_async(mailer.signin_email(to="a@b.co", cabinet_url="http://x/my?k=1"))
        assert ok and evt.wait(2)
        assert str(calls[0]["To"]) == "a@b.co"
    finally:
        mailer.brevo_key, mailer.host, mailer.sender, mailer._deliver_api = saved


def test_brevo_api_payload_shape():
    from app import mailer as mailer_mod
    m = mailer_mod.Mailer()
    m.brevo_key, m.sender = "k-123", "s@catalist.world"
    captured = {}

    class _Resp:
        status_code = 201
        text = ""

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _Resp()

    saved_post = mailer_mod.httpx.post
    mailer_mod.httpx.post = fake_post
    try:
        m._deliver_api(m.signin_email(to="buyer@x.com", cabinet_url="http://x/my?k=t"))
    finally:
        mailer_mod.httpx.post = saved_post
    assert captured["url"].startswith("https://api.brevo.com/")
    assert captured["headers"]["api-key"] == "k-123"
    j = captured["json"]
    assert j["sender"] == {"name": "Catalist", "email": "s@catalist.world"}
    assert j["to"] == [{"email": "buyer@x.com"}]
    assert "http://x/my?k=t" in j["textContent"] and "http://x/my?k=t" in j["htmlContent"]
