"""Регрессии обобщения и управление порядком внутри полосы."""
from dataclasses import replace
import shutil
from pathlib import Path
from types import SimpleNamespace
import pytest
from kuznitsa.schema import Request,Offer
from kuznitsa.engine import Engine
from kuznitsa.understand.quantities import spoken_numbers,numeric_conditions
from kuznitsa.rank.priorities import compile_rules,apply
from kuznitsa.understand.repair import LAYOUT


def search(engine,q,**params):
    return engine.preview(Request(q=q,**params),[])


@pytest.mark.parametrize(("q","intent"),[
    ("щит для сотрудников на рабочие места","product"),
    ("щит для сисадминов до 9000","product"),
    ("лицензию QuantaNimbus Studio","out_of_catalog"),
    ("продление Old Guard","out_of_catalog"),
    ("список наших лицензий","account"),
    ("как зарегистрировать лицензию на новом устройстве","question"),
    ("щит или подписка","product"),
    ("антивирус для тендера по 223-ФЗ","compliance"),
    ("связка North Shield плюс East Guard","spec_list"),
])
def test_routing(engine,q,intent):
    r=search(engine,q)
    assert r["understood"]["intent"]==intent
    if intent=="question":assert any(b["type"]=="answer" for b in r["blocks"])
    if intent=="spec_list":assert len(r["blocks"][0]["lines"])==2


def test_negation(engine):
    for marker in ("но не","кроме","без"):
        r=search(engine,"антивирус "+marker+" Север")
        assert "north" in r["understood"]["exclude"]["vendor"]
        assert all(c["vendor"]["id"]!="north" for b in r["blocks"] if b["type"]=="products" for c in b["items"])


@pytest.mark.parametrize(("q","n","metric"),[("двадцати семи хостов",27,"server"),("сорока восьми процессоров",48,"cpu"),
    ("полутора сотен удаленных сотрудников",150,"user"),("63pk",63,"device"),("54ядер",54,"core")])
def test_quantity(q,n,metric):
    assert numeric_conditions(spoken_numbers(q).split(),{},None)==dict(value=n,metric=metric)


@pytest.fixture
def external(cfg,tmp_path):
    offers=[]
    for i in range(3):
        name=f"Novalux / Сфера, выпуск {i}, 8–19 ПК, ESD"
        o=Offer(offer_id=str(i),name=name,sku="AX-LUX-"+str(314+i),family_id="lum"+str(i),
                vendor_id="novalux",vendor="Novalux",family_name="Сфера "+str(i),category_id="toolset",
                category_path=["Деловые инструменты","Органайзеры"],price=800+100*i,
                attrs={"registry_no":str(84000+i),"analog_of":"Basalt Planner","operation":"Новая",
                       "series":"Сфера","edition":"Выпуск "+str(i),"unit":"пользователь","qty_min":"8","qty_max":"19","country":"Россия","fstec":"да"})
        offers.append(o.model_dump_json())
    (tmp_path/"catalog.jsonl").write_text("\n".join(offers))
    e=Engine.open(replace(cfg,data=tmp_path))
    yield e
    e.close()


def products(r):
    return [c for b in r["blocks"] if b["type"]=="products" for c in b["items"]]


def test_imported_keys_and_class(external):
    e=external
    for q in ("АХ-LUX-315","номер в реестре 84001",e.catalog.offers_by_id["1"].name):
        assert products(search(e,q))[0]["offer"]["offer_id"]=="1"
    assert products(search(e,"AX-LUX-31"))
    assert products(search(e,"Деловые инструменты"))
    assert products(search(e,"Тщмфдгч"))
    assert products(search(e,"Novalxu"))


def test_foreign_spec_and_replacement(external):
    r=search(external,"Novalux / Сфера / Выпуск 1 / Новая, кол-во 11 ед.")
    line=r["blocks"][0]["lines"][0]
    assert line["card"]["offer"]["offer_id"]=="1" and line["qty"]==11
    r=search(external,"Basalt Planner")
    assert r["understood"]["intent"]=="out_of_catalog"
    assert any(b["type"]=="analogs" and b["items"] for b in r["blocks"])


