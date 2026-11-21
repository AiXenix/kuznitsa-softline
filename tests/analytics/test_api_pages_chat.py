import json
from fastapi.testclient import TestClient

from kuznitsa.analytics import insights
from kuznitsa.analytics.store import Journal
from kuznitsa.app import create_app
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import ingest, ingest_files, sniff
from kuznitsa.plans.knowledge import KnowledgeIndex


EXAMPLES = ROOT/"docs/admin_examples"
SOURCES = EXAMPLES/"import/api-chat"

def page(path, dimension, metric, offset, pairs, total_rows, total, **kwargs):
    obj = dict(query=dict(ids=[73], dimensions=[dimension], metrics=[metric],
                          date1="2026-11-01", date2="2026-11-15", offset=offset, limit=2, **kwargs),
               data=[dict(dimensions=[dict(name=k)],metrics=[v]) for k,v in pairs],
               total_rows=total_rows, totals=[total], sampled=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2))
    return path


def test_api_report_pages(cfg,tmp_path,monkeypatch):
    engine = Engine.open(cfg,journal=Journal(tmp_path/"page.db"))
    a,b,z = (SOURCES/name for name in ("first.json","second.json","urls.json"))
    assert sniff(b)["kind"] == "metrika_api"
    assert not ingest(engine,b)["complete"]
    receipts=ingest_files(engine,[z,a,b])
    assert [(r["file"],r["rows_accepted"]) for r in receipts]==[(z.name,2),(a.name,2),(b.name,1)]
    reports = json.loads((tmp_path/"history_report.json").read_text())["files"]
    assert len(reports)==2
    phrase = next(r for r in reports if r["external_phrases"])
    assert phrase["complete"] and phrase["sampled"] and phrase["rows_accepted"]==3
    assert phrase["duplicates"]==1 and phrase["pages"]==2 and phrase["files"]==[a.name,b.name]
    assert phrase["report_metrics"]=={"ym:s:visits":15}
    assert [i["count"] for i in phrase["external_phrases"]]==[8,4,3] and phrase["site_phrases"]==[]
    onsite = next(r for r in reports if r["site_phrases"])
    assert onsite["site_phrases"]==[dict(q="backup pro",count=10,metric="ym:pv:pageviews")]
    assert onsite["external_phrases"]==[]
    assert engine.journal.rows("SELECT count(*) n FROM active_history")[0]["n"]==0
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(engine,cfg)) as api:
        assert len(api.get("/api/admin/ingest").json()["external_phrases"])==1


def test_support_chat_end_to_end(cfg,tmp_path,monkeypatch):
    journal = Journal(tmp_path/"chat.db")
    engine = Engine.open(cfg,journal=journal)
    # Одна контрольная статья FAQ совпадает с обращением.
    question = "Как активировать электронный ключ?"
    engine.kb.rows["faq"]["activation"] = dict(questions=[question],answer="Откройте меню активации.")
    engine.knowledge = KnowledgeIndex(engine.kb,engine.lex)
    path = SOURCES/"support.csv"
    assert sniff(path)["kind"]=="support_chat"
    log = tmp_path/"search.csv"
    log.write_text("Дата;Запрос;Число результатов\n15.11.2026;страж;2\n")
    ingest(engine,log)
    for _ in range(2):
        r = ingest(engine,path)
        assert r["rows_accepted"]==7 and r["skipped"]==1
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(engine,cfg)) as api:
        summary = api.get("/api/admin/support").json()
        assert summary == json.loads((EXAMPLES/"support.json").read_text())
        assert (summary["messages"], summary["clients"], summary["unanswered_count"])==(7,3,6)
        assert summary["products"][0]==dict(product="North Shield",messages=4)
        assert question not in [x["question"] for x in summary["unanswered"]]
        assert any(t["topic"]==question for t in summary["topics"])
        assert journal.rows("SELECT count(*) n FROM active_history")[0]["n"]==1
        insights.discover(engine)
        items = [i for i in insights.listing(journal) if i["evidence"].get("source")=="support_chat"]
        assert {i["type"] for i in items}=={"add_product","fix_card"}
        for item in items:
            ev = item["evidence"]
            assert ev["clients"]==2 and len(ev["questions"])==2 and item["impact_text"]
            assert journal.detail(ev["examples"][0]["search_id"])
            assert set(ev["target_card_ids"]).isdisjoint(next(iter(ev["checks"].values()))["top5"])
        assert not any("North Shield" in i["evidence"]["sample_queries"] for i in items)
        assert any(r["kind"]=="support_chat" for r in api.get("/api/admin/ingest").json()["history"])


