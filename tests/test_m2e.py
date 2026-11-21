import json
from dataclasses import replace
import httpx
import pytest
from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Jev
from kuznitsa.schema import Request
from kuznitsa.understand.quantities import spoken_numbers


@pytest.mark.parametrize("phrase",["щит для хоума","щит маме на ноут","щит для семьи"])
def test_home_and_remove(engine,phrase):
    r=engine.search(Request(q=phrase,mode="fast"))
    assert r["understood"]["refined"]["audience"]=="home"
    assert any(c["label"]=="Понято: для дома" for c in r["understood"]["chips"])
    assert r["understood"]["zero_reason"]=="not_in_catalog"
    alt=next(b for b in r["blocks"] if b["type"]=="analogs")
    assert all(i["card"]["offer"]["available"] for i in alt["items"])
    normal=engine.search(Request(q=phrase,mode="fast",ignore=["audience"]))
    assert normal["understood"]["refined"]["audience"] is None


def test_refine_one_decision_and_cache(cfg):
    sent=[]
    def reply(request):
        questions=json.loads(request.content)["questions"]
        choices={k:("mobile" if k=="audience" else "shield" if k=="line" else "none") for k in questions}
        assert set(questions)=={"audience","line"}
        assert "shield" in questions["line"]["criteria"] and len(questions["line"]["criteria"])<=9
        sent.append(questions)
        return httpx.Response(200,json={"answers":{k:dict(choice=v,probabilities={v:.89}) for k,v in choices.items()},"usage":{"cost":.0001}})
    e=Engine.open(cfg,llm=Jev(transport=httpx.MockTransport(reply)))
    try:
        for cached in (0,1):
            r=e.search(Request(q="север для карманных терминалов",mode="smart"))
            assert r["understood"]["refined"]==dict(audience="mobile",line="shield",source="jev",probability=.89)
            step=next(s for s in r["trace"] if s["step"]=="refine")
            assert step["detail"]["calls"][0]["cached"]==cached
        assert len(sent)==1
    finally:e.close()


def test_system_and_duplicate_word(engine):
    from kuznitsa.understand.systems import target_system
    f=dict(category=["endpoint_security"],vendor=["foreign"])
    assert target_system(engine,"антивирус для постгреса",f,[])=="PostgreSQL"
    assert f==dict(category=["endpoint_security"])
    f["vendor"]=["north"]
    assert target_system(engine,"антивирус север",f,[]) is None


def test_operation_and_unit(cfg,tmp_path):
    row=dict(offer_id="r23",vendor="Норд",vendor_id="n",family_id="net",family_name="Сеть",category_id="endpoint_security",
             name="Сеть Плюс",attrs=dict(series="Сеть",edition="Плюс",operation="EDU"),price=1900,
             lic=dict(action="new",audience="edu",qty_min=3,qty_max=27,metric="device"))
    per_core={**row,"offer_id":"per-core","lic":{**row["lic"],"metric":"core"}}
    (tmp_path/"catalog.jsonl").write_text("\n".join(map(json.dumps,[per_core,row])))
    engine=Engine.open(replace(cfg,data=tmp_path))
    try:
        r=engine.search(Request(q="Норд / Сеть / Плюс / образовательная, кол-во 11 устройств",mode="fast"))
        line=next(b for b in r["blocks"] if b["type"]=="spec")["lines"][0]
        assert line["card"]["offer"]["offer_id"]=="r23" and line["qty"]==11
    finally:engine.close()


@pytest.mark.parametrize("q,number",[("на трехстах узлах",300),("для восьмидесяти шести мест",86),("полтысячи мест",500)])
def test_spoken_cases(q,number):
    assert str(number) in spoken_numbers(q)


@pytest.mark.parametrize("mode",["smart","fast"])
def test_ignore_refined_from_storefront(cfg,mode):
    from fastapi.testclient import TestClient
    from kuznitsa.app import create_app
    questions=[]
    def capture(request):
        questions.extend(json.loads(request.content)["questions"])
        return httpx.Response(503)
    e=Engine.open(cfg,llm=Jev(transport=httpx.MockTransport(capture)))
    with TestClient(create_app(e,cfg)) as api:
        response=api.post("/api/search",json=dict(q="щит для дома на андроид на 12 пк",mode=mode,
            filters={"term_months":24},ignore=["refined"]))
        assert response.status_code==200
        r=response.json()
        u=r["understood"]
        assert "refined" not in u and not {"audience","platform"}.intersection(u["filters"])
        assert u["qty"]["value"]==12 and u["filters"]["term_months"]==24
        assert not any(c["key"]=="refined" for c in u["chips"])
        assert next(s for s in r["trace"] if s["step"]=="refine")["status"]=="skip"
        assert "line" not in questions and "audience" not in questions


def test_replacement_faq_contract(engine,monkeypatch):
    row=dict(id="office_terms",questions=["Можно ли использовать домашнюю лицензию в офисе?"])
    monkeypatch.setitem(engine.kb.rows["faq"],row["id"],row)
    r=engine.search(Request(q="щит для семьи",mode="fast"))
    b=next(b for b in r["blocks"] if b["type"]=="analogs")
    a=next(b for b in r["blocks"] if b["type"]=="answer")
    assert b["text"]==r["understood"]["agent_note"] and b["text"]
    assert b["faq_id"]==a["faq_id"]==row["id"] and a["links"][0]["q"] in row["questions"]


