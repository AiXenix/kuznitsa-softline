from io import BytesIO
import json
import pytest

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from kuznitsa.analytics import kpi,replay,rollup,dashboard
from kuznitsa.analytics.controls import RuleControls
from kuznitsa.analytics.store import Journal,result_cards
from kuznitsa.app import create_app
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import ingest,ordered_files
from kuznitsa.schema import Request

FILES=ROOT/"docs/admin_examples/import"


def test_external_reports(cfg,tmp_path,monkeypatch):
    j=Journal(tmp_path/"kuznitsa.sqlite")
    e=Engine.open(cfg,journal=j,controls=RuleControls(j))
    hits_file=tmp_path/"external.tsv"
    lines=(FILES/"vendor-actions.tsv").read_text().splitlines()
    hits_file.write_text("\n".join([lines[0],*reversed(lines[1:])]))
    parts=ordered_files([hits_file,FILES/"vendor-traffic.tsv"])
    visits,hits=[ingest(e,f) for f in parts]
    assert visits["visits"]==1 and hits["observed_searches"]==1 and hits["zero_rate"]==0
    assert hits["skip_reasons"] and hits["rows_read"]==4 and hits["rows_accepted"]==3
    assert j.rows("SELECT session_id,type,card_id FROM events ORDER BY ts")==[
        {"session_id":"98001","type":kind,"card_id":"shield:pro"} for kind in ("click","order")]
    sheet=ingest(e,FILES/"onsite-report.xlsx")
    assert sheet["searches"]==14 and sheet["observed_empty"]==8 and sheet["skipped"]==1
    crm=ingest(e,FILES/"supplier-search.csv")
    assert crm["searches"]==2 and crm["ignored"]==["Регион склада"] and crm["zero_rate"]==.5
    assert len(json.loads((tmp_path/"history_report.json").read_text())["files"])==4
    run=replay.run(e,limit=1)
    snapshot=kpi.report(j)
    assert run["frequency"]==snapshot["totals"]["searches"]<17
    assert run["labeled"]==1 and snapshot["totals"]["order_denominator"]==2
    for pair in snapshot["pairs"]:
        assert pair["delta_text"] and pair["scope_text"] and pair["tone"] in {"good","bad","neutral"}
    complete=replay.run(e)
    assert complete["frequency"]==17 and complete["labeled"]==1
    small=kpi.report(j)
    assert small["totals"]["revenue_rub"]==223000
    lead = next(step for step in small["funnel"] if step["key"]=="leads")
    assert lead["count"]==0 and lead["observed"] is False
    assert any("заявках" in note for note in small["coverage_notes"])
    monkeypatch.setattr(rollup,"PACK_AT",1)
    with j.transaction() as db:
        db.execute("DELETE FROM analytics_reports")
    packed=kpi.report(j)
    for key in ("totals","pairs","order_amounts","slices","funnel","lost_orders"):
        assert packed[key]==small[key],key
    (tmp_path/"import_report.json").write_text('{"ai":{"usd":0.006,"forecast_usd":5}}')
    (tmp_path/"import_ai.jsonl").write_text('{"choice":"other","accepted":false,"probability":0.2}\n')
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(e,cfg)) as api:
        evidence=api.get("/api/admin/ingest").json()
        assert evidence["classification_usd"]==evidence["catalog"]["ai"]["usd"]==.006
        assert evidence["forecast_usd"]==5
        assert len(evidence["review"])==1 and len(evidence["history"])==4
        for role,section in [("head_ecom","Онлайн-заказы"),("product_manager","Рост за 30 дней"),
                             ("content_manager","Исправить карточки"),("customer","Показатели"),("ecom_manager","Период")]:
            for fmt in ("md","xlsx"):
                res=api.get("/api/admin/digest",params=dict(role=role,format=fmt))
                assert res.status_code==200 and fmt in res.headers["content-disposition"]
                if fmt=="md":
                    assert section in res.text and "Что сделать сегодня" in res.text
                else:
                    book = load_workbook(BytesIO(res.content),read_only=True)
                    assert section in book.sheetnames
                    if role=="head_ecom":
                        assert any(row[0]=="Цель в первых пяти" for row in book["До и после"].values)
                    if role=="ecom_manager":
                        assert any("заявк" in row[0].lower() for row in book["Воронка"].values)
                    book.close()


def test_naive_sku_and_family_identity(engine):
    r=engine.search(Request(q="SHI NOR",mode="naive"))
    for c in result_cards(r):
        offer=engine.catalog.offers_by_id[c["offer"]["offer_id"]]
        assert c["card_id"]=="sku:"+offer.offer_id
        assert c["card_ref"]==offer.card_id
    reference=dashboard.search_reference(engine,"SHI NOR")
    assert reference["search_id"]==r["search_id"]
    assert [x["card_id"] for x in reference["items"]]==[c["card_ref"] for c in result_cards(r)]