def test_versioned_priorities_and_preview(engine,monkeypatch):
    query=Request(q="антивирус",mode="fast")
    base=products(engine.preview(query,[]))
    candidates=[c for c in base if c["score"]["tier"]==base[0]["score"]["tier"]]
    target=candidates[-1]["card_id"]
    rule=dict(id="p",title="Выбор магазина",order=2,scope={"channels":["api"]},target={"cards":[target]},
              action={"boost":100,"public_label":"Выбор","pin":{"card_id":target,"position":1}})
    module=SimpleNamespace(active_rules=lambda journal:(1,[rule]))
    monkeypatch.setattr(engine,"priority_store",module,raising=False)
    before=engine.journal.rows("select count(*) as n from searches")
    r=engine.preview(query,[rule])
    assert engine.journal.rows("select count(*) as n from searches")==before and r["cost"]["llm_calls"]==0
    assert products(r)[0]["card_id"]==target
    assert products(engine.search(query))[0]["card_id"]==target
    trace=next(s for s in r["trace"] if s["step"]=="business")
    assert trace["detail"]["priorities"][0]["id"]=="p"
    assert all(s["ms"]>=0 for s in r["trace"])
    assert {c["card_id"]:c["score"]["tier"] for c in base}=={c["card_id"]:c["score"]["tier"] for c in products(r)}


def test_document_flow_and_certified_systems(cfg,tmp_path):
    kb=tmp_path/"kb"
    shutil.copytree(cfg.kb,kb)
    with (kb/"categories.yaml").open("a") as rows:
        rows.write("- {id: sed_ecm, title: СЭД}\n"
                   "- {id: tax_reporting_edo, title: ЭДО, synonyms: [электронный документооборот, эдо с контрагентами]}\n")
    e=Engine.open(replace(cfg,kb=kb))
    try:
        for q,expected in (("электронный документооборот предприятия","sed_ecm"),
                           ("эдо с контрагентами","tax_reporting_edo")):
            assert expected in search(e,q)["understood"]["filters"]["category"]
        for q in ("средства защиты ГИС","защита ПДн предприятия","система защиты гостайны"):
            u=search(e,q)["understood"]
            assert u["intent"]=="compliance" and "fstec" in u["filters"]["certs"]
    finally:
        e.close()


def test_layout_with_count(engine):
    r=search(engine,"щит на 47пк".translate(LAYOUT))
    assert r["understood"]["filters"]["family"]==["shield"]
    assert r["understood"]["qty"]["value"]==47 and r["query"]["corrections"]


def test_offer_specific_attributes(external):
    o=external.catalog.offers_by_id["1"]
    assert o.registry and o.certs==["fstec"] and o.lic.metric=="user"
    assert products(search(external,"Органайзеры",filters={"origin":"russian","certs":["fstec"]}))


def test_priority_guarantees(engine):
    request=Request(q="антивирус")
    rows=products(search(engine,request.q))
    rule=dict(id="limit",scope={},order=1,target={"vendors":[rows[0]["vendor"]["id"]]},
              action={"max_in_top":{"n":1,"k":0}})
    result=products(engine.preview(request,[rule]))
    assert {c["card_id"] for c in rows}=={c["card_id"] for c in result}
    tier=rows[0]["score"]["tier"]
    if any(c["score"]["tier"]==tier and c["vendor"]!=rows[0]["vendor"] for c in rows):
        assert result[0]["vendor"]!=rows[0]["vendor"]
    exact=rows[0]["offer"]["sku"]
    rule.update(cross_tier=True,action={"boost":-100})
    c=products(engine.preview(Request(q=exact),[rule]))[0]
    assert c["offer"]["sku"]==exact and c["score"]["tier"]==0


