import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from kuznitsa.analytics.controls import RuleControls
from kuznitsa.analytics.kpi import loss_by_search
from kuznitsa.analytics.store import Journal,dump
from kuznitsa.analytics.cost import report
from kuznitsa.app import create_app
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import ingest
from kuznitsa.schema import Request


@pytest.fixture
def shop(cfg,tmp_path):
    j=Journal(tmp_path/"journal.sqlite")
    return Engine.open(cfg,journal=j,controls=RuleControls(j))


def test_journal_snapshot_and_threads(shop):
    r=shop.search(Request(q="страж",mode="naive",explain=False))
    j=shop.journal
    r["cost"].update(llm_calls=2,usd=.2,cached=1)
    r["engine"]="kuznitsa"
    r["understood"]["inherited"]={"from_search_id":"parent"}
    def write(i):
        j.search(1,Request(q="страж"),dict(r,search_id=str(i)),1,None,False)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(write,range(20)))
    row=j.rows("SELECT * FROM searches WHERE search_id='1'")[0]
    assert (row["prev_search_id"],row["llm_cost_usd"],row["cached"])==("parent",.2,1)
    assert j.detail(r["search_id"])["trace"]
    assert isinstance(row["response_z"],bytes)
    with pytest.raises(sqlite3.IntegrityError):
        j.event(0,dict(search_id="missing",type="click"))


def test_controls_tiers(shop):
    c=shop.controls
    cards=[dict(card_id=k,score=dict(tier=t,score=n)) for k,t,n in [("a",0,1),("b",1,.9),("c",1,.8)]]
    c.save("boost",{"segment":"smb"},{"card_id":"c","factor":2})
    assert c.merch({"segment":"gov"},cards)["cards"]==cards
    assert [v["card_id"] for v in c.merch({"segment":"smb"},cards)["cards"]]==["a","c","b"]
    c.save("pin",{},dict(card_id="c",position=1))
    assert c.merch({},cards)["cards"][0]["card_id"]=="c"
    version=c.version()
    c.set_weights(dict(rel=.5,pop=.1,margin=.2,pers=.2))
    assert c.version()>version


def test_api_lifecycle(cfg,shop,monkeypatch):
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    monkeypatch.setenv("KZ_ADMIN_TOKEN","test-only")
    j=shop.journal
    item=dict(id="demo",type="add_synonym",evidence=dict(sample_queries=["цурбикар"]),
              action=dict(kind="synonym",conditions={},payload_json=dict(kind="family",phrase="цурбикар",to="guard")))
    j.insert("insights",dict(id="demo",type="add_synonym",status="new",body=dump(item)))
    with TestClient(create_app(shop,cfg)) as api:
        assert api.get("/api/admin/rules").status_code==200
        assert api.post("/api/admin/insights/demo/apply").status_code==403
        api.headers["X-Admin-Token"]="test-only"
        assert api.post("/api/admin/insights/demo/apply").json()["status"]=="applied"
        assert api.post("/api/admin/insights/demo/apply").json()["status"]=="applied"
        assert len(api.get("/api/admin/rules").json()["items"])==1
        obj=api.post("/api/admin/insights/demo/verify").json()
        assert obj["status"]=="verified" and obj["verification"]["after"]["цурбикар"]["cards"][0]["card_id"]=="guard"
        assert api.post("/api/admin/insights/demo/reject").status_code==422
        monkeypatch.delenv("KZ_ADMIN_OPEN")
        api.headers.pop("X-Admin-Token")
        assert api.get("/api/admin/cost").status_code==403