def test_visit_purchase_and_later_hits(cfg,tmp_path):
    e=Engine.open(cfg,journal=Journal(tmp_path/"orders.sqlite"))
    visits=tmp_path/"202611.csv"
    visits.write_text('ym:s:visitID;ym:s:dateTime;ym:s:startURL;ym:s:watchIDs;ym:s:purchaseID;ym:s:purchaseRevenue\n'
                      "v105;2026-11-07 09:12:00;https://example.org/search?q=щит;[1105];['kp10'];[250000]\n")
    report=ingest(e,visits)
    assert report["searches"]==1 and report["events"]==1 and report["period"]
    hits=tmp_path/"logs.jsonl"
    hits.write_text(json.dumps({"ym:pv:watchID":"1105","ym:pv:dateTime":"2026-11-07 09:12:00",
                               "ym:pv:URL":"https://example.org/search?q=щит","ym:pv:params":{"search_results_count":5}}))
    ingest(e,hits)
    ingest(e,visits)
    totals=kpi.report(e.journal)["totals"]
    assert totals["searches"]==totals["orders"]==totals["revenue_denominator"]==1
    assert totals["revenue_rub"]==250000


def test_empty_target_coverage(cfg,tmp_path):
    j=Journal(tmp_path/"queries.sqlite")
    e=Engine.open(cfg,journal=j,controls=RuleControls(j))
    ingest(e,FILES/"onsite-report.xlsx")
    # Архивная рекомендация до обновления словаря не может менять выдачу.
    from kuznitsa.analytics.insights import listing,transition
    old=dict(id="stale",type="add_synonym",dataset="import",evidence={"sample_queries":["щит"]},
             action=dict(kind="synonym",conditions={},payload_json=dict(kind="text",phrase="щит",to="щит")))
    j.insert("insights",dict(id="stale",type="add_synonym",status="new",body=json.dumps(old)))
    assert not listing(j)
    with pytest.raises(ValueError,match="уже в первой пятёрке"):
        transition(e,"stale","apply")
    assert not e.controls.rules()
    run=replay.run(e)
    result=kpi.report(j)
    duplicate=ingest(e,FILES/"onsite-report.xlsx")
    assert duplicate["duplicates"]==14
    assert kpi.report(j)["comparison"]["run_id"]==run["id"]
    assert run["labeled"]==0 and all(p["key"]!="top5_hit" for p in result["pairs"])
    assert any("Топ-5 скрыт" in message for message in result["coverage_notes"])


def test_mixed_mock_builds_hide_comparison(cfg,tmp_path,monkeypatch):
    from kuznitsa.analytics.lineage import save_mock
    from kuznitsa.analytics.store import dump
    j=Journal(tmp_path/"snapshot.sqlite")
    e=Engine.open(cfg,journal=j,controls=RuleControls(j))
    (tmp_path/"catalog.jsonl").write_bytes((cfg.data/"catalog.jsonl").read_bytes())
    with j.transaction() as db:
        db.execute("INSERT INTO kv VALUES ('settings:history_source','mock',0)")
        j.insert("searches",dict(search_id="s_mock_a",session_id="v",ts=100,source="history",engine="legacy",q_raw="щит",
                 q_norm="щит",q_corrected="щит",zero=1,n_cards=0,top_cards_json="[]"))
    old=kpi.report(j)
    assert old["note"] and old["pairs"]==[] and old["comparison"] is None
    truth=dump(dict(search_id="s_mock_a",q="щит",target_family="shield"))
    with j.transaction() as db:
        save_mock(db,tmp_path,[truth],37,"2026-11-21")
    result=replay.run(e)
    assert result["frequency"]==result["labeled"]==1
    assert kpi.report(j)["comparison"]["run_id"]==result["id"]
    original=(tmp_path/"mock_truth.jsonl").read_bytes()
    (tmp_path/"mock_truth.jsonl").write_bytes(original.replace(b'shield',b'broken'))
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(e,cfg)) as api:
        stale=api.get("/api/admin/kpi").json()
        assert stale["data_status"]=="incompatible" and "разметки" in stale["note"]
        assert not stale["pairs"] and stale["comparison"] is None
        assert api.get("/api/admin/replay/"+result["id"]).json()["status"]=="incompatible"
        assert stale["note"] in api.get("/api/admin/digest?role=head_ecom").json()["items"][0]["text"]
        assert stale["note"] in api.get("/api/admin/digest?format=md").text
        assert api.get("/api/admin/digest?format=xlsx").content.startswith(b"PK")
    (tmp_path/"mock_truth.jsonl").write_bytes(original)
    assert kpi.report(j)["pairs"]
    j.db.execute("DELETE FROM kv WHERE key=?",("settings:paired_build:"+result["id"],))
    assert "Парный прогон" in kpi.report(j)["note"]
    j.db.execute("UPDATE searches SET q_raw='другая фраза' WHERE search_id='s_mock_a'")
    assert "разметки" in kpi.report(j)["note"]
