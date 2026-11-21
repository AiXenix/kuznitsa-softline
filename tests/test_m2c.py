"""Контракты комплекта, импорта ведомости и встраиваемого поиска."""
from dataclasses import replace
from shutil import copytree

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kuznitsa.app import create_app
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.schema import Request
from kuznitsa.understand.quantities import spoken_numbers, numeric_conditions


@pytest.fixture(scope="module")
def plant(cfg,tmp_path_factory):
    root=tmp_path_factory.mktemp("m2c")/"kb"
    copytree(cfg.kb,root)
    slot={"category":"endpoint_security","families":["shield"],"must":True}
    def group(name,rows):
        (root/name).write_text(yaml.safe_dump(rows,allow_unicode=True))
    group("industries_r4.yaml",[
        dict(id="arts",title="Сценическое искусство",aliases=["репертуарный театр"],slots=[slot]),
        dict(id="theatre",parent="arts",title="Драматический театр",aliases=["театр","репертуарный театр"],slots=[slot]),
        dict(id="orphan",parent="missing",title="Архив",slots=[slot])])
    group("roles_r4.yaml",[dict(id="director",title="Режиссёр",aliases=["постановщик"],slots=[slot])])
    group("okved_r4.yaml",[
        dict(code="90",title="Творческие профессии",industry="arts"),
        dict(code="90.01",title="Исполнительское искусство",industry="theatre")])
    engine=Engine.open(replace(cfg,kb=root))
    yield engine
    engine.close()


def test_parent_alias_and_industry_within_role(plant):
    kb=plant.kb
    assert "репертуарный театр" not in kb.rows["industries"]["arts"]["aliases"]
    assert any("missing" in s for s in kb.warnings)
    for query in ("репертуарный театр","оквэд 90.01.7"):
        result=plant.search(Request(q=query,mode="fast"))
        block=next(b for b in result["blocks"] if b["type"]=="kit")
        assert block["role"]=="theatre" and block["slots"][0]["card"]
        assert block["parent"]==dict(id="arts",title="Сценическое искусство",q="Сценическое искусство")
    u=plant.search(Request(q="постановщик в театре",mode="fast"))["understood"]
    assert u["intent"]=="role_kit" and {"theatre","director"}<={e["id"] for e in u["entities"]}
    assert plant.search(Request(q="антивирус для театра",mode="fast"))["understood"]["intent"]=="category"


def test_okved_fallback_requires_classifier_name(plant):
    def search(q):
        return plant.search(Request(q=q,mode="fast"))
    assert plant.kb.report()["sources"]["okved"]["extensions"]==2
    assert any(e["id"]=="90" and e["type"]=="okved" for e in search("оквэд 90.28")["understood"]["entities"])
    unknown=search("компания с оквэд 77.98")
    assert unknown["understood"]["zero_reason"]=="unknown_term"
    assert any(b["type"]=="clarify" and b["options"] for b in unknown["blocks"])
    assert all(e["type"]!="okved" for e in search("версия 90.01")["understood"]["entities"])


@pytest.mark.parametrize(("query","expected"),[
    ("на тридцать компьютеров","на 30 компьютеров"),("полсотни мест","50 мест"),
    ("две сотни лицензий","200 лицензий"),("на полтора года","на 18 мес"),
    ("тысяча двести пользователей","1200 пользователей")])
def test_spoken_quantities(query,expected):
    assert spoken_numbers(query)==expected


@pytest.mark.parametrize(("query","maximum"),[
    ("в пределах 500к",500000),("до 100 тысяч",100000),("не дороже 3 млн",3000000)])
def test_budget(query,maximum):
    filters={}
    numeric_conditions(spoken_numbers(query).split(),filters,None)
    assert filters["price_max"]==maximum


def test_budget_covers_entire_order(engine):
    q="антивирус на тридцать компьютеров"
    result=engine.search(Request(q=q+" в пределах 500к",mode="fast"))
    assert result["understood"]["qty"]["value"]==30
    assert result["understood"]["filters"]["price_max"]==500000
    assert any(c.get("calc",{}).get("total") for c in cards_from(result["blocks"]))
    assert not cards_from(engine.search(Request(q=q+" не дороже 3 руб",mode="fast"))["blocks"])


