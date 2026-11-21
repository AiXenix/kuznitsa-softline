import csv
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from kuznitsa.analytics import priorities
from kuznitsa.analytics.insights import foreign_shortlist
from kuznitsa.analytics.store import Journal
from kuznitsa.app import create_app
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import sniff, ingest_files
from kuznitsa.schema import Request


@pytest.fixture
def shop(cfg, tmp_path):
    return Engine.open(cfg,journal=Journal(tmp_path/"store.sqlite"),clock=lambda:1700000000.)


def test_priority_lifecycle(shop, cfg, tmp_path, monkeypatch):
    j = shop.journal
    reader = Journal(j.path)
    assert priorities.active_rules(reader) == (0,[])
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    monkeypatch.setenv("KZ_ADMIN_TOKEN","test-priorities")
    catalog = list(shop.catalog.cards.values())
    base, promoted = catalog[:2]
    def card(c):
        return dict(card_id=c.id,title=c.title,score=dict(tier=1),offer=dict(offer_id=c.offers[0].offer_id))
    def trial(req, priorities):
        assert req.profile_id=="gov_clinic" and req.mode=="fast"
        cards = [promoted,base] if priorities else [base,promoted]
        return dict(blocks=[dict(type="products",items=list(map(card,cards)))])
    monkeypatch.setattr(shop,"preview",trial,raising=False)
    with j.transaction() as db:
        db.executemany("INSERT INTO searches(search_id,q_raw,q_norm,source,client_id,segment,ts,intent) VALUES (?,?,?,'history',?,?,1700000000,'category')",
                       [(str(i),q,q,profile,seg) for i,(q,profile,seg) in enumerate([
                           ("защита","gov_clinic","gov"),("защита","gov_clinic","gov"),("почта","guest","smb")])])
    rule = dict(title="Защита для госзаказчиков",target=dict(cards=[promoted.id]),scope=dict(segments=["gov"]),
                action=dict(boost=40,criteria=dict(margin=.6,popularity=.4)))
    headers = {"X-Admin-Token":"test-priorities"}
    prefix = "/api/admin/priorities"
    def sample(name,response,code=200):
        assert response.status_code==code,response.text
        data = response.json()
        (tmp_path/("priorities"+name+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
        return data
    with TestClient(create_app(shop,cfg)) as api:
        assert api.post(prefix,json=rule).status_code==403
        # Предпросмотр нового правила не меняет ни версию, ни число поисков.
        preview = sample("-preview",api.post(prefix+"/preview",json={"rule":rule}))
        assert preview["summary"]["searches_affected"]==2
        assert preview["queries"][0]["moved"]==2
        assert preview["queries"][0]["q"]=="защита"
        assert j.rows("SELECT count(*) n FROM searches")[0]["n"]==3
        created = sample("-create",api.post(prefix,json=rule,headers=headers))
        ident = created["id"]
        assert priorities.active_rules(reader)[0]==1
        for wrong in [dict(action=dict(boost=-101)),dict(action=dict(max_in_top=dict(n=5,k=6))),
                      dict(target=dict(tags=["oops"])),dict(scope={"from":"2026-12-01","to":"2026-01-01"})]:
            err=sample("-invalid",api.put(prefix+"/"+ident,json=rule|wrong,headers=headers),400)
            assert err["error"]["code"]=="invalid_rule"
        sample("-update",api.put(prefix+"/"+ident,json=rule|{"note":"Согласовано"},headers=headers))
        snapshot=sample("-export",api.get(prefix+"/export"))
        assert snapshot["items"][0]["note"]=="Согласовано"
        res=shop.search(Request(q="защита",profile_id="gov_clinic",source="ui",mode="fast"))
        res["trace"].append(dict(step="business",detail={"priorities":[{"id":ident}]}))
        res["search_id"]="changed"
        j.search(shop.clock(),Request(q="защита",profile_id="gov_clinic",source="ui"),res,2,None,False)
        stats=sample("",api.get(prefix))["items"][0]["stats"]
        assert stats["searches_in_scope_24h"]==2 and stats["fired_24h"]==1
        sample("-toggle",api.post(prefix+"/"+ident+"/toggle",headers=headers))
        assert priorities.active_rules(reader)==(3,[])
        sample("-delete",api.delete(prefix+"/"+ident,headers=headers))
        assert api.post(prefix+"/import",json=snapshot|{"items":snapshot["items"]*2},headers=headers).status_code==400
        assert priorities.active_rules(reader)==(4,[])
        sample("-import",api.post(prefix+"/import",json=snapshot,headers=headers))
        assert priorities.active_rules(reader)[1][0]["id"]==ident
        history=sample("-audit",api.get(prefix+"/audit"))["items"]
        assert [r["operation"] for r in history]==["import","delete","toggle","update","create"]
        assert history[2]["before"]["enabled"] and not history[2]["after"]["enabled"]


def test_external_history_same_traffic(shop,tmp_path):
    visits, hits, report, raw = [tmp_path/n for n in ("01.tsv","02.tsv","03.xlsx","04.csv")]
    def write(path,rows,delimiter):
        with path.open("w",newline="") as f:
            csv.writer(f,delimiter=delimiter).writerows(rows)
    write(visits,[["ym:s:visitID","ym:s:watchIDs","ym:s:dateTime","ym:s:purchaseID","ym:s:purchaseRevenue"],
                  ["v1","[11,12]","2026-10-04 10:00:00",'["p-72"]','[500]']], "\t")
    write(hits,[["ym:pv:watchID","ym:pv:dateTime","ym:pv:URL","ym:pv:referer"],
                [11,"2026-10-04 10:00:00","https://s.test/find?search_term=shield",""],
                [12,"2026-10-04 10:00:10","https://s.test/product/sku","https://s.test/find?search_term=shield"]],"\t")
    write(raw,[["запрос","момент","визит","найдено"],["shield","2026-10-04 10:00:00","v1",4]],";")
    wb=Workbook()
    for row in [["Реквизиты отчёта"]]*15+[["Фраза внутреннего поиска","Визиты","Отказы","Глубина"],
              ["Итого и средние",1,"0%","2,0"],["shield",1,"0%","2,0"]]:
        wb.active.append(row)
    wb.save(report)
    assert [sniff(f)["kind"] for f in (visits,hits,report,raw)]==["metrika_visits","metrika_hits","metrika_report","search_log"]
    results=ingest_files(shop,[hits,report,visits,raw])
    assert [r["rows_accepted"] for r in results]==[1,1,2,1]
    assert results[-1]["summary_only"] and results[-1]["report_metrics"]["avg_depth"]==2
    assert results[-1]["skip_reasons"]=={"Итоговая строка отчёта":1}
    assert shop.journal.rows("SELECT n_cards FROM active_history")==[{"n_cards":4}]
    assert shop.journal.rows("SELECT type,value FROM events ORDER BY type")==[{"type":"click","value":None},{"type":"order","value":500.}]
    assert len(json.loads((tmp_path/"history_report.json").read_text())["files"])==4
    orders=tmp_path/"sales.csv"
    write(orders,[["Order ID","Order value"],["Z-1",400]],",")
    assert sniff(orders)["kind"]=="orders"
    write(orders,[["код склада","цвет"],[1,2]],",")
    assert sniff(orders)["kind"]=="unknown"


def test_imported_shortlist():
    def proposal(i,product):
        return dict(id=str(i),type="add_product",evidence=dict(examples=[{"search_id":str(i)}],sessions_30d=8,checks={"q":{"top5":[]}}),
                    impact={"expected_rub":i},action={"payload_json":{"product":product}})
    items=[proposal(i,"X "+str(i)) for i in range(55)]
    items.append(proposal(99,"X 54"))
    items.append(proposal(100,"нет подтверждения")|{"evidence":{"examples":[]}})
    result=list(foreign_shortlist(items).values())
    assert len(result)==30 and [i["id"] for i in result[:2]]==["99","53"]


def test_ga4_leads_external_channels(shop,cfg,tmp_path,monkeypatch):
    from kuznitsa.analytics import kpi
    from kuznitsa.config import ROOT
    from kuznitsa.ingest.history import ingest
    src=ROOT/"docs/admin_examples/import"
    ga,crm,external=[src/name for name in ("ga4-bigquery.jsonl","crm-requests.csv","external-acquisition.csv")]
    assert [sniff(p)["kind"] for p in (ga,crm,external)]==["ga4_events","crm_leads","metrika_external_phrases"]
    # До получения истории заявки сохраняются для последующей атрибуции.
    assert ingest(shop,crm)["crm"]["unlinked"]==3
    reports=ingest_files(shop,[external,ga,crm])
    assert [r["rows_accepted"] for r in reports]==[4,2,3]
    assert reports[2]["crm"]==dict(records=3,linked=2,unlinked=1,pipeline_rub=235000)
    assert reports[1]["report_metadata"]["totals"]["visits"]==930
    j=shop.journal
    assert j.rows("SELECT count(*) n FROM active_history")==[{"n":2}]
    assert j.rows("SELECT type, sum(value) amount FROM events WHERE type IN ('order','lead') GROUP BY type ORDER BY type")==[
        dict(type="lead",amount=190000),dict(type="order",amount=84000)]
    assert j.rows("SELECT count(distinct session_id) n FROM active_history")==[{"n":1}]
    result=kpi.report(j)
    funnel={x["key"]:x["count"] for x in result["funnel"]}
    assert (funnel["orders"],funnel["leads"],funnel["orders_or_leads"],result["totals"]["revenue_rub"])==(1,2,2,84000)
    ingest_files(shop,[crm,ga,external])
    assert j.rows("SELECT count(*) n FROM events WHERE type='lead'")==[{"n":2}]
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(shop,cfg)) as api:
        data=api.get("/api/admin/ingest").json()
        assert data["external_phrases"][0]["items"][0]["visits"]==600
        assert data["crm_leads"][0]["linked"]==2


def test_crm_minimal_headings(tmp_path):
    path=tmp_path/"table.csv"
    for field in ("Фраза","Товар"):
        path.write_text(f"Дата;Клиент;{field};Сумма\n17.11.2026;Клиент 1;Почта;40000")
        assert sniff(path)["kind"]=="crm_leads"
