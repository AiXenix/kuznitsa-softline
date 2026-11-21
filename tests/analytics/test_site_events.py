import json

from fastapi.testclient import TestClient

from kuznitsa.analytics.kpi import facts
from kuznitsa.analytics.store import Journal
from kuznitsa.app import create_app
from kuznitsa.config import ROOT
from kuznitsa.engine import Engine
from kuznitsa.ingest.history import ingest,sniff


SOURCE = ROOT/"docs/admin_examples/import/site-events.jsonl"


def test_jsonl_search_funnel(cfg,tmp_path,monkeypatch):
    j=Journal(tmp_path/"shop.db")
    e=Engine.open(cfg,journal=j)
    # Подставляем артикул текущего каталога, чтобы проверить цель и маржу заказа.
    offer=next(iter(e.catalog.offers_by_id.values()))
    path=tmp_path/"events.ndjson"
    src=SOURCE.read_text().replace("S-100", offer.offer_id)
    path.write_text(src + src.splitlines()[0]+"\n")
    hint=sniff(path)
    assert (hint["kind"],hint["format"])==("search_log","site_events")
    assert hint["columns"]["term"]=="q" and hint["columns"]["action"]=="kind"
    assert {hint["columns"][k] for k in ("found","results","hits")}=={"n_cards"}
    expected=dict(search=3,impression=1,click=1,cart=1,order=1)
    r=ingest(e,path)
    assert r["rows_read"]==9 and r["rows_accepted"]==7 and r["skipped"]==1 and r["repeated_rows"]==1
    assert r["skip_reasons"]=={"Нет предшествующего поиска в сессии":1}
    assert r["events_by_type"]==r["inserted_by_type"]==expected
    assert r["observed_searches"]==3 and r["observed_empty"]==1 and r["zero_rate"]==1/3
    for _ in range(2):
        r=ingest(e,path)
        assert r["events_by_type"]==expected and not sum(r["inserted_by_type"].values())
        assert (r["searches"],r["events"])==(0,0)
        rows={x["q"]:x for x in facts(j)}
        one,two=rows["защита сервера"],rows["защита на 20 мест"]
        assert (one["clicks"],one["best_position"],one["orders"])==(1,2,0)
        assert (two["clicks"],two["carts"],two["orders"],two["revenue"])==(0,1,1,12000)
        assert j.detail(one["search_id"])["n_cards"]==4
        assert json.loads(one["top_cards_json"])[0]==offer.card_id
        assert j.rows("SELECT card_id,margin_value FROM events WHERE type='order'")==[
            dict(card_id=offer.card_id,margin_value=round(12000*offer.margin,2))]
    saved=json.loads((tmp_path/"history_report.json").read_text())["files"]
    assert saved[0]["events_by_type"]==expected
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    with TestClient(create_app(e,cfg)) as api:
        funnel={s["key"]:s["count"] for s in api.get("/api/admin/kpi").json()["funnel"]}
        assert (funnel["searches"],funnel["orders"],funnel["carts"])==(3,1,1)
        assert api.get("/api/admin/ingest").json()["history"][0]["events_by_type"]==expected


def test_site_event_only_file_and_bad_rows(cfg,tmp_path):
    j=Journal(tmp_path/"shop.db")
    e=Engine.open(cfg,journal=j)
    search=tmp_path/"search.jsonl"
    search.write_text('{"type":"поиск","sid":"a","ts":20,"q":"щит","hits":0}\n')
    ingest(e,search)
    path=tmp_path/"orders.jsonl"
    path.write_text('{"action":"order","session":"a","timestamp":30}\n'
                    '{"action":"cart","session":"a","timestamp":10}\n'
                    '{"type":"click","sid":"a","ts":"позавчера"}\n'
                    '{"type":"other","sid":"a","ts":32}\n')
    assert sniff(path)["kind"]=="search_log"
    r=ingest(e,path)
    assert r["events_by_type"]["order"]==1 and r["skipped"]==3
    assert facts(j)[0]["orders"]==1
    assert r["availability"]["revenue"]=="нет суммы заказа"
