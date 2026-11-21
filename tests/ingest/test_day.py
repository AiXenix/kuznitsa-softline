from dataclasses import replace
from pathlib import Path
import json
import pytest
from kuznitsa.ingest.day import day,identify
from kuznitsa.mock.clients_gen import portfolio_qty
from kuznitsa.schema import License,Offer

SETS=Path(__file__).resolve().parents[2]/"docs/ingest_examples"


@pytest.mark.parametrize("name",["1c","usd","yml"])
def test_content_detection(name):
    roles={identify(p)[0] for p in (SETS/("day_"+name)).iterdir()}
    assert roles=={"catalog","history","metrika"}


def test_day_keeps_active_snapshot(tmp_path,cfg):
    out=tmp_path/"fresh"
    active=cfg.data/"catalog.jsonl"
    before=active.stat().st_mtime_ns
    r=day(SETS/"day_usd",replace(cfg,kb=SETS.parents[1]/"kb"),out,ai="off",n=2)
    assert r["coverage"]["offers"]==2 and r["agent"]["count"]>=0
    assert r["replay"]["processed"] and r["selfcheck"]["n"]==2
    assert (out/"day_report.md").is_file()
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