@pytest.mark.parametrize("ext",["xlsx","csv","tsv","jsonl"])
def test_import_reports(shop,tmp_path,ext):
    path=tmp_path/("search."+ext)
    headers=["Поисковая фраза","Поиски","Доля пустых выдач","Примечание"]
    values=["страж",4,.5,"тест"]
    if ext=="xlsx":
        wb=Workbook()
        wb.active.append(headers)
        wb.active.append(values)
        wb.save(path)
    elif ext=="jsonl":
        path.write_text(json.dumps(dict(zip(headers,values))))
    else:
        sep=";" if ext=="csv" else "\t"
        path.write_text(sep.join(headers)+"\n"+sep.join(map(str,values)))
    assert ingest(shop,path)["searches"]==4
    assert ingest(shop,path)["duplicates"]==4
    assert shop.journal.rows("SELECT sum(zero) n FROM searches")[0]["n"]==2


def test_cost_with_cache(shop):
    j=shop.journal
    assert not report(j)["items"][0]["rub_per_query"]
    with j.transaction() as db:
        db.execute("CREATE TABLE llm_calls(id INTEGER,search_id TEXT,cached INTEGER,cost_usd REAL)")
        for i,cached in enumerate([0,1]):
            r=shop.search(Request(q="страж",mode="smart"))
            db.execute("INSERT INTO llm_calls VALUES (?,?,?,?)",(i,r["search_id"],cached,0 if cached else .02))
    assert report(j)["cache_rate"]==.5


def test_session_loss_deduplicated():
    base=dict(segment="smb",category="av",intent="product",source="history",clicks=0,leads=0,carts=0,
              orders=0,revenue=0,reason="vocabulary_gap",zero=1,ts=1,exits=1,reformulations=0)
    rows=[dict(base,session_id="lost",search_id=str(i),ts=i) for i in range(3)]
    rows+=[dict(base,session_id="won",search_id="o",zero=0,orders=1,clicks=1,revenue=100)]
    rows+=[dict(base,session_id="noise",search_id="n",reason="hardware")]
    lost,excluded=loss_by_search(rows)
    assert set(lost)=={"2"} and lost["2"][0]==80 and excluded==1


def test_resume_identical_history(shop,tmp_path):
    from kuznitsa.analytics.replay import prepare,execute,summary
    file=tmp_path/"input.tsv"
    file.write_text("Запрос\tПоиски\tДоля пустых выдач\nщит\t3\t1\nстраж\t2\t0")
    ingest(shop,file)
    plan=prepare(shop,"fast",2)
    execute(shop,"fast",plan)
    before=summary(shop.journal,plan[0])
    execute(shop,"fast",prepare(shop,"fast",2))
    assert before["processed"]==2 and before["frequency"]==5 and before["before_zero"]==3
    assert len(shop.journal.rows("SELECT search_id FROM searches WHERE source='replay'"))==2


def test_metrika_attribution(shop,tmp_path):
    path=tmp_path/"hits.jsonl"
    def hit(ts,url,params):
        return {"ym:pv:visitID":"v","ym:pv:watchID":str(ts),"ym:pv:URL":url,"ym:pv:dateTime":ts,"ym:pv:params":params}
    rows=[hit(10,"/search?q=первый",{}),hit(20,"/search?q=второй",{}),hit(30,"/cart",{"ecommerce":{"add":{"products":[{"id":"o","quantity":3}]}}})]
    path.write_text("\n".join(map(dump,rows)))
    assert ingest(shop,path)["searches"]==2
    pairs=shop.journal.rows("SELECT q_raw,type FROM events JOIN searches USING(search_id) ORDER BY eVents.ts")
    assert pairs==[dict(q_raw="первый",type="reformulate"),dict(q_raw="второй",type="cart")]


def test_conditional_phrase(shop):
    ident=shop.controls.save("synonym",{"segment":"gov"},{"phrase":"цурбикар","to":"страж","kind":"text"})
    assert shop.controls.synonyms()==[]
    assert shop.controls.redirect({"q_raw":"цурбикар на год","segment":"gov"})==dict(q="страж на год",rule_id=ident)
    assert shop.controls.redirect({"q_raw":"цурбикар на год","segment":"smb"}) is None
