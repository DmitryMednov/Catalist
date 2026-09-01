# День включения домена — чек-лист

Выполняется один раз, когда появляется доступ к DNS-панели catalist.world.
Порядок важен. Ориентировочно 30–40 минут. IP сервера: `209.38.205.133`.

## 1. DNS-записи

В панели домена создать:

| Тип | Имя | Значение | Зачем |
|---|---|---|---|
| A | `code` | `209.38.205.133` | поддомен модуля |

Записи самого `catalist.world` и `www` **не трогать** — они ведут на Tilda.

Проверка (через 1–15 минут): `dig code.catalist.world +short` → должен вернуться IP сервера.

## 2. Проверить HTTPS

Открыть https://code.catalist.world — Caddy выпустит сертификат Let's Encrypt
автоматически при первом обращении (до ~1 минуты). Перезапускать ничего не нужно.

## 3. Переключить модуль на домен

На сервере в `~/Catalist/.env`:

- **удалить** строку `MERCH_PUBLIC_URL=http://209.38.205.133:8080` — ссылки в
  письмах и QR начнут собираться с https-доменом, включится Secure-флаг cookie;
- **сменить оба PIN-а** (`MERCH_PRODUCTION_PIN`, `MERCH_ADMIN_PIN`) — старые
  вводились по нешифрованному http.

Затем: `./deploy/deploy.sh`.

## 4. Закрыть временный порт 8080

- в `docker-compose.yml` удалить строку `- "8080:8080"` у сервиса caddy;
- в `deploy/Caddyfile` удалить блок `http://:8080 { ... }`;
- применить: `docker compose up -d caddy`.

Проверка: http://209.38.205.133:8080 больше не открывается, https://code.catalist.world работает.

## 5. Включить вход через Google

В `.env` вписать подготовленные credentials (см. `docs/google-oauth-setup.md`):

```
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
```

`docker compose up -d merch` → на страницах появятся кнопки Sign in with Google.
Первый вход с mednovdmitry@gmail.com даёт роль admin автоматически.

## 6. Письма с собственного домена (доставляемость)

Сейчас отправитель — @gmail.com, такие письма чаще попадают в спам.

1. В Brevo: **Senders, Domains & IPs → Domains → Add a domain** → `catalist.world`.
2. Brevo покажет 2–3 DNS-записи (DKIM/DMARC/код подтверждения) — добавить их в ту же DNS-панель, нажать Verify.
3. В Brevo добавить отправителя вида `noreply@catalist.world` (после верификации домена подтверждение кода не требуется).
4. В `.env`: `MERCH_SMTP_FROM=noreply@catalist.world` → `docker compose up -d merch`.

## 7. Кнопка на Tilda

На catalist.world добавить пункт меню/кнопку **«Проверка подлинности»** →
`https://code.catalist.world`. QR новых сертификатов печатать на
`https://code.catalist.world/НОМЕР`.

## 8. Финальная проверка

1. С телефона: https://code.catalist.world → выпустить тестовый номер (новый PIN) → проверить → зарегистрировать на тестовую почту → письмо пришло, ссылки в нём ведут на https-домен.
2. Кабинет `/my` открывается из письма; QR скидки сканируется и открывает `/d/<код>`.
3. `/admin` — вход через Google работает, роль admin.
4. Тестовые записи удалить в Journal, скидки при желании — пометить used.
