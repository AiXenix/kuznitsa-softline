from kuznitsa.analytics import priorities
from kuznitsa.analytics.store import Journal
from scripts.seed_priorities import seed


def test_seed_priorities(tmp_path):
    path = tmp_path / "fresh.sqlite"
    planned = seed(path, dry_run=True)
    assert len(planned) == 3
    assert not path.exists()
    assert seed(path) == planned
    j = Journal(path)
    try:
        assert priorities.active_rules(j) == (3, [])
        rules = priorities.all_rules(j)
        assert [r["title"] for r in rules] == [
            "Отечественные антивирусы для госзаказчиков",
            "Акция на резервное копирование до 31.12",
            "Не больше двух карточек одного вендора в первой пятёрке",
        ]
        gov, promo, cap = rules
        assert gov["target"]["categories"] == ["endpoint_security"]
        assert gov["target"]["tags"] == ["domestic"] and gov["scope"]["segments"] == ["gov"]
        assert promo["scope"]["to"] == "2026-12-31" and promo["target"]["categories"] == ["backup_recovery"]
        assert len(cap["target"]["vendors"]) == 1 and cap["action"]["max_in_top"] == {"k": 2, "n": 5}
        assert {r["author"] for r in priorities.audit(j)["items"]} == {"seed"}
        priorities.change(j, "toggle", ident=rules[0]["id"], author="manager")
        assert seed(path, dry_run=True) == seed(path) == []
        version, active = priorities.active_rules(j)
        assert version == 4 and [r["id"] for r in active] == [rules[0]["id"]]
    finally:
        j.db.close()


def test_backup_promotion_moves_the_first_page(tmp_path):
    from datetime import date, datetime, timezone

    from kuznitsa.analytics.store import result_cards
    from kuznitsa.config import Config
    from kuznitsa.engine import Engine
    from kuznitsa.kb.loader import load
    from kuznitsa.mock.catalog_gen import build
    from kuznitsa.schema import Request

    demo_day = date(2026, 11, 21)
    cfg = Config(data=tmp_path, cache=tmp_path/"cache", embed="off")
    build(cfg, load(cfg.kb), today=demo_day)
    seed(cfg.data/"kuznitsa.sqlite")
    timestamp = datetime(2026, 11, 21, 12, tzinfo=timezone.utc).timestamp()
    engine = Engine.open(cfg, clock=lambda: timestamp)

    def page(profile):
        req = Request(q="резервное копирование", profile_id=profile, source="ui", mode="fast", page_size=5)
        return result_cards(engine.preview(req, priorities=priorities.active_rules(engine.journal)[1]))

    profiles = ("guest", "gov_clinic")
    try:
        before = {profile: page(profile) for profile in profiles}
        priorities.change(engine.journal, "toggle", ident="seed-backup-promo")
        for profile in profiles:
            after = page(profile)
            assert len(before[profile]) == len(after) == 5
            assert sum(a["card_id"] != b["card_id"] for a,b in zip(before[profile],after)) >= 3
            assert [c["score"]["tier"] for c in after] == [c["score"]["tier"] for c in before[profile]]
            assert engine.catalog.cards[after[0]["card_id"]].family == "rubackup"
            for card in after:
                promoted = engine.catalog.cards[card["card_id"]].family == "rubackup"
                assert any(b.get("label") == "Акция" for b in card["badges"]) == promoted
        priorities.change(engine.journal, "toggle", ident="seed-backup-promo")
        for profile in profiles:
            assert [c["card_id"] for c in page(profile)] == [c["card_id"] for c in before[profile]]
    finally:
        engine.close()
        engine.journal.db.close()
