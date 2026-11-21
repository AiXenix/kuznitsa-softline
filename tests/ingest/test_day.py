from dataclasses import replace
from pathlib import Path
import json
from shutil import copytree
import pytest
from kuznitsa.ingest.day import day,identify
from kuznitsa.mock.clients_gen import portfolio_qty
from kuznitsa.schema import License,Offer

SETS=Path(__file__).resolve().parents[2]/"docs/ingest_examples"


@pytest.mark.parametrize("name",["1c","usd","yml"])
def test_content_detection(name):
    roles={p.stem:identify(p)[0] for p in (SETS/("day_"+name)).iterdir()}
    assert roles=={"01":"catalog","02":"history","03":"metrika_external_phrases"}


def test_day_keeps_active_snapshot(tmp_path,cfg):
    out=tmp_path/"fresh"
    active=cfg.data/"catalog.jsonl"
    before=active.stat().st_mtime_ns
    incoming=copytree(SETS/"day_usd",tmp_path/"incoming")
    (incoming/"onsite.tsv").write_text("Фраза внутреннего поиска\tВизиты\nпакет для офиса\t5\n",encoding="utf-8")
    r=day(incoming,replace(cfg,kb=SETS.parents[1]/"kb"),out,ai="off",n=2)
    assert r["coverage"]["offers"]==2 and r["agent"]["count"]>=0
    assert r["replay"]["processed"] and r["selfcheck"]["n"]==2
    report=(out/"day_report.md").read_text()
    assert "| 03.tsv | Метрика · фразы из поисковиков | 1 | 0 |" in report
    assert "| onsite.tsv | Метрика · поиск по сайту | 1 | 0 |" in report
    external=next(f["history"] for f in r["files"] if f["role"]=="metrika_external_phrases")
    assert external["external_phrases"]==[{"q":"windows pro","visits":3}]
    assert external["searches"]==0
    assert r["catalog"]["currency"]["converted_rows"]==2
    price=json.loads((out/"catalog.jsonl").read_text().splitlines()[0])["price"]
    assert price==145.50*cfg.usd_rub
    assert active.stat().st_mtime_ns==before
    with pytest.raises(FileExistsError):
        day(SETS/"day_usd",cfg,out)


def test_portfolio_metric_qty():
    def qty(metric,pack):
        return portfolio_qty(Offer(name="ПО",offer_id="x",lic=License(metric=metric,pack=pack)),123,3)
    assert qty("core",16)==48 and qty("server",1)==3 and qty("user",5)==125