@pytest.mark.parametrize("mode",["fast","smart"])
def test_spec_article_precedes_name_and_preserves_rows(engine,mode):
    first=next(o for o in engine.catalog.skus.values() if o.lic.action=="new" and (o.lic.qty_min or 1)==1 and o.price)
    other=next(c.title for c in engine.catalog.cards.values() if c.family!=first.family_id)
    line=f"{other} [{first.sku}] — 1 шт"
    for query in (line,"\n".join([line]*199+[f"{other} [UNLISTED-87964] — 7 шт"])):
        result=engine.search(Request(q=query,mode=mode,source="ui"))
        spec=next(b for b in result["blocks"] if b["type"]=="spec")
        assert len(spec["lines"])==len(query.splitlines())
        assert spec["lines"][0]["card"]["offer"]["offer_id"]==first.offer_id
        if len(spec["lines"])==200:
            assert spec["unresolved"]==[200] and spec["total"] is None
        assert result["cost"]["llm_calls"]<=1
    with pytest.raises(ValidationError):
        Request(q="\n".join([line]*201))


def test_full_offer_name_selects_variant(engine):
    from collections import Counter
    names=Counter(o.name for o in engine.catalog.offers_by_id.values())
    o=next(o for o in engine.catalog.offers_by_id.values() if names[o.name]==1 and o.lic.action=="renewal")
    for mode in ("fast","smart"):
        cards=cards_from(engine.search(Request(q=o.name,mode=mode))["blocks"])
        assert cards[0]["offer"]["offer_id"]==o.offer_id


def test_embed_and_eval_http_contract(cfg,engine,monkeypatch):
    cfg=replace(cfg,cors_origins=["https://shop.example"])
    token="fixture-eval-token"
    monkeypatch.setenv("KZ_ADMIN_TOKEN",token)
    with TestClient(create_app(engine,cfg)) as api:
        assert api.options("/api/search",headers={"Origin":"https://shop.example","Access-Control-Request-Method":"POST"}).headers["access-control-allow-origin"]=="https://shop.example"
        label=api.get("/api/meta").json()["labels"]
        assert set(label)==set("categories vendors roles industries segments intents zero_reasons blocks tiers".split())
        assert label["categories"]["endpoint_security"]["parent"]=="security"
        monkeypatch.setattr(engine,"search",lambda req:dict(source=req.model_source))
        data=dict(q="поиск",source="eval")
        assert api.post("/api/search",json=data).json()["source"]=="eval"
        assert api.post("/api/search",json=data,headers={"X-Admin-Token":"bad"}).status_code==403
        assert api.post("/api/search",json=data,headers={"X-Admin-Token":token}).json()["source"]=="authorized_eval"


def test_closed_kit_choice_and_cache(plant,monkeypatch):
    import json
    import httpx
    from kuznitsa.llm.jev import Jev
    from kuznitsa.llm.decisions import Decisions

    seen=[]
    def decide(request):
        questions=json.loads(request.content)["questions"]
        seen.append(questions)
        assert set(questions)=={"kit"} and 2<=len(questions["kit"]["criteria"])<=9
        assert "none" in questions["kit"]["criteria"]
        return httpx.Response(200,json={"answers":{"kit":{"choice":"theatre","probabilities":{"theatre":.78}}},
                                       "usage":{"cost":.00001}})
    client=Jev(model="kit-fixture",transport=httpx.MockTransport(decide))
    decisions=Decisions(client,plant.journal.path,plant.clock,1)
    monkeypatch.setattr(plant,"decisions",decisions)
    try:
        query="какие программы выбрать для драматического театра перед гастролями"
        first=plant.search(Request(q=query,mode="smart"))
        second=plant.search(Request(q=query,mode="smart"))
        assert first["understood"]["intent_source"]=="jev"
        assert any(b.get("role")=="theatre" for b in first["blocks"])
        assert len(seen)==1 and second["cost"]["cached"]==1
    finally:
        decisions.pool.shutdown()
        client.close()


def test_repeat_order_uses_purchased_sku(engine,monkeypatch):
    owned=next(o for o in engine.catalog.offers_by_id.values() if o.lic.action=="new" and o.price)
    profile=engine.clients["smb_trade"].model_copy(update={"owned":[],"orders":[
        {"order_id":"sample-order","date":"2026-10-04","items":[{"offer_id":owned.offer_id,"qty":owned.lic.qty_min or 1}]}]})
    monkeypatch.setitem(engine.clients,profile.client_id,profile)
    result=engine.search(Request(q="повторить прошлый заказ",profile_id=profile.client_id,mode="fast"))
    block=next(b for b in result["blocks"] if b.get("action")=="repeat_order")
    assert block["items"][0]["offer"]["offer_id"]==owned.offer_id
    assert block["items"][0]["action"]["label"]=="Повторить"