@pytest.fixture
def supplier_facts(cfg,tmp_path):
    import json
    rows=[]
    for i,(low,high,price) in enumerate([(1,12,4000),(13,24,3100),(25,99,2500)]):
        rows.append(dict(offer_id=f"r{i}",sku=f"LX-{300+i}",name=f"Сетка: от {low} мест",family_id="setka",
                         vendor="Орбита",vendor_id="orbita",family_name="Сетка",category_id="endpoint_security",
                         vat=22,price=price,source_ids=[f"Учёт/{103+i}",f"feed-{80+i}"],
                         attrs=dict(aliases=["сеточник","зелёная панель"] if i==1 else [],
                                    task="сводить показания датчиков" if i==1 else ""),
                         lic=dict(qty_min=low,qty_max=high,metric="device",action="new")))
    (tmp_path/"catalog.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows))
    e=Engine.open(replace(cfg,data=tmp_path))
    yield e
    e.close()


def test_source_facts_pick_offer(supplier_facts):
    for q in ("артикул Учёт/104","feed-81","зелёная панель","сеточник","чтобы сводить показания датчиков"):
        r=search(supplier_facts,q)
        assert products(r)[0]["offer"]["offer_id"]=="r1",q
        if q.startswith("чтобы"):
            assert r["understood"]["intent"]=="task"


@pytest.mark.parametrize("legacy",[False,True])
def test_d4_reopen_snapshot(cfg,tmp_path,legacy):
    import json
    primary="УЧ/086"
    codes=[primary,"feed:2026.78","ref-94ab-1532"]
    extra={"склады":[{"остаток":12}],"кратность":4}
    attrs=dict(aliases=["орбитальный зонт"],certs=["fstec"],extra=extra,
               task="сводить данные с антенн",source_id=primary,source_ids=codes)
    row=dict(offer_id="external-1",name="Orbita Signal",family_id="signal",vendor="Орбита",
             price=2400,family_name="Orbita Signal",category_id="endpoint_security",
             category_path=["Сводить данные с антенн"])
    if legacy:
        attrs={k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in attrs.items()}
    else:
        row.update(source_id=primary,source_ids=codes,in_stock=False,delivery_days=0,
                   added_at="2026-11-21",promo=True,domestic=True)
    (tmp_path/"catalog.jsonl").write_text(json.dumps({**row,"attrs":attrs},ensure_ascii=False))
    engine=Engine.open(replace(cfg,data=tmp_path))
    try:
        offer=engine.catalog.offers_by_id[row["offer_id"]]
        assert offer.attrs["aliases"]==["орбитальный зонт"] and offer.attrs["extra"]==extra
        assert offer.attrs["source_ids"]==codes and offer.attrs["certs"]==["fstec"]
        if not legacy:
            assert offer.in_stock is False and offer.delivery_days==0 and offer.promo and offer.domestic
            assert offer.added_at=="2026-11-21"
        for q in [*codes,"орбитальный зонт","сводить данные с антенн"]:
            result=engine.search(Request(q=q,mode="fast"))
            hit=products(result)[0]["offer"]
            assert (hit["offer_id"],hit["source_id"],hit["source_ids"])==(row["offer_id"],primary,codes)
            if q in codes:
                assert any(s["step"]=="sku_lookup" and primary in str(s) for s in result["trace"])
            if q==attrs["task"]:
                assert result["understood"]["intent"]=="task"
        assert engine.card(offer.card_id)["variants"][0]["source_ids"]==codes
    finally:
        engine.close()


def test_d4_shared_parent_code(cfg,tmp_path):
    import json
    rows=[dict(offer_id=f"variant-{low}",source_ids=["parent:53","legacy:12"],family_id="signal",name=f"Orbita {low}",
               price=1000,lic=dict(qty_min=low,qty_max=high,metric="user"))
          for low,high in [(11,50),(1,10)]]
    rows.append(dict(offer_id="unrelated",source_ids=["legacy:12"],family_id="viewer",name="Orbita Viewer",price=700))
    (tmp_path/"catalog.jsonl").write_text("\n".join(map(json.dumps,rows)))
    engine=Engine.open(replace(cfg,data=tmp_path))
    try:
        assert products(search(engine,"parent:53"))[0]["offer"]["offer_id"]=="variant-1"
        result=search(engine,"Орбита [parent:53] — 17 шт")
        line=next(b for b in result["blocks"] if b["type"]=="spec")["lines"][0]
        assert line["card"]["offer"]["offer_id"]=="variant-11"
        assert {c["card_id"] for c in products(search(engine,"legacy:12"))}=={"signal","viewer"}
        ambiguous=search(engine,"Позиция [legacy:12] — 17 шт")
        assert next(b for b in ambiguous["blocks"] if b["type"]=="spec")["unresolved"]==[1]
    finally:
        engine.close()


def test_budget_at_band_including_vat(supplier_facts):
    for q in ("Сетка на 16 мест, всего до 50 000 ₽","Сетка на 16 мест до 3 200 ₽ за место"):
        r=search(supplier_facts,q)
        calc=products(r)[0]["calc"]
        assert calc["total"]==49600 and not calc.get("over_budget_rub")
    for q in ("Сетка на 16 мест всего до 49 000 ₽","Сетка на 16 мест до 3 000 ₽ за место"):
        r=search(supplier_facts,q)
        c=products(r)[0]
        assert c["offer"]["offer_id"]=="r1" and c["calc"]["vat"]==22
        assert c["calc"]["over_budget_rub"]==c["calc"]["total"]-c["calc"]["budget_rub"]>0
        assert any("Выше бюджета" in line for line in c["score"]["why"])


@pytest.mark.parametrize("verb",["продлить","перенести","активировать"])
def test_answer_with_product(engine,verb):
    r=search(engine,"Подскажите, как "+verb+" лицензию North Shield?")
    assert r["understood"]["intent"]=="question" and r["blocks"][0]["type"]=="answer"
    assert verb in r["blocks"][0]["title"] and len(r["blocks"][0]["text"].split("."))>=3
    assert products(r) and all(c["card_id"].split(":")[0]=="shield" for c in products(r))


def test_registry_answer_consistency(external):
    found=search(external,"запись в реестре 84002")
    assert products(found) and not any(b["type"]=="not_in_catalog" for b in found["blocks"])
    missing=search(external,"номер в реестре 90878")
    assert not products(missing) and any(b["type"]=="answer" for b in missing["blocks"])


def test_variant_timer(engine,monkeypatch):
    import kuznitsa.engine as module
    ticks=[0]
    choose=module.select
    def measured(*args,**kwargs):
        ticks[0]+=1
        return choose(*args,**kwargs)
    monkeypatch.setattr(module,"select",measured)
    monkeypatch.setattr(engine,"timer",lambda:ticks[0]/1000)
    r=search(engine,"антивирус")
    steps={s["step"]:s["ms"] for s in r["trace"]}
    assert steps["variants"]==ticks[0]>0 and steps["filters"]==0


def test_competing_role(cfg,tmp_path):
    kb=tmp_path/"kb"
    shutil.copytree(cfg.kb,kb)
    (kb/"roles.yaml").write_text("- id: coordinator\n  title: Координатор\n  aliases: [координатор, сотрудники]\n"
        "  slots: [{category: endpoint_security, must: true, families: [shield]}]\n")
    engine=Engine.open(replace(cfg,kb=kb))
    try:
        assert search(engine,"софт для координатора")["understood"]["intent"]=="role_kit"
        for q in ("щит для сотрудников на рабочие места","щит набор для координатора до 8200"):
            r=search(engine,q)
            assert not any(b["type"]=="kit" for b in r["blocks"]) and products(r)
    finally:
        engine.close()


def test_priority_scope_and_restrictions(engine):
    req=Request(q="антивирус")
    cards=products(search(engine,req.q))
    target=cards[0]["card_id"]
    scoped=dict(id="plan",order=1,target={"categories":["security"],"cards":[target],"tags":["subscription","perpetual"]},
        scope={"profiles":["guest"],"segments":["smb"],"queries":["АНТИВИРУС"],"channels":["api"],"to":"2099-01-01"},
        action={"criteria":{"price_low":1},"boost":40,"public_label":"Проверено"})
    result=engine.preview(req,[scoped])
    flagged=[c["card_id"] for c in products(result) if any(b["kind"]=="priority" for b in c["badges"])]
    assert flagged==[target]
    scoped["scope"]["to"]="2001-01-01"
    assert not any(b["kind"]=="priority" for c in products(engine.preview(req,[scoped])) for b in c["badges"])


def test_optional_source_name_and_preview(supplier_facts):
    empty=search(supplier_facts,"подписка на violetflow")
    assert empty["understood"]["intent"]=="out_of_catalog" and not products(empty)
    r=supplier_facts.preview(Request(q="Сетка",mode="naive"),[])
    assert r["mode"]=="naive" and not supplier_facts.journal.rows("select search_id from searches")
    assert search(supplier_facts,"номер в реестре 123456")["blocks"][0]["type"]=="answer"


def test_law_and_adjectival_roles():
    from kuznitsa.text import lemma
    from kuznitsa.understand.kits import CUE,terms
    assert terms("сопровождение 223 ФЗ")==terms("сопровождение 223-ФЗ")
    assert terms("сопровождение 223 фз")!=terms("сопровождение 44 фз")
    assert lemma("главного")==lemma("главный") and lemma("дежурного")==lemma("дежурный")
    for q in ("переводим мастерскую","перевести подразделение","замена инструментов","импортозамещение отдела","подбираю по"):
        assert CUE.search(q)


def test_child_alias_precedes_parent_title():
    from kuznitsa.understand.kits import KitIndex
    kb=SimpleNamespace(rows={"roles":{},"industries":{
        "craft":{"title":"Ремесло и переплёт","aliases":["переплёт"]},
        "binding":{"title":"Книжная мастерская","aliases":["переплёт"],"parent":"craft"}}})
    index=KitIndex(kb)
    req=Request(q="софт для переплёта",mode="fast")
    winner,*_=index.pick(None,req,req.q,[],{},"industry",0,"",[],False)
    assert winner==("industry","binding")
    req=Request(q="отечественное по",mode="fast")
    assert index.pick(None,req,req.q,[],{},"broad",0,"",[],False)[:2]==(None,[])
    kb.rows["roles"]["kit_binding"]={"title":"Комплект для переплётного бюро","aliases":["переплётное бюро"]}
    kb.rows["industries"]["craft"]["aliases"].append("переплётное бюро")
    index=KitIndex(kb)
    req=Request(q="софт для переплётного бюро",mode="fast")
    winner,*_=index.pick(None,req,req.q,[],{},"industry",0,"",[],False)
    assert winner==("role","kit_binding")
