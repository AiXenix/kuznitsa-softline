import json
import yaml
from fastapi.testclient import TestClient
from kuznitsa.app import create_app
from kuznitsa.analytics.store import Journal
from kuznitsa.analytics.upsell_rules import active_rules
from kuznitsa.engine import Engine


def test_upsell_api(cfg,tmp_path,monkeypatch):
    j=Journal(tmp_path/"journal.db")
    e=Engine.open(cfg,journal=j)
    rule=dict(id="security",when=dict(query_words=["офис"]),offer=dict(families=["shield"]),
              reason="Защита рабочих мест с офисным пакетом",weight=.8,source="kb")
    (tmp_path/"upsell_r9.yaml").write_text(yaml.safe_dump([rule],allow_unicode=True))
    monkeypatch.setenv("KZ_KB_DIR",str(tmp_path))
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    monkeypatch.setenv("KZ_ADMIN_TOKEN","local-test-token")
    headers={"X-Admin-Token":"local-test-token","X-Admin-Author":"manager"}
    with TestClient(create_app(e,cfg)) as api:
        path="/api/admin/upsell"
        def save(name,data):
            (tmp_path/("upsell-"+name+".json")).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
        v,r=active_rules(j)
        assert r[0]["id"]=="security"
        resp=api.post(path+"/preview",json={"q":"офис","rule_id":"security"})
        assert resp.status_code==200 and resp.json()["matched"]
        assert resp.json()["items"] and all(x["rule_id"]=="security" for x in resp.json()["items"])
        save("preview",resp.json())
        assert api.post(path,json=rule).status_code==403
        created=api.post(path,json=rule|dict(id="manual"),headers=headers)
        assert created.status_code==201
        save("create",created.json())
        assert api.post(path,json=rule,headers=headers).status_code==422
        assert api.put(path+"/manual",json={"offer":{}},headers=headers).status_code==422
        updated=api.put(path+"/security",json={"weight":.4},headers=headers).json()
        save("update",updated)
        assert updated["rule"]["weight"]==.4 and v!=active_rules(j)[0]
        disabled=api.delete(path+"/manual",headers=headers).json()
        save("disable",disabled)
        assert len(active_rules(j)[1])==1
        result=api.post("/api/search",json=dict(q="офис",mode="fast",source="ui")).json()
        card=next(iter(e.catalog.by["family"]["shield"]))
        for kind in ("impression","click","cart"):
            assert api.post("/api/event",json=dict(type=kind,search_id=result["search_id"],card_id=card,
                payload={"rule_id":"security"})).status_code==204
        metrics=api.get(path+"/analytics").json()
        assert metrics["totals"]==dict(impressions=1,clicks=1,carts=1)
        assert metrics["best_pairs"][0]["q"]=="офис"
        save("analytics",metrics)
        save("list",api.get(path).json())
        audit=api.get(path+"/audit").json()
        assert [r["op"] for r in audit["items"]]==["disable","update","create"]
        save("audit",audit)
        revised=rule|dict(reason="Обновлено по документации вендора")
        (tmp_path/"upsell_r9.yaml").write_text(yaml.safe_dump([revised],allow_unicode=True))
        effective=active_rules(j)[1][0]
        assert effective["weight"]==.4 and effective["reason"]==revised["reason"]


def test_feed_model_scope_and_funnel(cfg,tmp_path):
    from kuznitsa.analytics import feed_history,kpi,replay
    from shutil import copyfile
    copyfile(cfg.data/"catalog.jsonl",tmp_path/"catalog.jsonl")
    j=Journal(tmp_path/"journal.db")
    e=Engine.open(cfg,journal=j)
    counts=feed_history.generate(e,17,"2026-11-26")
    assert counts["searches"]==45000
    assert 0 < counts["failed"]/45000 <= .4
    assert .3 <= counts["exits_after_failure"]/counts["failed"] <= .5
    assert .05 <= counts["orders"]/45000 <= .10
    assert j.rows("SELECT count(distinct date(ts,'unixepoch','+3 hours')) n FROM active_history")[0]["n"]==90
    assert replay.run(e)["status"]=="completed"
    report=kpi.report(j)
    assert report["totals"]["paired_searches"]==45000 and report["history_note"] in report["note"]
    assert all(t["value"] is not None for t in report["tiles"])


def test_feed_preview_is_isolated(tmp_path):
    from types import SimpleNamespace
    from kuznitsa.analytics.upsell_rules import preview

    class Recommendations:
        provider="stored"
        compiled=[]
        def compile(self,rules):
            return [r for r in rules if r["enabled"]]

    class Feed:
        def preview(self,req,priorities):
            rec=self.catalog.feed.recommend
            assert rec.provider is None
            extra=[dict(card=dict(card_id="safe",title="Антивирус",kind="upsell",rule_id=r["id"]))
                   for r in rec.compiled if r["weight"]>.5]
            return dict(blocks=[dict(type="products",items=[dict(card_id="office")]),dict(type="crosssell",items=extra)])

    engine=Feed()
    engine.journal=Journal(tmp_path/"preview.db")
    engine.catalog=SimpleNamespace(feed=SimpleNamespace(recommend=Recommendations()))
    rule=dict(id="draft",when=dict(classes=["1"]),offer=dict(classes=["2"]),reason="Защита ПК",weight=.8)
    assert preview(engine,"офис",rule)["items"][0]["block"]=="crosssell"
    assert not preview(engine,"офис",rule|dict(weight=.1))["matched"]
    assert engine.catalog.feed.recommend.provider=="stored" and engine.catalog.feed.recommend.compiled==[]
    assert engine.journal.rows("select * from upsell_audit")==[]