def test_budget_accepts_mixed_pack_sizes(engine):
    from dataclasses import replace
    from kuznitsa.index.filters import OfferFilters
    from kuznitsa.rank.variants import select,calculation
    card=next(iter(engine.catalog.cards.values()))
    base=card.offers[0]
    offers=[base.model_copy(update={"price":price,"price_on_request":False,"available":True,
                "lic":base.lic.model_copy(update={"pack":pack,"action":"new","audience":"business",
                                                  "qty_min":1,"qty_max":None})}) for pack,price in [(2,20),(5,50)]]
    mixed=replace(card,offers=offers,filters=OfferFilters(offers,{},{}))
    found=select(mixed,engine.clients["guest"],{"price_max":70},{},{"value":7})
    assert calculation(found[0],found[1])["total"]==70
    assert select(mixed,engine.clients["guest"],{"price_max":69},{},{"value":7}) is None


def test_explicit_procurement_code_selects_matching_offer(cfg,tmp_path):
    from kuznitsa.schema import Offer
    codes=["12.34.01.010-00000001","12.34.02.020-00000002"]
    with (tmp_path/"catalog.jsonl").open("w") as dest:
        for i,code in enumerate(codes):
            offer=Offer(offer_id=str(i),name="Инженерный пакет",family_id="shield",registry=True,
                        sku=f"CAD-{i}",price=1000+i,attrs={"КТРУ":code},lic={"action":"new","metric":"user"})
            print(offer.model_dump_json(),file=dest)
    (tmp_path/"clients.jsonl").write_text("")
    shop=Engine.open(replace(cfg,data=tmp_path))
    try:
        for i,code in enumerate(codes):
            result=shop.search(Request(q="ктру "+code.split("-")[0],mode="fast"))
            assert result["understood"]["intent"]=="compliance"
            assert cards_from(result["blocks"])[0]["offer"]["sku"]==f"CAD-{i}"
    finally:
        shop.close()


def test_class_vendor_scope_instead_of_guessed_family(engine):
    r=engine.search(Request(q="защита рабочих станций Север",mode="fast"))
    f=r["understood"]["filters"]
    assert f["category"]==["endpoint_security"] and f["vendor"]==["north"] and "family" not in f
    assert cards_from(r["blocks"]) and all(c["vendor"]["id"]=="north" for c in cards_from(r["blocks"]))


@pytest.mark.parametrize("mode", ["fast", "smart"])
def test_removable_procurement_conditions(plant,monkeypatch,mode):
    from kuznitsa.schema import Client
    clinic=Client(client_id="clinic",title="Клиника",segment="gov",fleet={"os":["astra"]},
                  preferences={"registry_required":True,"certs_required":["fstec"]})
    monkeypatch.setitem(plant.clients,"clinic",clinic)
    def lookup(profile,ignore=()):
        return plant.search(Request(q="антивирус на 30 пк",profile_id=profile,ignore=list(ignore),mode=mode))
    result=lookup("clinic")
    keys={"registry","certs","platform"}
    chips={c["key"] for c in result["understood"]["chips"] if c.get("source")=="context" and c["removable"]}
    assert keys<=chips
    for key in keys:
        revised=lookup("clinic",[key])
        assert key not in revised["understood"]["filters"]
        assert keys-{key}<=revised["understood"]["filters"].keys()
        assert cards_from(revised["blocks"])!=cards_from(result["blocks"])
    guest=lookup("guest")
    assert not keys.intersection(guest["understood"]["filters"])
    for card in cards_from(guest["blocks"]):
        assert all(o["audience"] not in ("edu","gov") for o in [card["offer"],*card["variants"]])


def test_spec_brand_uses_installed_product(engine):
    result=engine.search(Request(q="Север на 30 пк\nСтраж на 10 пк",profile_id="smb_trade",mode="fast"))
    lines=next(b for b in result["blocks"] if b["type"]=="spec")["lines"]
    assert len(lines)==2 and lines[0]["status"]=="matched"
    assert lines[0]["card"]["card_id"].split(":")[0]=="shield"
    assert lines[0]["qty"]==30


def test_kit_respects_slot_family_order(plant,monkeypatch):
    slot=plant.kb.rows["industries"]["theatre"]["slots"][0]
    for families in (["shield","guard"],["guard","shield"]):
        monkeypatch.setitem(slot,"families",families)
        r=plant.search(Request(q="оквэд 90.01",mode="fast"))
        kit=next(b for b in r["blocks"] if b["type"]=="kit")
        assert plant.catalog.cards[kit["slots"][0]["card"]["card_id"]].family==families[0]
