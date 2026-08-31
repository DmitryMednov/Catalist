# История изменений

Журнал релизов модуля мерч-кодов. Формат — по [Keep a Changelog](https://keepachangelog.com/ru/), нумерация — [semver](https://semver.org/lang/ru/): **MAJOR** — несовместимые изменения API или схемы БД, **MINOR** — новые возможности, **PATCH** — исправления. Перед обновлением на новый MAJOR обязателен бэкап базы (см. `docs/merch-module.md`, раздел «Бэкапы»).

## [2.0.0] — 2026-08-31

### Added
- Ролевая модель из четырёх ролей: admin, config, production, ledger.
- Вход персонала через Google (OAuth 2.0 code flow); bootstrap первого администратора по `MERCH_ADMIN_EMAILS`; таблицы `users`/`sessions`, cookie-сессии на 12 часов.
- Дашборд `/admin`: Overview, Users, Catalog, Journal, Logs.
- `verify_log` — журнал всех проверок номеров (статус, IP, время; хранение `MERCH_VERIFYLOG_DAYS`, по умолчанию 365 дней).
- `audit_log` — журнал действий персонала (выдача, удаление, правка каталога, входы, смена ролей).
- Миграции схемы БД (`schema_migrations`), применяются автоматически при старте.
- Версия модуля в `/api/status` (`merch/app/version.py`, `APP_VERSION`).
- Экспорт журнала в CSV (`GET /api/ledger/export.csv`).
- Автозаполнение формы регистрации покупателя из Google-профиля (`mode=buyer`, без создания staff-аккаунта).

### Changed
- Права двух PIN-ролей 1.x сопоставлены новой модели: PIN production → роль production, PIN admin → роль admin.
- `/api/status` дополнен полем версии и данными текущей сессии.

### Compatibility
- База 1.x обновляется автоматически при первом старте 2.x (миграции аддитивные, данные сохраняются).
- PIN-вход 1.x (заголовок `X-Pin`) полностью сохранён.
- Формат ответов API прототипа не менялся.

## [1.0.0] — 2026-08-31

Первый выпуск модуля мерч-кодов:

- порт ядра серийных номеров из прототипа `hallmarksuite.tsx` бит-в-бит (64 эталонных вектора, `merch/tests/vectors.json`);
- REST API один-в-один с операциями `api.*` прототипа (preview/confirm/next-seq, ledger, verify, register);
- SQLite-хранилище с уникальностью `code` и `slot` на уровне БД; автогенерация 128-битного ключа с файлом-бэкапом;
- PIN-роли production/admin, ограничение частоты запросов на IP;
- веб-интерфейс Check/Serial/Register и глубокая ссылка `/НОМЕР` для QR-кодов;
- развёртывание: docker compose (bot, merch, caddy), автоматический HTTPS.
