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