@pytest.fixture
def imported_shop(cfg,tmp_path):
    def offer(fid,title,category,path,**attrs):
        return dict(offer_id="sku-"+fid,name=title,vendor="Векторика",vendor_id="vektorika",
                    source_id="src-"+fid,family_name=title,family_id=fid,category_id=category,
                    category_path=[path],price=2400,attrs=attrs,lic={"action":"new","audience":"business"})
    rows=[
        offer("wall","Векторика Геометр","blueprints","Чертежи помещений",aliases=["геометр-план"]),
        offer("disk","Векторика Снимок","backup_recovery","Архивация и резервное копирование",task="сберечь копию документов"),
        offer("zip","Векторика Сжатие","archivers","Архиваторы"),
        offer("support","Сопровождение Векторика","tech_support","Техническая поддержка"),
        offer("withdrawn","Векторика Резерв Старая","backup_recovery","Резервное копирование",active=False),
    ]
    (tmp_path/"catalog.jsonl").write_text("\n".join(map(json.dumps,rows)))
    e=Engine.open(replace(cfg,data=tmp_path))
    yield e
    e.close()


def hits(r):
    return [item.get("card",item)["offer"]["offer_id"] for b in r["blocks"] if b["type"] in ("analogs","services","products") for item in b["items"]]


@pytest.mark.parametrize("query,expected",[
    ("Чертежи помещений","wall"),("Чертежи помещений Векторика","wall"),("Векторика Геометр","wall"),
    ("геометр-план","wall"),("феометр-план","wall"),("geometr-plan","wall"),("сберечь копию документов","disk"),("сохранить файл перед переездом","disk"),
    ("data compression for 4 devices","zip"),("software installation service","support")])
def test_imported_discovery(imported_shop,query,expected):
    r=imported_shop.search(Request(q=query,mode="fast"))
    assert hits(r)[0]=="sku-"+expected
    if "devices" in query:assert r["understood"]["qty"]==dict(value=4,metric="device")


@pytest.mark.parametrize("query",["Куда обратиться по поводу продления щита?", "Как перенести щит на новый ноутбук?"])
def test_product_question_before_action(engine,query):
    r=engine.search(Request(q=query,mode="fast"))
    assert r["blocks"][0]["type"]=="answer" and hits(r)


def test_imported_withdrawal(imported_shop):
    r=imported_shop.search(Request(q="Векторика Резерв Старая",mode="fast"))
    assert r["understood"]["zero_reason"]=="not_in_catalog"
    assert "sku-withdrawn" not in imported_shop.catalog.offers_by_id
    assert hits(r)==["sku-disk"] and any(b["type"]=="not_in_catalog" for b in r["blocks"])


def test_imperative_budget(engine):
    r=engine.search(Request(q="щит на 6 устройств, отберите до 50 000 руб.",mode="fast"))
    assert r["understood"]["filters"]["price_max"]==50_000
    assert r["understood"]["qty"]["value"]==6
    assert hits(r) and all(c["calc"]["total"]<=50000 for b in r["blocks"] if b["type"]=="products" for c in b["items"])


def test_kb_purpose_groups(tmp_path):
    from kuznitsa.kb.loader import load
    from shutil import copytree
    from tests.conftest import MINI
    kbdir=tmp_path/"kb"
    copytree(MINI,kbdir)
    (kbdir/"for_whom.yaml").write_text("families: [{id: shield, audiences: [server], for_whom: Файловые серверы}]")
    (kbdir/"system_compat.yaml").write_text("systems: [{id: db, label: Для СУБД, aliases: [субд], compatible: {backup: {categories: [endpoint_security], families: [{id: shield}]}}}]")
    kb=load(kbdir)
    assert kb.report()["counts"]["system_compat"]==kb.report()["counts"]["for_whom"]==1
    assert kb.rows["families"]["shield"]["for_whom"]=="Файловые серверы"
    assert "СУБД" in kb.systems


def test_imported_replacement_and_metric(imported_shop):
    from kuznitsa.understand.routing import software_like_unknown
    assert software_like_unknown("Willow Studio",["willow","studio"],[dict(type="family",text="studio")])
    r=imported_shop.search(Request(q="отечественная замена чужой платформы на 13 узлов",mode="fast"))
    assert r["understood"]["intent"]=="analog" and r["understood"]["qty"]["value"]==13
    assert r["understood"]["filters"]["origin"]=="russian"


def test_english_intent_checks_live_catalog(imported_shop, cfg, tmp_path):
    seen = []

    def decide(request):
        questions = json.loads(request.content)["questions"]
        seen.append(set(questions))
        answers = {}
        for key, question in questions.items():
            options = question["criteria"]
            val = "category" if key == "intent" else "none" if "none" in options else next(iter(options))
            answers[key] = {"choice": val, "probabilities": {val: .91}}
        return httpx.Response(200, json={"answers": answers, "usage": {"cost": .00001}})

    shop = Engine.open(replace(cfg,data=tmp_path),llm=Jev(transport=httpx.MockTransport(decide)))
    try:
        result = shop.search(Request(q="file compression for 6 seats", mode="smart"))
        assert any("intent" in batch for batch in seen)
        assert hits(result) == ["sku-zip"]
        assert result["understood"]["qty"] == {"value": 6, "metric": "user"}
    finally:
        shop.close()
