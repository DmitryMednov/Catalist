"""Подготовка к боевому запуску: очистка тестовых данных и выпуск
производственной партии кодов. Запускается ТОЛЬКО на сервере — ключ
шифрования серийных номеров никогда не покидает его базу:

    docker compose exec merch python -m app.seed_batch --yes

Без --yes скрипт лишь показывает план и ничего не меняет.

Что делает (в одном запуске, по порядку):
  1) удаляет все записи журнала, скидки, кабинеты покупателей и лог
     проверок (пользователи Google, сессии и audit_log сохраняются);
  2) записывает актуальный каталог из app/catalog_seed.py
     (Crystal White, форматы сертификатов A5/A7/A8, фотографии);
  3) выпускает партию: Balloon Cat — 5 цветов по 5 номеров (Dubai),
     Guardian of Cyprus и Guardian of Cyprus S — по 10 номеров (Cyprus);
  4) печатает список кодов и сохраняет его в data/issued-codes.txt.

Нумерация сквозная внутри тиража, чтобы каждый «№ … / тираж» существовал
в одном экземпляре: Balloon Cat — № 001–025 подряд по цветам (тираж 25).
Тираж каждой фигурки Guardian — 100; партия выпускает первые № 001–010
большой и № 001–010 маленькой, дальше номера продолжаются со страницы
/factory (подсказка next-seq).

Скрипт идемпотентен по слотам: уже занятый номер пропускается с пометкой,
поэтому повторный запуск без --reset не создаст дублей.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from . import serials
from .catalog_seed import SEED_CATALOG
from .storage import Storage

# Партия запуска: (изделие, [цвета] или None = все включённые,
#                  номеров на цвет, стартовый №).
# Внутри изделия цвета нумеруются подряд от стартового №.
BATCH_PLAN = [
    ("Balloon Cat", None, 5, 1),
    ("Guardian of Cyprus", None, 10, 1),
    ("Guardian of Cyprus S", None, 10, 1),
]
ISSUED_BY = "seed-batch"


def current_month_index() -> int:
    now = datetime.now(timezone.utc)
    return max(0, min(serials.CAP["month"] - 1,
                      (now.year - serials.BASE_YEAR) * 12 + now.month - 1))


def build_plan(catalog: dict) -> list[dict]:
    """Разворачивает BATCH_PLAN в конкретные слоты по актуальному каталогу."""
    jobs = []
    for product_name, color_names, per_color, start in BATCH_PLAN:
        ti = next((i for i, t in enumerate(catalog["types"]) if t["name"] == product_name), None)
        if ti is None:
            sys.exit(f"каталог не содержит изделия «{product_name}» — обновите catalog_seed")
        t = catalog["types"][ti]
        place = t.get("site")
        if place is None or not (0 <= place < len(catalog["places"])):
            sys.exit(f"у изделия «{product_name}» не задана площадка (site)")
        colors = [(j, c) for j, c in enumerate(t["colors"])
                  if c.get("on") and (color_names is None or c["name"] in color_names)]
        if not colors:
            sys.exit(f"у изделия «{product_name}» нет включённых цветов для партии")
        seq_from = start  # сквозная нумерация по цветам изделия
        for j, c in colors:
            jobs.append({
                "type": ti, "color": j, "place": place,
                "count": per_color, "start": seq_from,
                "product": t["name"], "colorName": c["name"], "hex": c.get("hex"),
                "img": c.get("img"), "sheet": t.get("sheet") or "a5",
                "edition": t.get("edition"), "site": catalog["places"][place]["name"],
            })
            seq_from += per_color
    return jobs


def issue_jobs(store: Storage, jobs: list[dict], month: int) -> tuple[list[dict], list[str]]:
    issued, skipped = [], []
    for job in jobs:
        for seq in range(job["start"], job["start"] + job["count"]):
            fields = serials.Fields(type=job["type"], color=job["color"],
                                    month=month, place=job["place"], seq=seq)
            code = serials.encode_serial(fields, store.key)
            ok = store.insert_record({
                "code": code, "slot": serials.slot_of(fields),
                "type": job["type"], "color": job["color"], "month": month,
                "place": job["place"], "seq": seq,
                "product": job["product"], "colorName": job["colorName"],
                "hex": job["hex"], "img": job["img"], "site": job["site"],
                "sheet": job["sheet"], "edition": job["edition"],
                "issuedBy": ISSUED_BY,
            })
            entry = {**job, "seq": seq, "code": code}
            if ok:
                issued.append(entry)
            else:
                skipped.append(f"{job['product']} / {job['colorName']} № {seq:03d}: слот уже занят")
    return issued, skipped


def render_list(issued: list[dict], month: int, public_url: str, fingerprint: str) -> str:
    """Текст для передачи производителям: коды по изделиям и цветам."""
    lines = [
        "CATALIST production batch of serial numbers",
        f"Issued: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        f" · month on certificate: {serials.month_label(month)}",
        f"Verify any code at: {public_url}/<CODE>  (key {fingerprint})",
        "",
    ]
    group = None
    for e in issued:
        g = (e["product"], e["colorName"])
        if g != group:
            group = g
            lines.append(f"{e['product']} · {e['colorName']} · {e['site']}")
        lines.append(f"  № {e['seq']:03d} / {e['edition']}   {e['code']}")
        if e["seq"] == e["start"] + e["count"] - 1:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Очистка тестовых данных и выпуск партии кодов (на сервере)")
    ap.add_argument("--yes", action="store_true", help="выполнить (без него только показать план)")
    ap.add_argument("--no-reset", action="store_true",
                    help="не удалять существующие данные, только каталог и партия")
    args = ap.parse_args()

    data_dir = os.environ.get("MERCH_DATA_DIR", "data")
    store = Storage(data_dir, os.environ.get("MERCH_SERIAL_KEY") or None)
    public_url = (os.environ.get("MERCH_PUBLIC_URL")
                  or f"https://{os.environ.get('MERCH_DOMAIN', 'code.catalist.world')}").rstrip("/")
    month = current_month_index()
    jobs = build_plan(SEED_CATALOG)
    total = sum(j["count"] for j in jobs)

    print(f"База: {store.path} · записей сейчас: {store.count_records()}")
    print(f"Месяц партии: {serials.month_label(month)} · всего к выпуску: {total}")
    for j in jobs:
        last = j["start"] + j["count"] - 1
        print(f"  {j['product']} / {j['colorName']}: № {j['start']:03d}…{last:03d} из {j['edition']} ({j['site']})")
    if not args.no_reset:
        print("Перед выпуском будут удалены: журнал, скидки, кабинеты, лог проверок.")
    if not args.yes:
        print("\nЭто был план. Запустите с --yes, чтобы выполнить.")
        return

    if not args.no_reset:
        counts = store.reset_business_data()
        store.audit(ISSUED_BY, "seed_reset",
                    ", ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"Очищено: {counts}")
    store.save_catalog(SEED_CATALOG)
    store.audit(ISSUED_BY, "catalog_update", "seed_batch: каталог запуска")

    issued, skipped = issue_jobs(store, jobs, month)
    store.audit(ISSUED_BY, "seed_issue",
                f"{len(issued)} codes, month {serials.month_label(month)}")
    text = render_list(issued, month, public_url, store.key_fingerprint())
    out_path = os.path.join(data_dir, "issued-codes.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    print("\n" + text)
    for s in skipped:
        print("ПРОПУЩЕНО:", s)
    print(f"Выпущено {len(issued)} кодов. Список сохранён: {out_path}")
    print("Сертификаты печатаются на странице /factory (вкладка Register).")


if __name__ == "__main__":
    main()
