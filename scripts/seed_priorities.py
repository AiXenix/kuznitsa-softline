#!/usr/bin/env python3
"""Добавить выключенные примеры приоритетов в журнал снимка."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kuznitsa.analytics import priorities
from kuznitsa.analytics.store import Journal
from kuznitsa.config import Config


EXAMPLES = (
    dict(id="seed-gov-antivirus", title="Отечественные антивирусы для госзаказчиков",
         target=dict(categories=["endpoint_security"], tags=["domestic"]),
         scope=dict(segments=["gov"]), action=dict(boost=40)),
    dict(id="seed-backup-promo", title="Акция на резервное копирование до 31.12",
         target=dict(categories=["backup_recovery"], families=["rubackup"]), scope={"to": "2026-12-31"},
         action=dict(boost=20, public_label="Акция"),
         note="До конца декабря продвигаем линейку RuBackup. Запрос для показа — «резервное копирование», профиль — Гость."),
    dict(id="seed-vendor-cap", title="Не больше двух карточек одного вендора в первой пятёрке",
         target=dict(vendors=["kaspersky"]), action=dict(max_in_top=dict(n=5, k=2)),
         note="В примере выбран Kaspersky. Для другого вендора измените направление."),
)


def seed(path, dry_run=False):
    rules = [priorities.validate(dict(rule, enabled=False, author="seed")) for rule in EXAMPLES]
    if dry_run:
        existing = set()
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='priorities'").fetchone():
                    existing = {r[0] for r in db.execute("SELECT id FROM priorities")}
        return [r["title"] for r in rules if r["id"] not in existing]

    path.parent.mkdir(parents=True, exist_ok=True)
    journal = Journal(path)
    try:
        with journal.transaction():
            existing = {r["id"] for r in priorities.all_rules(journal)}
            pending = [r for r in rules if r["id"] not in existing]
            for rule in pending:
                priorities.change(journal, "create", rule, ident=rule["id"], author="seed")
        return [r["title"] for r in pending]
    finally:
        journal.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=Config().data / "kuznitsa.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    titles = seed(args.journal, args.dry_run)
    print(("К добавлению" if args.dry_run else "Добавлено") + f" правил — {len(titles)}")
    for title in titles:
        print(title)


if __name__ == "__main__":
    main()
