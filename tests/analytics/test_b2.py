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
    run=replay.run(e,"fast")
    assert run["frequency"]==45000
    assert .25<=run["before_zero"]/run["frequency"]<=.35
    assert .03<=run["after_zero"]/run["frequency"]<=.08
    baseline=run["before_top5"]/run["labeled"]
    assert .45<=baseline<=.55
    assert run["after_top5"]/run["labeled"]-baseline>=.20
    assert run["after_top5"]/run["labeled"]>=.85
    amounts=[r["value"] for r in j.rows("SELECT value FROM events WHERE type='order'")]
    assert .02<=len(amounts)/45000<=.04
    assert 80000<=statistics.median(amounts)<=250000
    assert statistics.mean(amounts)<=600000 and max(amounts)<=2500000
    insights.discover(e)
    from tests.analytics.coverage import audit
    stories=audit(j)
    # Устранённый поиском сюжет не должен порождать правило. Проверяем саму
    # выдачу на сохранённых реплеях и сохраняем порог покрытия сюжетов B2.
    solved={}
    for story,(phrase,families) in {
        "INS-01":("адешка",{"ald_pro"}),
        "INS-02":("кэдо",{"hrlink_kedo","onec_kedo"}),
        "INS-10":("аналог teamviewer",{"rudesktop","assistant_remote"}),
        "INS-12":("autocad лицензия цена",{"nanocad_platform"}),
        "INS-14":("миграция active directory на российское",{"ald_pro","red_adm","alt_domain"}),
    }.items():
        import json
        rr=j.rows("SELECT result FROM replay_results WHERE run_id=? AND q=?",(run["id"],phrase))
        first=json.loads(rr[0]["result"])["first"] if rr else []
        solved[story]=any(e.catalog.cards[c].family in families for c in first)
        if story=="INS-14":
            solved[story]=bool(first) and e.catalog.cards[first[0]].family in families
    # Прежняя проблема INS-11 — клики по малому офису в среднем с позиции 4,8.
    # Все три исходных запроса должны выводить такую лицензию уже в первую тройку.
    small_office={"kaspersky_ksos","drweb_small_business"}
    phrases=("антивирус для малого бизнеса","антивирус на 10 пк","антивирус на 15 компьютеров")
    rows=j.rows("SELECT result FROM replay_results WHERE run_id=? AND q IN (?,?,?)",(run["id"],*phrases))
    solved["INS-11"]=len(rows)==len(phrases) and all(
        any(e.catalog.cards[cid].family in small_office for cid in json.loads(row["result"])["first"][:3])
        for row in rows)
    assert sum(bool(ids) or solved.get(story,False) for story,ids in stories.items())>=15
    assert all(stories[k] or solved.get(k) for k in ("INS-10","INS-11","INS-12","INS-17"))
    items=insights.listing(j)
    # INS-08: подтверждение относится к SKU именно из проверенной пятёрки.
    for item in items:
        proof=item["evidence"]
        for q,cards in proof.get("shown_defects",{}).items():
            top=insights.products(j.detail(proof["checks"][q]["search_id"]))[:5]
            displayed={(c["card_id"],c["offer"]["offer_id"]) for c in top}
            assert item["action"]["payload_json"]["field"]=="registry"
            for c in cards:
                assert (c["card_id"],c["offer_id"]) in displayed
                assert e.catalog.offers_by_id[c["offer_id"]].registry is None
    end=j.rows("SELECT max(ts) ts FROM active_history")[0]["ts"]
    turnover=j.rows("""SELECT sum(value) rub FROM events JOIN active_history s USING(search_id)
                       WHERE type='order' AND s.ts>?""",(end-30*86400,))[0]["rub"]
    effects=[i["impact"]["expected_rub"] for i in items]
    assert max(effects)<=turnover*.25 and sum(effects)<=turnover
    assert all(i["impact"]["formula_note"] for i in items)
    from kuznitsa.analytics import gaps
    clusters={r["key"] for r in gaps.report(e)["items"]}
    assert not clusters.intersection({"ghjlktybt","regbnm","lkz","bazovyi","ghjlkbnm","fpjdsq","premise","rfg","god","dlya","резервилка"})
    # Перенаправление по разговорной фразе требует переходов и хотя бы одного
    # заказа именно выбранного после уточнения товара (условия discover).
    phrase="защитить десять касс от вирусов"
    supported=j.rows("""
        SELECT c.card_id FROM active_history s
        JOIN events rf ON rf.search_id=s.search_id AND rf.type='reformulate'
        JOIN active_history nxt ON nxt.session_id=s.session_id
            AND nxt.q_raw=json_extract(rf.payload_json,'$.to') AND nxt.ts>s.ts AND nxt.ts<=s.ts+180
        JOIN events c ON c.search_id=nxt.search_id AND c.type='click'
        LEFT JOIN events o ON o.search_id=nxt.search_id AND o.type='order' AND o.card_id=c.card_id
        WHERE s.q_raw=? AND s.ts>? GROUP BY c.card_id
        HAVING COUNT(DISTINCT s.session_id)>=4 AND COUNT(o.event_id)>0
    """,(phrase,end-30*86400))
    cash_rules=[i for i in items if i["type"]=="merch_rule" and phrase in i["evidence"]["sample_queries"]]
    assert bool(cash_rules)==bool(supported)
    assert all(i["evidence"]["target_card"] in {r["card_id"] for r in supported} for i in cash_rules)
    assert {i["type"] for i in items}==set(insights.ROLES)
    for i in items:
        if i["type"]=="merch_rule":
            assert i["evidence"]["choice_examples"]
            for proof in i["evidence"]["choice_examples"]:
                assert j.rows("SELECT card_id FROM events WHERE event_id=?",(proof["click_event_id"],))[0]["card_id"]==proof["card_id"]
    assert all(i["evidence_text"] and i["impact_text"] for i in items)
    demo=next(i for i in items if i["action"]["payload_json"].get("phrase")=="резервилка")
    assert demo["status"]=="new"
    assert "Карточек — 0" in demo["evidence_text"]
    assert all(i["action"]["payload_json"].get("phrase")!="адешка" for i in items if i["type"]=="add_synonym")
    assert all(x["trial_target_position"]<=5 and x["n_cards"]==0 for x in demo["evidence"]["checks"].values())
    assert insights.transition(e,demo["id"],"apply")["status"]=="applied"
    verified=insights.transition(e,demo["id"],"verify")
    assert verified["status"]=="verified"
    assert all(x["before_n_cards"]==0 and x["after_n_cards"]>0 and x["target_position"]<=5 for x in verified["verification"]["outcomes"])
    for q,r in verified["verification"]["before"].items():
        after=verified["verification"]["after"][q]
        assert r["n_cards"]==0 and after["n_cards"]>0
        assert any(c['card_id'] in e.catalog.by["family"]["cyber_backup"] for c in after["cards"][:5])
        assert j.detail(r["search_id"])["understood"]["zero_reason"]=="unknown_term"
        assert j.detail(r["search_id"])["n_cards"]==0 and j.detail(after["search_id"])["n_cards"]>0
