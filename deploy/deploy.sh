#!/usr/bin/env bash
# Деплой/обновление сервисов Catalist на сервере: бот + модуль мерч-кодов + caddy.
#
# Первый запуск на чистом сервере:
#   git clone -b claude/merch-code-generator-module-ng1tmq https://github.com/DmitryMednov/Catalist.git
#   cd Catalist
#   ./deploy/deploy.sh        # создаст .env и попросит его заполнить
#   nano .env                 # заполнить PIN-ы, домен и токены бота
#   ./deploy/deploy.sh        # соберёт и запустит всё
#
# Обновление до свежей версии той же ветки: ./deploy/deploy.sh
# Деплой другой ветки:                      ./deploy/deploy.sh main
set -euo pipefail

BRANCH="${1:-claude/merch-code-generator-module-ng1tmq}"
cd "$(dirname "$0")/.."

say()  { printf '\n== %s\n' "$*"; }
fail() { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null || fail "не установлен git"
command -v docker >/dev/null || fail "не установлен docker — https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || fail "нужен docker compose v2 (плагин compose)"

# ---------- .env ----------
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  say "Создан .env из шаблона"
  echo "Заполните в нём BOT_TOKEN, ADMIN_CHAT_IDS, REVIEW_CHAT_ID, MERCH_DOMAIN,"
  echo "MERCH_PRODUCTION_PIN и MERCH_ADMIN_PIN, затем запустите скрипт ещё раз."
  exit 1
fi

# последнее вхождение — так же читает .env сам docker compose
envval() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }

for v in MERCH_PRODUCTION_PIN MERCH_ADMIN_PIN; do
  [ -n "$(envval "$v")" ] || fail "в .env не заполнено $v — служебные функции модуля будут отключены (503)"
done
PROD_PIN="$(envval MERCH_PRODUCTION_PIN)"
ADMIN_PIN="$(envval MERCH_ADMIN_PIN)"
{ [ "${#PROD_PIN}" -ge 4 ] && [ "${#ADMIN_PIN}" -ge 4 ]; } || fail "PIN-ы должны быть не короче 4 знаков"
[ "$PROD_PIN" != "$ADMIN_PIN" ] || fail "MERCH_PRODUCTION_PIN и MERCH_ADMIN_PIN должны различаться"
DOMAIN="$(envval MERCH_DOMAIN)"
DOMAIN="${DOMAIN:-code.catalist.world}"

# ---------- код ----------
say "Обновляю код: ветка $BRANCH"
git fetch origin "$BRANCH"
git checkout -q "$BRANCH"
git pull --ff-only origin "$BRANCH"

# ---------- сборка и запуск ----------
say "Собираю образы"
docker compose build
say "Запускаю сервисы"
docker compose up -d
docker compose ps

# ---------- проверка ----------
say "Проверяю модуль мерч-кодов"
ok=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if docker compose exec -T merch python -c \
    "import urllib.request as u; u.urlopen('http://localhost:8000/healthz', timeout=3)" 2>/dev/null; then
    ok=1
    break
  fi
  sleep 2
done
[ -n "$ok" ] || { docker compose logs --tail 30 merch; fail "merch не ответил на /healthz — логи выше"; }
echo "merch отвечает на /healthz."

say "Готово"
echo "Дальше:"
echo "  1) Убедитесь, что A-запись $DOMAIN указывает на IP этого сервера, а порты"
echo "     80/443 открыты — сертификат Let's Encrypt Caddy выпустит сам (до ~1 мин)."
echo "  2) Откройте https://$DOMAIN и выпустите тестовый номер (вкладка Serial, PIN production),"
echo "     проверьте его на вкладке Check, при желании удалите в журнале."
echo "  3) Заберите бэкап ключа шифрования в надёжное место ОТДЕЛЬНО от бэкапов базы:"
echo "     docker compose cp merch:/app/data/serial-key.backup.json ~/serial-key.backup.json"
