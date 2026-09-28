"""Партия запуска: выпуск кодов и обновление каталога на сервере. Ключ
шифрования серийных номеров никогда не покидает сервер, поэтому команда
выполняется только там:

    docker compose exec merch python -m app.seed_batch --yes

Без --yes скрипт лишь показывает план и ничего не меняет.

Что делает запуск с --yes (по порядку):
  1) записывает каталог запуска из app/catalog_seed.py (цвета, фотографии,
     форматы сертификатов, тиражи);
  2) обновляет снимок каталога у УЖЕ выпущенных записей журнала (тираж,
     формат листа, фото) — сами коды не меняются никогда: список,
     отправленный производителям, остаётся действительным;
  3) довыпускает недостающие номера партии; уже занятые слоты не трогает,
     их коды попадают в список как есть (сверяются с расчётными);
  4) печатает полный список партии и сохраняет его в data/issued-codes.txt.

Ничего не удаляется. Полная очистка (журнал, скидки, кабинеты, лог
проверок) выполняется только явным флагом --reset-all и уместна лишь до
боевого запуска, пока коды не разосланы.

Состав партии — BATCH_PLAN ниже: Balloon Cat пять цветов по № 001-005
(тираж 25), Guardian of Cyprus и Guardian of Cyprus S по № 001-010
(тираж каждой 100). Следующие номера выпускаются на странице /factory,
поле Edition number само подсказывает свободный номер.

Месяц партии закреплён: сентябрь 2026 (месяц зашит в код, и коды этой
партии уже у производителей). Новую партию другого месяца выпускайте
через /factory или отдельным планом.
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
#                  номеров на цвет, стартовый №). Нумерация в каждом цвете
# своя, с стартового №: так выглядит список, уже отправленный производителям.
BATCH_PLAN = [
    ("Balloon Cat", None, 5, 1),
    ("Guardian of Cyprus", None, 10, 1),
    ("Guardian of Cyprus S", None, 10, 1),
]
# Sep 2026: (2026-2026)*12 + 9 - 1. Менять нельзя, пока жива эта партия:
# месяц входит в код, и при другом значении скрипт выпустит 45 НОВЫХ кодов.
BATCH_MONTH = 8
ISSUED_BY = "seed-batch"


def build_plan(catalog: dict) -> list[dict]:
    """Разворачивает BATCH_PLAN в конкретные слоты по актуальному каталогу."""
    jobs = []
    for product_name, color_names, per_color, start in BATCH_PLAN:
        ti = next((i for i, t in enumerate(catalog["types"]) if t["name"] == product_name), None)
        if ti is None:
            sys.exit(f"каталог не содержит изделия «{product_name}»: обновите catalog_seed")
        t = catalog["types"][ti]
        place = t.get("site")
        if place is None or not (0 <= place < len(catalog["places"])):
            sys.exit(f"у изделия «{product_name}» не задана площадка (site)")
        colors = [(j, c) for j, c in enumerate(t["colors"])
                  if c.get("on") and (color_names is None or c["name"] in color_names)]
        if not colors:
            sys.exit(f"у изделия «{product_name}» нет включённых цветов для партии")
        for j, c in colors:
            jobs.append({
                "type": ti, "color": j, "place": place,
                "count": per_color, "start": start,
                "product": t["name"], "colorName": c["name"], "hex": c.get("hex"),
                "img": c.get("img"), "sheet": t.get("sheet") or "a5",
                "edition": t.get("edition"), "site": catalog["places"][place]["name"],
            })
    return jobs


def issue_jobs(store: Storage, jobs: list[dict], month: int) -> tuple[list[dict], int, list[str]]:
    """Возвращает (полный список партии, сколько выпущено сейчас, тревоги).

    Занятый слот не трогается: его код читается из журнала и сверяется с
    расчётным. Расхождение возможно только при другом ключе или месяце и
    попадает в тревоги."""
    batch, created, alerts = [], 0, []
    for job in jobs:
        for seq in range(job["start"], job["start"] + job["count"]):
            fields = serials.Fields(type=job["type"], color=job["color"],
                                    month=month, place=job["place"], seq=seq)
            slot = serials.slot_of(fields)
            code = serials.encode_serial(fields, store.key)
            existing = store.find_by_slot(slot)
            if existing:
                if existing["code"] != code:
                    alerts.append(
                        f"{job['product']} / {job['colorName']} № {seq:03d}: в журнале "
                        f"{existing['code']}, расчётный {code}. Проверьте ключ и месяц!")
                batch.append({**job, "seq": seq, "code": existing["code"], "new": False})
                continue
            ok = store.insert_record({
                "code": code, "slot": slot,
                "type": job["type"], "color": job["color"], "month": month,
                "place": job["place"], "seq": seq,
                "product": job["product"], "colorName": job["colorName"],
                "hex": job["hex"], "img": job["img"], "site": job["site"],
                "sheet": job["sheet"], "edition": job["edition"],
                "issuedBy": ISSUED_BY,
            })
            if ok:
                created += 1
            batch.append({**job, "seq": seq, "code": code, "new": bool(ok)})
    return batch, created, alerts


def render_list(batch: list[dict], month: int, public_url: str, fingerprint: str) -> str:
    """Текст для передачи производителям: полный состав партии."""
    lines = [
        "CATALIST production batch of serial numbers",
        f"Listed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        f" · month on certificate: {serials.month_label(month)}",
        f"Verify any code at: {public_url}/<CODE>  (key {fingerprint})",
        "",
    ]
    group = None
    for e in batch:
        g = (e["product"], e["colorName"])
        if g != group:
            group = g
            lines.append(f"{e['product']} · {e['colorName']} · {e['site']}")
        lines.append(f"  № {e['seq']:03d} / {e['edition']}   {e['code']}")
        if e["seq"] == e["start"] + e["count"] - 1:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Партия запуска: каталог, тиражи на выпущенных записях, недостающие коды")
    ap.add_argument("--yes", action="store_true", help="выполнить (без него только показать план)")
    ap.add_argument("--reset-all", action="store_true",
                    help="СНАЧАЛА удалить журнал, скидки, кабинеты и лог проверок "
                         "(только до боевого запуска, пока коды не разосланы)")
    args = ap.parse_args()

    data_dir = os.environ.get("MERCH_DATA_DIR", "data")
    store = Storage(data_dir, os.environ.get("MERCH_SERIAL_KEY") or None)
    public_url = (os.environ.get("MERCH_PUBLIC_URL")
                  or f"https://{os.environ.get('MERCH_DOMAIN', 'code.catalist.world')}").rstrip("/")
    month = BATCH_MONTH
    jobs = build_plan(SEED_CATALOG)
    total = sum(j["count"] for j in jobs)

    print(f"База: {store.path} · записей сейчас: {store.count_records()}")
    print(f"Месяц партии: {serials.month_label(month)} · слотов в партии: {total}")
    for j in jobs:
        last = j["start"] + j["count"] - 1
        print(f"  {j['product']} / {j['colorName']}: № {j['start']:03d}…{last:03d} из {j['edition']} ({j['site']})")
    if args.reset_all:
        print("ВНИМАНИЕ: --reset-all удалит журнал, скидки, кабинеты и лог проверок.")
    else:
        print("Существующие записи не удаляются: обновится тираж на сертификатах,"
              " недостающие номера довыпустятся.")
    if not args.yes:
        print("\nЭто был план. Запустите с --yes, чтобы выполнить.")
        return

    if args.reset_all:
        counts = store.reset_business_data()
        store.audit(ISSUED_BY, "seed_reset",
                    ", ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"Очищено: {counts}")
    store.save_catalog(SEED_CATALOG)
    synced = store.sync_ledger_snapshots(SEED_CATALOG)
    store.audit(ISSUED_BY, "catalog_update", f"seed_batch: каталог запуска, снимков обновлено {synced}")

    batch, created, alerts = issue_jobs(store, jobs, month)
    store.audit(ISSUED_BY, "seed_issue",
                f"{created} new codes, batch {len(batch)}, month {serials.month_label(month)}")
    text = render_list(batch, month, public_url, store.key_fingerprint())
    out_path = os.path.join(data_dir, "issued-codes.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    print("\n" + text)
    for a in alerts:
        print("ТРЕВОГА:", a)
    kept = len(batch) - created
    print(f"Партия: {len(batch)} кодов. Выпущено сейчас: {created}, уже были и не тронуты: {kept}.")
    if synced:
        print(f"Тираж и фото обновлены у {synced} существующих записей (коды не менялись).")
    print(f"Список сохранён: {out_path}")
    print("Сертификаты печатаются на странице /factory (вкладка Register).")


if __name__ == "__main__":
    main()
