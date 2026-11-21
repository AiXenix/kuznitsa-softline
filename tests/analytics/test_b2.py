import statistics
import subprocess
import sys

from fastapi.testclient import TestClient
from kuznitsa.analytics import insights,replay
from kuznitsa.analytics.controls import RuleControls
from kuznitsa.analytics.store import Journal
from kuznitsa.app import create_app
from kuznitsa.config import Config,ROOT
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import ingest
from kuznitsa.mock.querylog_gen import generate


def test_organizer_files_to_console(cfg,tmp_path,monkeypatch):
    j=Journal(tmp_path/"history.sqlite")
    shop=Engine.open(cfg,journal=j,controls=RuleControls(j))
    src=ROOT/"docs/admin_examples/import"
    for name,n in [("legacy.csv",3),("weekly.xlsx",4),("metrika.tsv",10),("events.jsonl",1)]:
        report=ingest(shop,src/name)
        assert report["searches"]==n and report["recognized"]
        assert ingest(shop,src/name)["duplicates"]==n
    assert j.rows("SELECT count(*) n FROM events WHERE type='exit'")[0]["n"]==3
    run=replay.run(shop,"fast",10)
    assert run["frequency"]==18 and run["labeled"]==0
    insights.discover(shop)
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(shop,cfg)) as api:
        r=api.get("/api/admin/kpi").json()
        assert r["totals"]["searches"]==18 and r["totals"]["revenue_rub"]==108000
        assert r["totals"]["conversion"]==1/3 and r["coverage_notes"]
        assert r["slices"]["day"][-1]["partial"]
        assert api.get("/api/admin/digest?role=head").status_code==422
        assert "slices" not in api.get("/api/admin/kpi?view=overview").json()
        assert len(api.get("/api/admin/ingest").json()["history"])==4
        sid=api.post("/api/search",json={"q":"страж","mode":"fast","source":"gallery"}).json()["search_id"]
        latest=api.get("/api/admin/queries?kind=recent&limit=1").json()["items"][0]
        assert latest["search_id"]==sid and "n_cards" in latest
        assert api.get("/api/admin/kpi").json()["totals"]["searches"]==18


def test_custom_header_mapping(cfg,tmp_path):
    j=Journal(tmp_path/"journal.sqlite")
    e=Engine.open(cfg,journal=j,controls=RuleControls(j))
    source=tmp_path/"source.csv"
    source.write_bytes("Искомый текст;Показы;Остаток выдачи\nстраж;2;0\n".encode("cp1251"))
    mapping=tmp_path/"map.yaml"
    mapping.write_text("Искомый текст: q\nПоказы: count\nОстаток выдачи: n_cards\n")
    result=ingest(e,source,mapping)
    assert result["searches"]==2 and result["recognized"]==["Искомый текст","Остаток выдачи","Показы"]
    assert j.rows("SELECT sum(zero) n FROM active_history")==[{"n":2}]


def test_fresh_history_paired_and_recovery(tmp_path,monkeypatch):
    monkeypatch.setenv("KZ_DATA_DIR",str(tmp_path/"data"))
    # Индексы контентно-адресуемые. Каталог и журнал всегда создаются заново.
    monkeypatch.setenv("HF_HUB_OFFLINE","1")
    for cmd in ("build-mock","build-index"):
        subprocess.run([sys.executable,"-m","kuznitsa.cli",cmd],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    cfg=Config()
    j=Journal(cfg.data/"kuznitsa.sqlite")
    e=Engine.open(cfg,journal=j,controls=RuleControls(j))
    generate(e,today="2026-11-21")
    run=replay.run(e,"fast",3000)
    assert .25<=run["before_zero"]/run["frequency"]<=.35
    assert .03<=run["after_zero"]/run["frequency"]<=.08
    assert .45<=run["before_top5"]/run["labeled"]<=.55
    assert run["after_top5"]/run["labeled"]>=.85
    amounts=[r["value"] for r in j.rows("SELECT value FROM events WHERE type='order'")]
    assert .02<=len(amounts)/45000<=.04
    assert 80000<=statistics.median(amounts)<=250000
    assert statistics.mean(amounts)<=600000 and max(amounts)<=2500000
    insights.discover(e)
    from tests.analytics.coverage import audit
    stories=audit(j)
    assert sum(bool(ids) for ids in stories.values())>=15
    assert all(stories[k] for k in ("INS-10","INS-11","INS-12"))
    items=insights.listing(j)
    end=j.rows("SELECT max(ts) ts FROM active_history")[0]["ts"]
    turnover=j.rows("""SELECT sum(value) rub FROM events JOIN active_history s USING(search_id)
                       WHERE type='order' AND s.ts>?""",(end-30*86400,))[0]["rub"]
    effects=[i["impact"]["expected_rub"] for i in items]
    assert max(effects)<=turnover*.25 and sum(effects)<=turnover
    assert all(i["impact"]["formula_note"] for i in items)
    from kuznitsa.analytics import gaps
    clusters={r["key"] for r in gaps.report(e)["items"]}
    assert not clusters.intersection({"ghjlktybt","regbnm","lkz","bazovyi","ghjlkbnm","fpjdsq","premise","rfg","god","dlya","резервилка"})
    assert any(i["type"]=="merch_rule" and any("касс" in q for q in i["evidence"]["sample_queries"]) for i in items)
    demo=next(i for i in items if i["action"]["payload_json"].get("phrase")=="резервилка")
    assert demo["status"]=="new"
    assert insights.transition(e,demo["id"],"apply")["status"]=="applied"
    verified=insights.transition(e,demo["id"],"verify")
    assert verified["status"]=="verified"
    for q,r in verified["verification"]["before"].items():
        after=verified["verification"]["after"][q]
        assert r["n_cards"]==0 and after["n_cards"]>0
        assert any(c['card_id'] in e.catalog.by["family"]["cyber_backup"] for c in after["cards"][:5])
        assert j.detail(r["search_id"])["understood"]["zero_reason"]=="unknown_term"
        assert j.detail(r["search_id"])["n_cards"]==0 and j.detail(after["search_id"])["n_cards"]>0
