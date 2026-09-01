#!/usr/bin/env bash
# Бэкап модуля мерч-кодов: консистентный снимок SQLite + копия ключа.
#
# Разовый запуск:      ./deploy/backup.sh            → ~/catalist-backups/merch-ДАТА.db
# Другая папка:        ./deploy/backup.sh /mnt/backups
# Ежедневно в 03:20 (установка cron одной командой):
#   (crontab -l 2>/dev/null; echo "20 3 * * * $HOME/Catalist/deploy/backup.sh >> $HOME/catalist-backups/backup.log 2>&1") | crontab -
#
# Ротация: файлы старше CATALIST_BACKUP_KEEP_DAYS дней (по умолчанию 14) удаляются.
# ВАЖНО: папку с бэкапами стоит периодически скачивать с сервера (scp) —
# бэкап на том же диске не спасает от гибели самого сервера. Ключ
# serial-key.backup.json храните отдельно от бэкапов базы.
set -euo pipefail

cd "$(dirname "$0")/.."
DEST="${1:-$HOME/catalist-backups}"
KEEP_DAYS="${CATALIST_BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%F-%H%M)"

mkdir -p "$DEST"

# консистентный снимок работающей базы (WAL): VACUUM INTO средствами Python
docker compose exec -T merch python -c "
import os, sqlite3
try: os.remove('/app/data/merch-backup.db')
except FileNotFoundError: pass
sqlite3.connect('/app/data/merch.db').execute(\"VACUUM INTO '/app/data/merch-backup.db'\")
"
docker compose cp merch:/app/data/merch-backup.db "$DEST/merch-$STAMP.db"
docker compose exec -T merch rm -f /app/data/merch-backup.db

# копия ключа кладётся рядом на случай восстановления с нуля,
# но основное хранение ключа — отдельно от этих бэкапов
docker compose cp merch:/app/data/serial-key.backup.json "$DEST/serial-key.backup.json" >/dev/null 2>&1 || true

find "$DEST" -maxdepth 1 -name 'merch-*.db' -mtime +"$KEEP_DAYS" -delete

SIZE="$(du -h "$DEST/merch-$STAMP.db" | cut -f1)"
COUNT="$(find "$DEST" -maxdepth 1 -name 'merch-*.db' | wc -l | tr -d ' ')"
echo "$(date '+%F %T') backup ok: $DEST/merch-$STAMP.db ($SIZE), всего копий: $COUNT"
