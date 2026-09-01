"""HTTP API модуля мерч-кодов Catalist.

Эндпоинты выдачи/проверки повторяют операции api.* прототипа один в один
(см. docs/merch-module.md — таблица соответствия). Семантика сохранена:
generate (preview) ничего не записывает, запись создаёт только save
(confirm); уникальность номера и слота гарантирует БД.

Ролевая модель (полная матрица — в docs/merch-module.md):
  admin      — всё;
  config     — каталог (просмотр и правка);
  production — выдача номеров, каталог (просмотр), журнал (просмотр);
  ledger     — журнал (просмотр) и экспорт CSV;
  публично   — проверка номера и регистрация владельца (с rate limit).
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import segno

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import serials
from .auth import (BUYER_COOKIE, BUYER_TTL_DAYS, PREFILL_COOKIE, SESSION_COOKIE,
                   SESSION_TTL_HOURS, Auth, AuthError, Principal)
from .mailer import Mailer
from .security import RateLimiter, Roles, client_ip
from .storage import ROLES as USER_ROLES
from .storage import Storage
from .version import APP_VERSION

DATA_DIR = os.environ.get("MERCH_DATA_DIR", "data")
PUBLIC_URL = (os.environ.get("MERCH_PUBLIC_URL") or "https://code.catalist.world").rstrip("/")
MAIN_SITE = os.environ.get("MERCH_MAIN_SITE", "https://catalist.world")
# Secure-флаг cookie следует за схемой публичного адреса: на временном
# http-доступе (до DNS) браузер не отбросит cookie кабинета и сессий,
# с переходом на https флаг включится сам.
SECURE_COOKIES = PUBLIC_URL.lower().startswith("https")

VERIFY_PER_MIN = int(os.environ.get("MERCH_VERIFY_PER_MIN", "30"))
REGISTER_PER_MIN = int(os.environ.get("MERCH_REGISTER_PER_MIN", "10"))
ISSUE_PER_MIN = int(os.environ.get("MERCH_ISSUE_PER_MIN", "60"))
VERIFYLOG_DAYS = int(os.environ.get("MERCH_VERIFYLOG_DAYS", "365"))
DISCOUNT_PERCENT = int(os.environ.get("MERCH_DISCOUNT_PERCENT", "10"))

app = FastAPI(title="Catalist merch codes", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    # Разрешаем вызовы публичных эндпоинтов со страниц Tilda (основной сайт),
    # чтобы позже можно было встроить форму проверки прямо на catalist.world.
    allow_origins=[MAIN_SITE, MAIN_SITE.replace("://", "://www.")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

store = Storage(DATA_DIR, os.environ.get("MERCH_SERIAL_KEY") or None)
roles = Roles()
limiter = RateLimiter()
auth = Auth(store, roles, PUBLIC_URL)
mailer = Mailer()
store.prune_verify_log(VERIFYLOG_DAYS)

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _err(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, **extra}, status_code=status)


def _guard(request: Request, *allowed: str) -> tuple[Principal | None, JSONResponse | None]:
    """Пускает admin всегда, остальных — по списку ролей; (principal, ошибка)."""
    if not limiter.allow(client_ip(request), "staff", ISSUE_PER_MIN):
        return None, _err(429, "too many requests")
    p = auth.principal(request)
    if p is None:
        if not roles.configured and not auth.google_configured:
            return None, _err(503, "neither PINs nor Google sign-in are configured on the server")
        return None, _err(401, "unauthorized")
    if p.role == "admin" or p.role in allowed:
        return p, None
    if p.role == "none":
        return None, _err(403, "your account has no role yet — ask the administrator")
    return None, _err(403, "your role does not allow this action")


def _current_month_index() -> int:
    now = datetime.now(timezone.utc)
    return max(0, min(serials.CAP["month"] - 1, (now.year - serials.BASE_YEAR) * 12 + now.month - 1))


def _enabled_catalog(catalog: dict) -> dict:
    """Как enabledCatalog прототипа: только включённое, с исходными индексами."""
    types = []
    for i, t in enumerate(catalog["types"]):
        if not t.get("on"):
            continue
        colors = [{**c, "j": j} for j, c in enumerate(t["colors"]) if c.get("on")]
        types.append({**t, "i": i, "colors": colors})
    places = [{**p, "i": i} for i, p in enumerate(catalog["places"]) if p.get("on")]
    return {"types": types, "places": places}


class IssueReq(BaseModel):
    type: int
    color: int
    month: int
    place: int
    seq: int
    expectedCode: str | None = Field(default=None, max_length=16)


class VerifyReq(BaseModel):
    # длина ограничена: normalize() на мегабайтной строке — лишняя работа CPU
    code: str = Field(max_length=64)


class RegisterReq(BaseModel):
    code: str = Field(max_length=64)
    firstName: str = Field(default="", max_length=80)
    lastName: str = Field(default="", max_length=80)
    dob: str = Field(default="", max_length=10)
    email: str = Field(default="", max_length=254)


class CatalogReq(BaseModel):
    catalog: dict


class UserPatchReq(BaseModel):
    role: str | None = None
    active: bool | None = None


class MyLinkReq(BaseModel):
    email: str = Field(max_length=254)


class DiscountPatchReq(BaseModel):
    status: str


# ---------- статус и профиль ----------

@app.get("/api/status")
async def status(request: Request):
    p = auth.principal(request)
    return {
        "ok": True,
        "provisioned": True,
        "version": APP_VERSION,
        "keyFingerprint": store.key_fingerprint(),
        "baseYear": serials.BASE_YEAR,
        "currentMonth": _current_month_index(),
        "issued": store.count_records(),
        "role": p.role if p else None,
        "googleAuth": auth.google_configured,
        "publicUrl": PUBLIC_URL,
    }


@app.get("/api/me")
async def me(request: Request):
    p = auth.principal(request)
    return {"ok": True, "auth": p.as_dict() if p else None}


@app.get("/api/me/prefill")
async def me_prefill(request: Request):
    """Профиль Google для автозаполнения формы регистрации владельца."""
    return {"ok": True, "prefill": auth.prefill_from(request)}


# ---------- вход через Google ----------

NONCE_COOKIE = "merch_oauth_nonce"


# Оба обработчика — синхронные (def): FastAPI выполняет их в пуле потоков,
# и сетевой обмен с Google не блокирует event loop публичных запросов.
@app.get("/auth/google")
def auth_google(request: Request, mode: str = "staff", next: str = "/admin"):
    try:
        url, nonce = auth.auth_url(mode, next)
    except AuthError as e:
        return _err(503, str(e))
    resp = RedirectResponse(url, status_code=302)
    # nonce привязывает начатый вход к этому браузеру (защита от login CSRF);
    # SameSite=Lax отправляется при top-level GET-редиректе от Google
    resp.set_cookie(NONCE_COOKIE, nonce, max_age=600,
                    httponly=True, secure=SECURE_COOKIES, samesite="lax")
    return resp


@app.get("/auth/google/callback")
def auth_google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    # при ошибке возвращаем туда, откуда начинался вход (next из state)
    st = auth.unsign(state or "", "state")
    fallback = (st or {}).get("next") or "/admin"
    if error:  # пользователь отменил вход на стороне Google
        return RedirectResponse(f"{fallback}?auth_error={quote(error)}", status_code=302)
    try:
        mode, value, next_path = auth.handle_callback(
            code, state, client_ip(request), request.cookies.get(NONCE_COOKIE) or "")
    except AuthError as e:
        return RedirectResponse(f"{fallback}?auth_error={quote(str(e))}", status_code=302)
    resp = RedirectResponse(next_path, status_code=302)
    resp.delete_cookie(NONCE_COOKIE)
    if mode == "staff":
        resp.set_cookie(SESSION_COOKIE, value, max_age=SESSION_TTL_HOURS * 3600,
                        httponly=True, secure=SECURE_COOKIES, samesite="lax")
    elif mode == "cabinet":
        # Google подтвердил email покупателя — выдаём токен кабинета
        buyer_token = store.issue_buyer_token(value)
        resp.set_cookie(BUYER_COOKIE, buyer_token, max_age=BUYER_TTL_DAYS * 86400,
                        httponly=True, secure=SECURE_COOKIES, samesite="lax")
    else:
        resp.set_cookie(PREFILL_COOKIE, value, max_age=600,
                        httponly=True, secure=SECURE_COOKIES, samesite="lax")
    return resp


@app.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        store.delete_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    resp.delete_cookie(PREFILL_COOKIE)
    return resp


# ---------- каталог ----------

@app.get("/api/catalog")
async def get_catalog(request: Request):
    p, denied = _guard(request, "config", "production")
    if denied:
        return denied
    catalog = store.catalog()
    out = {
        "ok": True,
        **_enabled_catalog(catalog),
        "certificate": store.certificate(),
        "currentMonth": _current_month_index(),
    }
    if p.role in ("admin", "config"):
        out["catalog"] = catalog
    return out


@app.put("/api/catalog")
async def put_catalog(request: Request, body: CatalogReq):
    p, denied = _guard(request, "config")
    if denied:
        return denied
    # валидируем структуру целиком: сломанный каталог обрушил бы и выдачу,
    # и сам редактор каталога, которым его можно было бы починить
    cat = body.catalog
    if not isinstance(cat.get("types"), list) or not isinstance(cat.get("places"), list):
        return _err(400, "catalog must contain lists 'types' and 'places'")
    if len(cat["types"]) > serials.CAP["type"] or len(cat["places"]) > serials.CAP["place"]:
        return _err(400, "catalog exceeds serial number capacity")
    for p_ in cat["places"]:
        if not isinstance(p_, dict) or not str(p_.get("name") or "").strip():
            return _err(400, "every site must be an object with a name")
    for t in cat["types"]:
        if not isinstance(t, dict) or not str(t.get("name") or "").strip() or not isinstance(t.get("colors"), list):
            return _err(400, "every type needs a name and a list of colors")
        if len(t["colors"]) > serials.CAP["color"]:
            return _err(400, "too many colors for one type")
        if t.get("site") is not None and not (isinstance(t["site"], int) and 0 <= t["site"] < len(cat["places"])):
            return _err(400, f"type '{t['name']}': site must be an index into places or null")
        for c in t["colors"]:
            if not isinstance(c, dict) or not str(c.get("name") or "").strip():
                return _err(400, f"type '{t['name']}': every colour must be an object with a name")
    store.save_catalog(cat)
    store.audit(p.label, "catalog_update",
                f"types={len(cat['types'])} places={len(cat['places'])}")
    return {"ok": True}


# ---------- выдача номеров ----------

def _validate_issue(req: IssueReq) -> tuple[dict | None, JSONResponse | None]:
    """Возвращает (контекст изделия, None) или (None, ответ-ошибка)."""
    catalog = store.catalog()
    t = catalog["types"][req.type] if 0 <= req.type < len(catalog["types"]) else None
    c = t["colors"][req.color] if t and 0 <= req.color < len(t["colors"]) else None
    p = catalog["places"][req.place] if 0 <= req.place < len(catalog["places"]) else None
    if not t or not t.get("on") or not c or not c.get("on") or not p or not p.get("on"):
        return None, _err(422, "combination not allowed")
    if t.get("site") is not None and t["site"] != req.place:
        return None, _err(422, "this product is not made at this site")
    if not (0 <= req.seq < serials.CAP["seq"]) or not (0 <= req.month < serials.CAP["month"]):
        return None, _err(422, "out of range")
    return {"type": t, "color": c, "place": p}, None


@app.post("/api/issue/preview")
async def issue_preview(request: Request, req: IssueReq):
    """Generate: выдаёт код для выбора, ничего не записывая. Слот не занимается."""
    p, denied = _guard(request, "production")
    if denied:
        return denied
    ctx, bad = _validate_issue(req)
    if bad:
        return bad
    fields = serials.Fields(type=req.type, color=req.color, month=req.month, place=req.place, seq=req.seq)
    taken = store.find_by_slot(serials.slot_of(fields))
    if taken:
        return _err(409, "already issued", code=taken["code"])
    return {"ok": True, "code": serials.encode_serial(fields, store.key)}


@app.post("/api/issue/confirm")
async def issue_confirm(request: Request, req: IssueReq):
    """Save: единственное действие, создающее запись в журнале."""
    p, denied = _guard(request, "production")
    if denied:
        return denied
    ctx, bad = _validate_issue(req)
    if bad:
        return bad
    fields = serials.Fields(type=req.type, color=req.color, month=req.month, place=req.place, seq=req.seq)
    slot = serials.slot_of(fields)
    taken = store.find_by_slot(slot)
    if taken:
        return _err(409, "already issued", code=taken["code"])
    code = serials.encode_serial(fields, store.key)
    if req.expectedCode and code != req.expectedCode:
        return _err(409, "the selection changed — generate again")
    t, c, pl = ctx["type"], ctx["color"], ctx["place"]
    inserted = store.insert_record({
        "code": code, "slot": slot,
        "type": req.type, "color": req.color, "month": req.month, "place": req.place, "seq": req.seq,
        "product": t["name"], "colorName": c["name"], "hex": c.get("hex"), "img": c.get("img"),
        "site": pl["name"], "sheet": t.get("sheet") or "a5", "edition": t.get("edition"),
        "issuedBy": p.label,
    })
    if not inserted:
        taken = store.find_by_slot(slot)
        return _err(409, "already issued", code=taken["code"] if taken else None)
    store.audit(p.label, "issue_save", f"{code} {t['name']} / {c['name']} № {req.seq}")
    return {"ok": True, "code": code, "verifyUrl": f"{PUBLIC_URL}/{code}"}


@app.get("/api/issue/next-seq")
async def next_seq(request: Request, type: int, color: int, month: int, place: int):
    p, denied = _guard(request, "production")
    if denied:
        return denied
    used = store.used_seqs(type, color, month, place)
    # номера изданий идут с 1 (как в прототипе); 0 через подсказку не выдаём
    n = next((i for i in range(1, serials.CAP["seq"]) if i not in used), None)
    if n is None:
        return _err(409, "all edition numbers for this selection are taken", used=len(used))
    return {"ok": True, "seq": n, "used": len(used)}


# ---------- журнал ----------

def _ledger_public(records: list[dict]) -> list[dict]:
    """Журнал наружу: без email/даты рождения владельца."""
    out = []
    for r in records:
        r = dict(r)
        r["monthLabel"] = serials.month_label(r["month"])
        if r["owner"]:
            r["owner"] = {"firstName": r["owner"]["firstName"], "lastName": r["owner"]["lastName"]}
        out.append(r)
    return out


@app.get("/api/ledger")
async def ledger(request: Request):
    p, denied = _guard(request, "production", "ledger")
    if denied:
        return denied
    return {"ok": True, "records": _ledger_public(store.all_records())}


@app.get("/api/ledger/export.csv")
async def ledger_export(request: Request):
    p, denied = _guard(request, "ledger")
    if denied:
        return denied
    def cell(v):
        """Экранирование формул (CWE-1236): часть полей вводят покупатели."""
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code", "product", "color", "seq", "edition", "month", "site",
                "issued_at", "issued_by", "checks", "registered",
                "owner_first_name", "owner_last_name", "owner_email"])
    for r in store.all_records():
        o = r["owner"] or {}
        w.writerow([cell(x) for x in (
            r["code"], r["product"], r["colorName"], r["seq"], r["edition"] or "",
            serials.month_label(r["month"]), r["site"], r["issuedAt"], r["issuedBy"] or "",
            r["checks"], "yes" if r["owner"] else "no",
            o.get("firstName", ""), o.get("lastName", ""), o.get("email", ""))])
    store.audit(p.label, "ledger_export", f"{store.count_records()} records")
    return Response(
        buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=catalist-ledger.csv"},
    )


@app.delete("/api/ledger/{code}")
async def delete_record(request: Request, code: str):
    """Удаление освобождает слот — комбинацию можно выдать заново."""
    p, denied = _guard(request)  # только admin
    if denied:
        return denied
    norm = serials.normalize(code)
    if not store.delete_record(norm):
        return _err(404, "not found")
    store.audit(p.label, "ledger_delete", norm)
    return {"ok": True}


@app.delete("/api/ledger")
async def clear_ledger(request: Request, confirm: str = ""):
    p, denied = _guard(request)  # только admin
    if denied:
        return denied
    if confirm != "all":
        return _err(400, "pass ?confirm=all to delete every record")
    deleted = store.clear_ledger()
    store.audit(p.label, "ledger_clear", f"{deleted} records")
    return {"ok": True, "deleted": deleted}


# ---------- администрирование ----------

@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    p, denied = _guard(request)
    if denied:
        return denied
    return {
        "ok": True, **store.stats(),
        "verify7d": store.verify_stats_since(7),
        "version": APP_VERSION,
        "keyFingerprint": store.key_fingerprint(),
        "dbSchema": store.schema_version(),
    }


@app.get("/api/admin/users")
async def admin_users(request: Request):
    p, denied = _guard(request)
    if denied:
        return denied
    return {"ok": True, "users": store.list_users()}


@app.patch("/api/admin/users/{user_id}")
async def admin_user_patch(request: Request, user_id: int, body: UserPatchReq):
    p, denied = _guard(request)
    if denied:
        return denied
    if body.role is not None and body.role not in USER_ROLES:
        return _err(400, f"role must be one of: {', '.join(USER_ROLES)}")
    if p.user_id == user_id and (body.active is False or (body.role is not None and body.role != "admin")):
        return _err(409, "you cannot demote or deactivate your own account")
    target = store.get_user(user_id)
    if not target:
        return _err(404, "user not found")
    store.update_user(user_id, role=body.role, active=body.active)
    changes = []
    if body.role is not None:
        changes.append(f"role={body.role}")
    if body.active is not None:
        changes.append(f"active={body.active}")
    store.audit(p.label, "user_update", f"{target['email']}: {', '.join(changes) or 'no-op'}")
    return {"ok": True}


@app.get("/api/admin/verify-log")
async def admin_verify_log(request: Request, limit: int = 200, status: str = ""):
    p, denied = _guard(request)
    if denied:
        return denied
    if status and status not in ("issued", "not_issued", "mismatch", "malformed"):
        return _err(400, "unknown status filter")
    return {"ok": True, "entries": store.recent_verifies(min(max(limit, 1), 1000), status or None)}


@app.get("/api/admin/audit-log")
async def admin_audit_log(request: Request, limit: int = 200):
    p, denied = _guard(request)
    if denied:
        return denied
    return {"ok": True, "entries": store.recent_audit(min(max(limit, 1), 1000))}


# ---------- публичные эндпоинты ----------

@app.post("/api/verify")
async def verify(request: Request, req: VerifyReq):
    ip = client_ip(request)
    if not limiter.allow(ip, "verify", VERIFY_PER_MIN):
        return _err(429, "too many requests")
    dec = serials.decode_serial(req.code, store.key)
    if not dec.ok:
        # набран с ошибкой: не та длина, не тот алфавит или контрольный знак
        store.log_verify(dec.norm[:16], "malformed", ip)
        return {"ok": False, "status": "malformed", "code": dec.norm, "reason": dec.reason}
    rec = store.find_by_code(dec.norm)
    if not rec:
        # корректный по формату, но не выпускался
        store.log_verify(dec.norm, "not_issued", ip)
        return {"ok": False, "status": "not_issued", "code": dec.norm}
    if serials.slot_of(dec.fields) != rec["slot"]:
        # расшифровка не совпадает с записью журнала
        store.log_verify(dec.norm, "mismatch", ip)
        return {"ok": False, "status": "mismatch", "code": dec.norm}
    checks = store.bump_checks(dec.norm)
    if checks is None:  # запись успели удалить в момент проверки
        store.log_verify(dec.norm, "not_issued", ip)
        return {"ok": False, "status": "not_issued", "code": dec.norm}
    store.log_verify(dec.norm, "issued", ip)
    return {
        "ok": True, "status": "issued", "code": dec.norm,
        "product": rec["product"], "color": rec["colorName"], "hex": rec["hex"], "img": rec["img"],
        "seq": rec["seq"], "month": rec["month"], "monthLabel": serials.month_label(rec["month"]),
        "site": rec["site"], "checks": checks, "sheet": rec["sheet"], "edition": rec["edition"],
        "certificate": store.certificate(),
        "registered": rec["owner"] is not None,
        "owner": {"firstName": rec["owner"]["firstName"], "lastName": rec["owner"]["lastName"]} if rec["owner"] else None,
    }


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_DOB_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.post("/api/register")
async def register(request: Request, req: RegisterReq):
    """Регистрация владельца: дописывает данные к существующей записи журнала.

    Новую запись не создаёт и возможна один раз на номер — как в прототипе.
    """
    if not limiter.allow(client_ip(request), "register", REGISTER_PER_MIN):
        return _err(429, "too many requests")
    code = serials.normalize(req.code)
    rec = store.find_by_code(code)
    if not rec:
        return _err(404, "this number is not on record")
    if rec["owner"]:
        return _err(409, "this piece is already registered")
    email = req.email.strip().lower()
    first, last, dob = req.firstName.strip(), req.lastName.strip(), req.dob.strip()
    if not _EMAIL_RE.match(email):
        return _err(422, "check the email address")
    if not first or not last:
        return _err(422, "name and surname are required")
    if not _DOB_RE.match(dob):
        return _err(422, "date of birth is required")
    year = int(dob[:4])
    if year < 1900 or year > datetime.now(timezone.utc).year:
        return _err(422, "check the date of birth")
    if not store.register_owner(code, {"email": email, "firstName": first, "lastName": last, "dob": dob}):
        return _err(409, "this piece is already registered")

    # Скидка за регистрацию: сохраняется в БД, письмо уходит в фоне,
    # покупатель сразу залогинен в личный кабинет (cookie).
    discount = store.grant_discount(code, email, DISCOUNT_PERCENT)
    buyer_token = store.issue_buyer_token(email)
    magic_link = f"{PUBLIC_URL}/my?k={buyer_token}"
    email_queued = mailer.send_async(
        mailer.registration_email(
            to=email, first_name=first, product=rec["product"], seq=rec["seq"],
            edition=rec["edition"], code=code, percent=discount["percent"],
            cabinet_url=magic_link, discount_token=discount["token"],
        ),
        on_sent=lambda t=discount["token"]: store.mark_discount_email_sent(t),
    )
    resp = JSONResponse({
        "ok": True, "owner": {"firstName": first, "lastName": last},
        "discount": {"percent": discount["percent"], "token": discount["token"], "status": discount["status"]},
        "cabinetUrl": "/my",
        "emailQueued": email_queued,
    })
    resp.set_cookie(BUYER_COOKIE, buyer_token, max_age=BUYER_TTL_DAYS * 86400,
                    httponly=True, secure=SECURE_COOKIES, samesite="lax")
    return resp


# ---------- личный кабинет покупателя и скидки ----------

def _buyer_email(request: Request) -> str | None:
    return store.buyer_email_by_token(request.cookies.get(BUYER_COOKIE) or "")


@app.get("/api/my")
async def my_collection(request: Request):
    """Кабинет: фигурки, зарегистрированные на email покупателя, и его скидки."""
    if not limiter.allow(client_ip(request), "cabinet", 60):
        return _err(429, "too many requests")
    email = _buyer_email(request)
    if not email:
        return _err(401, "sign in to see your collection")
    discounts = store.discounts_by_email(email)
    figurines = []
    for r in store.records_by_owner_email(email):
        d = discounts.get(r["code"])
        figurines.append({
            "code": r["code"], "product": r["product"], "color": r["colorName"],
            "hex": r["hex"], "img": r["img"], "seq": r["seq"], "edition": r["edition"],
            "monthLabel": serials.month_label(r["month"]), "site": r["site"],
            "registeredAt": (r["owner"] or {}).get("registeredAt"),
            "discount": {"token": d["token"], "percent": d["percent"],
                         "status": d["status"], "createdAt": d["createdAt"]} if d else None,
        })
    return {"ok": True, "email": email, "figurines": figurines}


@app.post("/api/my/link")
async def my_link(request: Request, req: MyLinkReq):
    """Отправка ссылки для входа в кабинет. Ответ одинаков для любых адресов —
    по нему нельзя проверить, есть ли email в базе."""
    if not limiter.allow(client_ip(request), "maglink", 5):
        return _err(429, "too many requests")
    email = req.email.strip().lower()
    message = "If this address has a registered figurine, the sign-in link is on its way."
    if _EMAIL_RE.match(email) and (store.buyer_exists(email) or store.records_by_owner_email(email)):
        token = store.issue_buyer_token(email)
        mailer.send_async(mailer.signin_email(to=email, cabinet_url=f"{PUBLIC_URL}/my?k={token}"))
    return {"ok": True, "message": message}


@app.post("/api/my/logout")
async def my_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(BUYER_COOKIE)
    return resp


@app.get("/api/my/qr/{token}")
async def my_discount_qr(request: Request, token: str):
    """QR скидки (SVG). Отдаётся только владельцу кабинета, которому она выдана."""
    email = _buyer_email(request)
    if not email:
        return _err(401, "sign in to see your collection")
    d = store.discount_by_token(token.strip().upper())
    if not d or d["email"] != email:
        return _err(404, "not found")
    buff = io.BytesIO()
    segno.make(f"{PUBLIC_URL}/d/{d['token']}", error="m").save(
        buff, kind="svg", scale=6, dark="#14120E", light=None)
    return Response(buff.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/discount/{token}")
async def discount_check(request: Request, token: str):
    """Публичная проверка скидки — страницу /d/<токен> открывает кассир по QR."""
    if not limiter.allow(client_ip(request), "discount", 30):
        return _err(429, "too many requests")
    d = store.discount_by_token(token.strip().upper())
    if not d:
        return _err(404, "unknown discount")
    rec = store.find_by_code(d["code"])
    return {
        "ok": True, "status": d["status"], "percent": d["percent"], "token": d["token"],
        "createdAt": d["createdAt"], "usedAt": d["usedAt"],
        "product": rec["product"] if rec else None,
        "ownerFirstName": (rec["owner"] or {}).get("firstName") if rec else None,
    }


@app.get("/api/admin/discounts")
async def admin_discounts(request: Request):
    p, denied = _guard(request)
    if denied:
        return denied
    return {"ok": True, "discounts": store.list_discounts()}


@app.patch("/api/admin/discounts/{token}")
async def admin_discount_patch(request: Request, token: str, body: DiscountPatchReq):
    """Отметка «скидка использована» (или возврат в active) — только admin."""
    p, denied = _guard(request)
    if denied:
        return denied
    if body.status not in ("active", "used"):
        return _err(400, "status must be 'active' or 'used'")
    token = token.strip().upper()
    if not store.set_discount_status(token, body.status):
        return _err(404, "not found")
    store.audit(p.label, "discount_update", f"{token}: status={body.status}")
    return {"ok": True}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "version": APP_VERSION}


# ---------- страницы ----------

@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/admin")
async def admin_page():
    return FileResponse(os.path.join(WEB_DIR, "admin.html"))


@app.get("/my")
async def my_page(request: Request, k: str = ""):
    """Личный кабинет. Ссылка из письма несёт ?k=<токен> — ставим cookie
    и уходим на чистый /my, чтобы токен не оставался в адресной строке."""
    if k:
        email = store.buyer_email_by_token(k)
        if email:
            resp = RedirectResponse("/my", status_code=302)
            resp.set_cookie(BUYER_COOKIE, k, max_age=BUYER_TTL_DAYS * 86400,
                            httponly=True, secure=SECURE_COOKIES, samesite="lax")
            return resp
        return RedirectResponse("/my", status_code=302)  # просроченная ссылка → экран входа
    return FileResponse(os.path.join(WEB_DIR, "my.html"))


@app.get("/d/{token}")
async def discount_page(token: str):
    """Страница проверки скидки — на неё ведёт QR из кабинета."""
    return FileResponse(os.path.join(WEB_DIR, "discount.html"))


@app.get("/{code}")
async def deep_link(code: str):
    """Страница проверки по прямой ссылке — на неё ведёт QR-код сертификата.

    Любой путь вида /XXXXXXXX открывает интерфейс с автопроверкой кода;
    сам код разбирает клиентский скрипт из location.pathname.
    """
    if code.lower() in {"api", "static", "healthz", "admin", "auth", "my", "d", "favicon.ico"}:
        return _err(404, "not found")
    if not re.fullmatch(r"[0-9A-Za-z-]{1,32}", code):
        return _err(404, "not found")
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
