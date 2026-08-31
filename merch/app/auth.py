"""Аутентификация: сессии, вход через Google, PIN-совместимость.

Два способа входа персонала:
  * Google-аккаунт — OAuth 2.0 authorization code flow. Роль назначает
    администратор в дашборде; адреса из MERCH_ADMIN_EMAILS получают
    роль admin автоматически при входе (bootstrap первого админа).
  * PIN переходного периода (сборка 1.x): заголовок X-Pin,
    MERCH_PRODUCTION_PIN → production, MERCH_ADMIN_PIN → admin.

Для покупателя (mode=buyer) staff-учётка не создаётся: профиль Google
кладётся в короткоживущую подписанную cookie и подставляется в форму
регистрации владельца через /api/me/prefill.

Секрет подписи состояний и cookie генерируется при первом старте и
хранится в app_config — cookie переживают перезапуск контейнера.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .security import Roles
from .storage import Storage

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SESSION_COOKIE = "merch_session"
PREFILL_COOKIE = "merch_prefill"
SESSION_TTL_HOURS = 12
STATE_TTL_S = 600
PREFILL_TTL_S = 600


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    kind: str            # "user" | "pin"
    role: str            # admin | config | production | ledger | none
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    user_id: int | None = None

    @property
    def label(self) -> str:
        """Подпись для журнала действий: почта или pin:<роль>."""
        return self.email or f"pin:{self.role}"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "role": self.role, "email": self.email,
                "name": self.name, "picture": self.picture}


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Auth:
    def __init__(self, store: Storage, roles: Roles, public_url: str):
        self.store = store
        self.roles = roles
        self.public_url = public_url.rstrip("/")
        self.client_id = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
        self.client_secret = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
        self.admin_emails = {
            e.strip().lower()
            for e in (os.environ.get("MERCH_ADMIN_EMAILS") or "").split(",") if e.strip()
        }
        secret = (os.environ.get("MERCH_SESSION_SECRET") or "").strip()
        if not secret:
            secret = store.app_config_get("session_secret")
            if not secret:
                secret = secrets.token_hex(32)
                store.app_config_set("session_secret", secret)
        self._secret = secret.encode()

    @property
    def google_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/google/callback"

    # ---------- подписанные значения (state, prefill-cookie) ----------

    def sign(self, payload: dict, ttl_s: int, purpose: str) -> str:
        """Подписанный токен с назначением: state и prefill не взаимозаменяемы."""
        body = _b64e(json.dumps({**payload, "pur": purpose, "exp": int(time.time()) + ttl_s}).encode())
        mac = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{mac}"

    def unsign(self, token: str, purpose: str) -> dict | None:
        try:
            body, mac = token.split(".", 1)
            if not hmac.compare_digest(hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest(), mac):
                return None
            payload = json.loads(_b64d(body))
            if payload.get("exp", 0) < time.time() or payload.get("pur") != purpose:
                return None
            return payload
        except Exception:
            return None

    # ---------- OAuth flow ----------

    @staticmethod
    def _safe_next(next_path: str) -> str:
        # только внутренние пути — никаких редиректов на чужие домены
        return next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"

    def auth_url(self, mode: str, next_path: str) -> tuple[str, str]:
        """Возвращает (URL Google, nonce). Nonce кладётся в cookie браузера и
        сверяется на callback — state не может быть подброшен из чужой сессии."""
        if not self.google_configured:
            raise AuthError("Google sign-in is not configured on the server")
        mode = mode if mode in ("staff", "buyer") else "staff"
        nonce = secrets.token_hex(16)
        state = self.sign({"mode": mode, "next": self._safe_next(next_path), "nonce": nonce}, STATE_TTL_S, "state")
        url = GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        })
        return url, nonce

    def _exchange_code(self, code: str) -> dict:
        """Меняет authorization code на профиль пользователя Google."""
        with httpx.Client(timeout=15) as client:
            tok = client.post(GOOGLE_TOKEN_URL, data={
                "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
            })
            if tok.status_code != 200:
                raise AuthError(f"token exchange failed ({tok.status_code})")
            access_token = tok.json().get("access_token")
            if not access_token:
                raise AuthError("no access token in Google response")
            info = client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            if info.status_code != 200:
                raise AuthError(f"userinfo failed ({info.status_code})")
            return info.json()

    def handle_callback(self, code: str, state: str, ip: str, nonce_cookie: str) -> tuple[str, str, str]:
        """Возвращает (mode, значение cookie, путь редиректа)."""
        st = self.unsign(state or "", "state")
        if not st:
            raise AuthError("state expired or invalid — start the sign-in again")
        # nonce из state обязан совпасть с cookie, выставленной этому браузеру
        # на старте входа, — иначе state подброшен из чужой сессии (login CSRF)
        if not nonce_cookie or not hmac.compare_digest(str(st.get("nonce") or ""), nonce_cookie):
            raise AuthError("sign-in was started in a different browser — start again")
        profile = self._exchange_code(code)
        email = (profile.get("email") or "").lower()
        if not email or not profile.get("email_verified", False):
            raise AuthError("Google account has no verified email")
        next_path = self._safe_next(st.get("next") or "/")
        if st.get("mode") == "buyer":
            prefill = self.sign({
                "firstName": profile.get("given_name") or "",
                "lastName": profile.get("family_name") or "",
                "email": email,
            }, PREFILL_TTL_S, "prefill")
            return "buyer", prefill, next_path
        user = self.store.upsert_google_user(
            sub=profile.get("sub") or email, email=email,
            name=profile.get("name") or "", picture=profile.get("picture") or "",
            admin_emails=self.admin_emails,
        )
        if not user["active"]:
            raise AuthError("this account is deactivated")
        token = self.store.create_session(user["id"], ip, SESSION_TTL_HOURS)
        self.store.audit(email, "login_google", f"role={user['role']}")
        return "staff", token, next_path

    # ---------- принципал запроса ----------

    def principal(self, request) -> Principal | None:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            user = self.store.session_user(token)
            if user:
                return Principal(kind="user", role=user["role"], email=user["email"],
                                 name=user["name"], picture=user["picture"], user_id=user["id"])
        pin_role = self.roles.role_of(request.headers.get("x-pin"))
        if pin_role:
            return Principal(kind="pin", role=pin_role)
        return None

    def prefill_from(self, request) -> dict | None:
        data = self.unsign(request.cookies.get(PREFILL_COOKIE) or "", "prefill")
        if not data:
            return None
        return {"firstName": data.get("firstName", ""), "lastName": data.get("lastName", ""),
                "email": data.get("email", "")}
