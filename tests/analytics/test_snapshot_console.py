import json
import shutil
from dataclasses import replace

from fastapi.testclient import TestClient

from kuznitsa.analytics import replay
from kuznitsa.analytics.lineage import save_mock, warning
from kuznitsa.analytics.store import Journal, dump
from kuznitsa.app import create_app
from kuznitsa.engine import Engine


def test_moved_snapshot_preserves_pairs_and_independent_history(cfg, tmp_path, monkeypatch):
    build = tmp_path / "build"
    build.mkdir()
    shutil.copyfile(cfg.data / "catalog.jsonl", build / "catalog.jsonl")
    monkeypatch.setenv("KZ_ADMIN_OPEN", "1")
    build_cfg = replace(cfg, data=build, cache=build / "cache")
    engine = Engine.open(build_cfg)
    j = engine.journal
    with j.transaction() as db:
        db.execute("INSERT INTO kv VALUES ('settings:history_source','mock',0)")
        labels = []
        for i, q in enumerate(["щит", "щит", "антивирус"]):
            ident = f"s_mock_feed_{i}"
            j.insert("searches", dict(search_id=ident, session_id=ident, source="history",
                                      engine="legacy", ts=i*86400+22*3600, q_raw=q,
                                      n_cards=0, zero=1, top_cards_json="[]"))
            labels.append(dump(dict(search_id=ident, q=q, target_family="shield")))
        save_mock(db, build, labels, 1, "1970-01-04", model="feed")
    run = replay.run(engine, limit=1)
    with TestClient(create_app(engine, build_cfg)) as api:
        expected = api.get("/api/admin/kpi").json()
    assert run["frequency"] == 2 and expected["pairs"]
    engine.close()
    j.db.close()

    served = tmp_path / "served"
    shutil.copytree(build, served, copy_function=shutil.copyfile)
    with TestClient(create_app(cfg=replace(cfg, data=served, cache=tmp_path / "new-cache"))) as api:
        k = api.get("/api/admin/kpi").json()
        assert k["comparison"]["run_id"] == run["id"]
        assert k["pairs"] == expected["pairs"] and k["lost_orders"] == expected["lost_orders"]
        chart = api.get("/api/admin/ui/history-days").json()
        assert chart["period"] == dict(start="1970-01-02", end="1970-01-04")
        assert [x["searches"] for x in chart["items"]] == [1, 1, 1]
        journal = api.app.state.engine.journal
        receipt_key = "settings:paired_build:" + run["id"]
        receipt = json.loads(journal.rows("SELECT value FROM kv WHERE key=?", (receipt_key,))[0]["value"])
        receipt["method"] = "older"
        journal.db.execute("UPDATE kv SET value=? WHERE key=?", (dump(receipt), receipt_key))
        stale = api.get("/api/admin/kpi").json()
        assert stale["data_status"] == "incompatible" and stale["pairs"] == []
        assert "код метода сравнения" in stale["note"]
        journal.db.execute("DELETE FROM analytics_reports")
        assert api.get("/api/admin/ui/history-days").json() == chart


def test_wrong_snapshot_reports_missing_history(tmp_path):
    j = Journal(tmp_path / "kuznitsa.sqlite")
    j.insert("replays", dict(id="old", mode="fast", limit_n=0))
    j.insert("searches", dict(search_id="service", source="eval", ts=100))
    assert "нет поисков магазина" in warning(j)
