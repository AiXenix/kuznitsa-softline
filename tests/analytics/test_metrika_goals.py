import json
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from kuznitsa.app import create_app
from kuznitsa.analytics.kpi import report
from kuznitsa.analytics.store import Journal
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import ingest, sniff

GOALS = ROOT / "docs/admin_examples/import/goals-by-day.csv"


def steps(result):
    return {s["key"]:s for s in result["funnel"]}


def test_daily_goals_then_observations(cfg,tmp_path,monkeypatch):
    j = Journal(tmp_path/"sample.sqlite")
    e = Engine.open(cfg, journal=j)
    hint = sniff(GOALS)
    assert hint["kind"]=="metrika_goals"
    assert set(hint["columns"].values())=={"ts","cart","order","lead"}
    imported = ingest(e, GOALS)
    assert imported["rows_accepted"]==2 and imported["skip_reasons"]=={"Итоговая строка отчёта":1}
    assert imported["report_metrics"]=={"cart":18,"order":5,"lead":3}
    assert imported["searches"]==imported["events"]==0
    for _ in range(2):
        snap = report(j)
        assert [steps(snap)[key]["count"] for key in ("carts","orders","leads")]==[18,5,3]
        assert steps(report(j,day="2026-11-18"))["orders"]["count"]==2
        assert steps(report(j,segment="smb"))["orders"]["count"]==0
        ingest(e, GOALS)
    log = tmp_path/"search.csv"
    log.write_text("Дата;Запрос;Заказы;Корзины;Число результатов\n17.11.2026;страж;1;1;1\n18.11.2026;щит;0;0;2\n")
    ingest(e, log)
    snap = report(j)
    assert [steps(snap)[key]["count"] for key in ("carts","orders","leads")]==[1,1,3]
    assert snap["funnel_daily"][1]["stages"]["order"]["journal"]==0
    saved = json.loads((tmp_path/"history_report.json").read_text())["files"]
    entry = next(r for r in saved if r["kind"]=="metrika_goals")
    assert entry["comparison"]["order"]=={"metrika":5,"journal":1,"delta":4}
    assert "Дней с расхождениями — 2" in entry["reconciliation_text"]
    assert "\n" not in entry["reconciliation_text"] and entry["missing"].count(entry["reconciliation_text"])==1
    assert ingest(e, GOALS)["comparison"]==entry["comparison"]
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(e,cfg)) as api:
        day = api.get("/api/admin/kpi", params={"day":"2026-11-18"}).json()
        assert day["funnel_daily"][0]["stages"]["order"]["count"]==0
        assert steps(day)["leads"]["metrika_count"]==2
        receipt = api.get("/api/admin/ingest").json()["history"]
        assert any(entry["reconciliation_text"] in r["missing"] for r in receipt)
        xlsx = api.get("/api/admin/digest?role=ecom_manager&format=xlsx")
        workbook = load_workbook(BytesIO(xlsx.content), read_only=True)
        assert ("2026-11-18","Заказ",2,0,0,"Журнал") in workbook["Цели по дням"].values
        workbook.close()


def test_named_goal_rows_and_overlap(cfg,tmp_path):
    path = tmp_path/"daily.csv"
    path.write_bytes(("Отчёт;Достижение целей\nДень;Название цели;Количество достижений\n"
                      "17.11.2026;Заказ;4\n17.11.2026;Заявка;2\n"
                      "17.11.2026;Заявка;2\nне дата;Корзина;3\n18.11.2026;Заказ;3,4\n").encode("cp1251"))
    assert sniff(path)["kind"]=="metrika_goals"
    j = Journal(tmp_path/"sample.sqlite")
    e = Engine.open(cfg, journal=j)
    ingest(e, GOALS)
    r = ingest(e,path)
    assert r["rows_accepted"]==2 and sum(r["skip_reasons"].values())==3
    snap = report(j)
    assert [steps(snap)[k]["count"] for k in ("carts","orders","leads")]==[18,6,4]
    assert steps(snap)["orders_or_leads"]["count"]==0
