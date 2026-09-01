"""Отправка писем покупателям: HTTPS-API Brevo или классический SMTP.

Два транспорта (см. .env.example):
  * MERCH_BREVO_API_KEY — отправка через api.brevo.com по HTTPS (порт 443).
    Рекомендуется на DigitalOcean и подобных хостингах: исходящие
    SMTP-порты (25/465/587) там часто заблокированы на уровне сети.
    Отправитель — MERCH_SMTP_FROM (адрес должен быть подтверждён в Brevo).
  * MERCH_SMTP_HOST/PORT/USER/PASSWORD/FROM/SECURITY — обычный SMTP.
Если задан API-ключ, используется он. Пока не настроено ни то ни другое,
письма не отправляются — остальной функционал (скидка, кабинет) работает.

Отправка идёт в фоновом потоке: регистрация фигурки не ждёт SMTP-сервер.
Результат отправки фиксируется колбэком (флаг email_sent у скидки) и в логе.
"""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

import httpx

log = logging.getLogger("merch.mailer")


class Mailer:
    def __init__(self) -> None:
        self.host = (os.environ.get("MERCH_SMTP_HOST") or "").strip()
        self.port = int(os.environ.get("MERCH_SMTP_PORT") or "587")
        self.user = (os.environ.get("MERCH_SMTP_USER") or "").strip()
        self.password = os.environ.get("MERCH_SMTP_PASSWORD") or ""
        self.sender = (os.environ.get("MERCH_SMTP_FROM") or self.user).strip()
        self.security = (os.environ.get("MERCH_SMTP_SECURITY") or "starttls").strip().lower()
        self.brevo_key = (os.environ.get("MERCH_BREVO_API_KEY") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.sender and (self.brevo_key or self.host))

    # ---------- транспорт ----------

    def _deliver(self, msg: EmailMessage) -> None:
        """Синхронная доставка; вынесена отдельно, чтобы тесты могли её подменить."""
        if self.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=20)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=20)
        try:
            if self.security == "starttls":
                server.starttls()
            if self.user:
                server.login(self.user, self.password)
            server.send_message(msg)
        finally:
            server.quit()

    def _deliver_api(self, msg: EmailMessage) -> None:
        """Доставка через HTTPS-API Brevo — обходит блокировку SMTP-портов."""
        text = msg.get_body(("plain",))
        html = msg.get_body(("html",))
        payload = {
            "sender": {"name": "Catalist", "email": self.sender},
            "to": [{"email": str(msg["To"])}],
            "subject": str(msg["Subject"]),
            "textContent": text.get_content() if text else "",
        }
        if html is not None:
            payload["htmlContent"] = html.get_content()
        r = httpx.post("https://api.brevo.com/v3/smtp/email", json=payload,
                       headers={"api-key": self.brevo_key, "accept": "application/json"},
                       timeout=20)
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"Brevo API {r.status_code}: {r.text[:300]}")

    def send_async(self, msg: EmailMessage, on_sent=None) -> bool:
        """Ставит письмо в фоновую отправку; False — SMTP не настроен."""
        if not self.enabled:
            log.info("mail is not configured; skipping email to %s", msg["To"])
            return False
        deliver = self._deliver_api if self.brevo_key else self._deliver

        def run():
            try:
                deliver(msg)
                log.info("email sent to %s (%s)", msg["To"], msg["Subject"])
                if on_sent:
                    on_sent()
            except Exception as e:  # сбой почты не должен ронять регистрацию
                log.warning("email to %s failed: %s", msg["To"], e)

        threading.Thread(target=run, daemon=True).start()
        return True

    # ---------- письма ----------

    def registration_email(self, *, to: str, first_name: str, product: str,
                           seq: int, edition: int | None, code: str,
                           percent: int, cabinet_url: str, discount_token: str) -> EmailMessage:
        """Уведомление о регистрации фигурки: скидка + ссылка в личный кабинет."""
        edition_str = f"№ {seq:03d}" + (f" / {edition}" if edition else "")
        subject = f"Your {product} is registered — {percent}% discount inside"
        text = f"""Hello {first_name},

Your Catalist figurine is now registered to you.

  Product:  {product}
  Edition:  {edition_str}
  Serial:   {code}

As a thank-you, a {percent}% loyalty discount is saved to your collection.
Discount code: {discount_token}

Open your personal collection page — your figurines and the discount QR code live there:

  {cabinet_url}

Keep this email: the link above signs you in without a password.

— Catalist
https://catalist.world
"""
        html = f"""\
<div style="margin:0;padding:32px 16px;background:#F2E0BE;font-family:-apple-system,'Helvetica Neue','Segoe UI',Arial,sans-serif;color:#14120E">
  <div style="max-width:520px;margin:0 auto">
    <div style="font-size:26px;font-weight:800;letter-spacing:.4px;margin-bottom:18px">CATALIST</div>
    <div style="background:#FFFFFF;border-radius:16px;padding:28px">
      <div style="font-size:22px;font-weight:800;text-transform:uppercase;line-height:1.25">
        <span style="font-weight:300">Your figurine</span> is registered
      </div>
      <p style="font-size:16px;line-height:1.55;margin:14px 0 20px">Hello {first_name}, thank you for joining Catalist.</p>
      <table style="width:100%;border-collapse:collapse;font-size:15.5px">
        <tr><td style="padding:9px 0;color:#6B6555;text-transform:uppercase;font-size:12px;letter-spacing:1px">Product</td><td style="text-align:right;font-weight:700">{product}</td></tr>
        <tr><td style="padding:9px 0;color:#6B6555;text-transform:uppercase;font-size:12px;letter-spacing:1px;border-top:1px solid rgba(20,18,14,.12)">Edition</td><td style="text-align:right;border-top:1px solid rgba(20,18,14,.12)">{edition_str}</td></tr>
        <tr><td style="padding:9px 0;color:#6B6555;text-transform:uppercase;font-size:12px;letter-spacing:1px;border-top:1px solid rgba(20,18,14,.12)">Serial</td><td style="text-align:right;border-top:1px solid rgba(20,18,14,.12);font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:2px">{code}</td></tr>
      </table>
      <div style="background:#14120E;color:#FFFFFF;border-radius:14px;padding:22px;margin:22px 0;text-align:center">
        <div style="font-size:26px;font-weight:800">{percent}% OFF</div>
        <div style="font-size:14px;opacity:.85;margin-top:6px">your loyalty discount is saved</div>
        <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:18px;letter-spacing:2px;margin-top:12px">{discount_token}</div>
      </div>
      <a href="{cabinet_url}" style="display:block;background:#14120E;color:#FFFFFF;text-decoration:none;text-align:center;border-radius:999px;padding:16px;font-size:16px;font-weight:700">Open my collection</a>
      <p style="font-size:13px;color:#6B6555;line-height:1.5;margin:16px 0 0">The discount QR code for the checkout is on your collection page. This link signs you in without a password — keep this email.</p>
    </div>
    <p style="font-size:12px;color:#6B6555;text-align:center;margin-top:18px">© Catalist · <a href="https://catalist.world" style="color:#6B6555">catalist.world</a></p>
  </div>
</div>"""
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("Catalist", self.sender))
        msg["To"] = to
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        return msg

    def signin_email(self, *, to: str, cabinet_url: str) -> EmailMessage:
        """Ссылка для входа в личный кабинет (magic link)."""
        text = f"""Hello,

Here is your sign-in link for the Catalist collection page:

  {cabinet_url}

If you did not request it, just ignore this email.

— Catalist
https://catalist.world
"""
        html = f"""\
<div style="margin:0;padding:32px 16px;background:#F2E0BE;font-family:-apple-system,'Helvetica Neue','Segoe UI',Arial,sans-serif;color:#14120E">
  <div style="max-width:520px;margin:0 auto">
    <div style="font-size:26px;font-weight:800;letter-spacing:.4px;margin-bottom:18px">CATALIST</div>
    <div style="background:#FFFFFF;border-radius:16px;padding:28px">
      <div style="font-size:22px;font-weight:800;text-transform:uppercase"><span style="font-weight:300">Sign in to</span> your collection</div>
      <p style="font-size:16px;line-height:1.55;margin:14px 0 22px">Use the button below to open your Catalist collection — no password needed.</p>
      <a href="{cabinet_url}" style="display:block;background:#14120E;color:#FFFFFF;text-decoration:none;text-align:center;border-radius:999px;padding:16px;font-size:16px;font-weight:700">Open my collection</a>
      <p style="font-size:13px;color:#6B6555;line-height:1.5;margin:16px 0 0">If you did not request this link, just ignore this email.</p>
    </div>
    <p style="font-size:12px;color:#6B6555;text-align:center;margin-top:18px">© Catalist · <a href="https://catalist.world" style="color:#6B6555">catalist.world</a></p>
  </div>
</div>"""
        msg = EmailMessage()
        msg["Subject"] = "Your Catalist sign-in link"
        msg["From"] = formataddr(("Catalist", self.sender))
        msg["To"] = to
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        return msg