def test_chat_visible_in_both_roles(tmp_path):
    import shutil
    import subprocess
    import pytest

    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Нужен локальный Chrome")
    html = tmp_path/"roles.html"
    js = """
    import {product,content} from 'ROLES_URL';
    const data={messages:2,clients:2,unanswered_count:1,topics:[{topic:'Поставка',messages:2}],
                products:[{product:'North Shield',messages:2}],
                unanswered:[{question:'Есть ли совместимая версия?',messages:1}],note:'Подбор по FAQ'};
    globalThis.fetch=async url=>new Response(JSON.stringify(url.endsWith('/support')?data:{}));
    const roles=[product,content].map(show=>{
       const panel=document.body.appendChild(document.createElement('main'));
       show(panel,new URLSearchParams());return panel;
    });
    setTimeout(()=>{document.querySelector('output').textContent=roles.every(p=>
       ['Обращения покупателей','Поставка','North Shield','Есть ли совместимая версия?'].every(t=>p.textContent.includes(t)))
       ?'passed':'failed';},100);
    """
    html.write_text('<meta charset="utf-8"><output></output><script type="module">'+
                    js.replace("ROLES_URL",(ROOT/"web/js/admin/roles.js").as_uri())+'</script>')
    run = subprocess.run([chrome,"--headless","--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
                          "--disable-background-networking","--allow-file-access-from-files",
                          "--user-data-dir="+str(tmp_path/"chrome"),"--virtual-time-budget=2000",
                          "--dump-dom",html.as_uri()],capture_output=True,text=True,timeout=30,check=True)
    assert "<output>passed</output>" in run.stdout


def test_api_engine_only_and_inconsistent_rows(cfg,tmp_path):
    engine=Engine.open(cfg,journal=Journal(tmp_path/"stat.db"))
    p=page(tmp_path/"api.json","ym:s:searchEngine","ym:s:bounceRate",1,[("Яндекс",20)],2,20)
    bad=json.loads(p.read_text())
    bad["data"].append(dict(metrics=["?"],dimensions=[dict(name="Другой")]))
    p.write_text(json.dumps(bad))
    r=ingest(engine,p)
    assert r["scope"]=="external" and r["external_phrases"]==[]
    assert r["external_engines"]==[dict(q="Яндекс",count=None,metric=None)]
    assert not r["complete"] and r["skipped"]==1 and r["rows_accepted"]==1
    assert r["report_metrics"]=={"ym:s:bounceRate":20}
    other=page(tmp_path/"filtered.json","ym:s:searchEngine","ym:s:bounceRate",1,[],0,0,filters="a==b")
    ingest(engine,other)
    saved=json.loads((tmp_path/"history_report.json").read_text())["files"]
    assert len(saved)==2 and len({r["report_id"] for r in saved})==2


def test_free_text_mention_and_replacement(cfg,tmp_path):
    from kuznitsa.analytics.support import overview

    j = Journal(tmp_path/"support.db")
    e = Engine.open(cfg,journal=j)
    path=tmp_path/"messages.csv"
    row="2026-11-10;Клиент;Есть ли у вас Zorbium?"
    path.write_text("date;customer;question\n"+row+"\n"+row+"\n")
    assert ingest(e,path)["duplicates"]==1
    assert overview(j)["products"]==[dict(product="Zorbium",messages=1)]
    path.write_text("date;customer;question\n2026-11-11;Клиент;Как оплатить?\n")
    ingest(e,path)
    result=overview(j)
    assert result["messages"]==1 and result["products"]==[]
