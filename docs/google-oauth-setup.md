# Настройка входа через Google (OAuth 2.0)

Инструкция для модуля мерч-кодов (code.catalist.world). Результат — кнопка «Sign in with Google» на странице `/admin` и вход персонала через Google-аккаунты. До выполнения этих шагов модуль полностью работает по PIN-кодам.

Обновлено: 2026-08-31.

## Шаг 1. Проект в Google Cloud

1. Открыть [console.cloud.google.com](https://console.cloud.google.com) под аккаунтом, которому будет принадлежать интеграция.
2. Создать проект (вверху слева выбор проекта → **New Project**), например `catalist-merch`.

## Шаг 2. Экран согласия (OAuth consent screen)

1. **APIs & Services → OAuth consent screen**.
2. Тип пользователей — **External**.
3. Заполнить: название приложения **Catalist**, support email, контакт разработчика.
4. Scopes: достаточно базовых `openid`, `email`, `profile` (другие не запрашивать).
5. Пока приложение в статусе Testing, входить смогут только адреса из списка **Test users** — добавить туда рабочие адреса персонала. Либо нажать **Publish app** — тогда вход открыт любому Google-аккаунту (роль в модуле всё равно назначает администратор, посторонние получают роль `none` без доступа).

## Шаг 3. Ключи (Credentials)

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type — **Web application**, имя произвольное.
3. **Authorized JavaScript origins**:
   `https://code.catalist.world`
4. **Authorized redirect URIs** — точно, без слэша в конце:
   `https://code.catalist.world/auth/google/callback`
5. Нажать **Create** и скопировать **Client ID** и **Client secret**.

Если модуль развёрнут на другом поддомене — подставить его в оба адреса.

## Шаг 4. Подключение на сервере

В `.env` на сервере:

```bash
GOOGLE_CLIENT_ID=<Client ID>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<Client secret>
MERCH_ADMIN_EMAILS=mednovdmitry@gmail.com
```

Применить:

```bash
docker compose up -d merch
```

После перезапуска на `/admin` появится кнопка **Sign in with Google**.

## Шаг 5. Первый вход

Первый вход с адреса `mednovdmitry@gmail.com` автоматически даёт роль **admin** (bootstrap по `MERCH_ADMIN_EMAILS`). Дальше роли остальных сотрудников назначаются в дашборде: **/admin → Users**.

## Типовые ошибки

| Симптом | Причина и решение |
|---|---|
| `redirect_uri_mismatch` | Redirect URI в Google Console не совпадает байт-в-байт с `https://<поддомен>/auth/google/callback` (протокол, домен, путь, отсутствие завершающего слэша). Исправить в Credentials. |
| «Access blocked / приложение не прошло проверку» | Consent screen не опубликован, а входящий не в списке Test users. Добавить адрес в **Test users** или нажать **Publish app**. |
| Вход проходит, но доступа нет (роль `none`) | Адрес не входит в `MERCH_ADMIN_EMAILS`, а роль ещё не назначена. Администратор выдаёт роль в **/admin → Users**. |
