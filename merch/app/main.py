"""HTTP API модуля мерч-кодов Catalist.

Эндпоинты повторяют операции api.* прототипа один в один (см.
docs/merch-module.md — там таблица соответствия). Формат ответов и
тексты статусов сохранены, чтобы поведение совпадало с описанием
системы: generate ничего не записывает, запись создаёт только save.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import serials
from .security import RateLimiter, Roles, client_ip
from .storage import Storage

DATA_DIR = os.environ.get("MERCH_DATA_DIR", "data")
PUBLIC_URL = (os.environ.get("MERCH_PUBLIC_URL") or "https://code.catalist.world").rstrip("/")
MAIN_SITE = os.environ.get("MERCH_MAIN_SITE", "https://catalist.world")

VERIFY_PER_MIN = int(os.environ.get("MERCH_VERIFY_PER_MIN", "30"))
REGISTER_PER_MIN = int(os.environ.get("MERCH_REGISTER_PER_MIN", "10"))
ISSUE_PER_MIN = int(os.environ.get("MERCH_ISSUE_PER_MIN", "60"))

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

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _err(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, **extra}, status_code=status)


def _role(request: Request) -> str | None:
    return roles.role_of(request.headers.get("x-pin"))


def _guard_staff(request: Request, need_admin: bool = False):
    """None — доступ разрешён, иначе готовый ответ с ошибкой."""
    if not roles.configured:
        return _err(503, "PINs are not configured on the server")
    if not limiter.allow(client_ip(request), "staff", ISSUE_PER_MIN):
        return _err(429, "too many requests")
    role = _role(request)
    if role is None or (need_admin and role != "admin"):
        return _err(401, "unauthorized")
    return None


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
    expectedCode: str | None = None


class VerifyReq(BaseModel):
    code: str


class RegisterReq(BaseModel):
    code: str
    firstName: str = ""
    lastName: str = ""
    dob: str = ""
    email: str = ""


class CatalogReq(BaseModel):
    catalog: dict


# ---------- служебные эндпоинты (PIN) ----------

@app.get("/api/status")
async def status(request: Request):
    return {
        "ok": True,
        "provisioned": True,
        "keyFingerprint": store.key_fingerprint(),
        "baseYear": serials.BASE_YEAR,
        "currentMonth": _current_month_index(),
        "issued": store.count_records(),
        "role": _role(request),
        "publicUrl": PUBLIC_URL,
    }


@app.get("/api/catalog")
async def get_catalog(request: Request):
    denied = _guard_staff(request)
    if denied:
        return denied
    catalog = store.catalog()
    out = {
        "ok": True,
        **_enabled_catalog(catalog),
        "certificate": store.certificate(),
        "currentMonth": _current_month_index(),
    }
    if _role(request) == "admin":
        out["catalog"] = catalog
    return out


@app.put("/api/catalog")
async def put_catalog(request: Request, body: CatalogReq):
    denied = _guard_staff(request, need_admin=True)
    if denied:
        return denied
    cat = body.catalog
    if not isinstance(cat.get("types"), list) or not isinstance(cat.get("places"), list):
        return _err(400, "catalog must contain lists 'types' and 'places'")
    if len(cat["types"]) > serials.CAP["type"] or len(cat["places"]) > serials.CAP["place"]:
        return _err(400, "catalog exceeds serial number capacity")
    for t in cat["types"]:
        if not t.get("name") or not isinstance(t.get("colors"), list):
            return _err(400, "every type needs a name and a list of colors")
        if len(t["colors"]) > serials.CAP["color"]:
            return _err(400, "too many colors for one type")
    store.save_catalog(cat)
    return {"ok": True}


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
    denied = _guard_staff(request)
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
    denied = _guard_staff(request)
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
    t, c, p = ctx["type"], ctx["color"], ctx["place"]
    inserted = store.insert_record({
        "code": code, "slot": slot,
        "type": req.type, "color": req.color, "month": req.month, "place": req.place, "seq": req.seq,
        "product": t["name"], "colorName": c["name"], "hex": c.get("hex"), "img": c.get("img"),
        "site": p["name"], "sheet": t.get("sheet") or "a5", "edition": t.get("edition"),
    })
    if not inserted:
        taken = store.find_by_slot(slot)
        return _err(409, "already issued", code=taken["code"] if taken else None)
    return {"ok": True, "code": code, "verifyUrl": f"{PUBLIC_URL}/{code}"}


@app.get("/api/issue/next-seq")
async def next_seq(request: Request, type: int, color: int, month: int, place: int):
    denied = _guard_staff(request)
    if denied:
        return denied
    used = store.used_seqs(type, color, month, place)
    n = 1
    while n in used and n < serials.CAP["seq"]:
        n += 1
    return {"ok": True, "seq": n, "used": len(used)}


@app.get("/api/ledger")
async def ledger(request: Request):
    denied = _guard_staff(request)
    if denied:
        return denied
    records = store.all_records()
    for r in records:
        r["monthLabel"] = serials.month_label(r["month"])
        if r["owner"]:  # журнал не отдаёт персональные данные целиком
            r["owner"] = {"firstName": r["owner"]["firstName"], "lastName": r["owner"]["lastName"]}
    return {"ok": True, "records": records}


@app.delete("/api/ledger/{code}")
async def delete_record(request: Request, code: str):
    """Удаление освобождает слот — комбинацию можно выдать заново."""
    denied = _guard_staff(request, need_admin=True)
    if denied:
        return denied
    if not store.delete_record(serials.normalize(code)):
        return _err(404, "not found")
    return {"ok": True}


@app.delete("/api/ledger")
async def clear_ledger(request: Request, confirm: str = ""):
    denied = _guard_staff(request, need_admin=True)
    if denied:
        return denied
    if confirm != "all":
        return _err(400, "pass ?confirm=all to delete every record")
    return {"ok": True, "deleted": store.clear_ledger()}


# ---------- публичные эндпоинты ----------

@app.post("/api/verify")
async def verify(request: Request, req: VerifyReq):
    if not limiter.allow(client_ip(request), "verify", VERIFY_PER_MIN):
        return _err(429, "too many requests")
    dec = serials.decode_serial(req.code, store.key)
    if not dec.ok:
        # набран с ошибкой: не та длина, не тот алфавит или контрольный знак
        return {"ok": False, "status": "malformed", "code": dec.norm, "reason": dec.reason}
    rec = store.find_by_code(dec.norm)
    if not rec:
        # корректный по формату, но не выпускался
        return {"ok": False, "status": "not_issued", "code": dec.norm}
    if serials.slot_of(dec.fields) != rec["slot"]:
        # расшифровка не совпадает с записью журнала
        return {"ok": False, "status": "mismatch", "code": dec.norm}
    checks = store.bump_checks(dec.norm)
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
    email = req.email.strip()
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
    return {"ok": True, "owner": {"firstName": first, "lastName": last}}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ---------- страницы ----------

@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/{code}")
async def deep_link(code: str):
    """Страница проверки по прямой ссылке — на неё ведёт QR-код сертификата.

    Любой путь вида /XXXXXXXX открывает интерфейс с автопроверкой кода;
    сам код разбирает клиентский скрипт из location.pathname.
    """
    if code.lower() in {"api", "static", "healthz", "admin", "auth", "favicon.ico"}:
        return _err(404, "not found")
    if not re.fullmatch(r"[0-9A-Za-z-]{1,32}", code):
        return _err(404, "not found")
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
