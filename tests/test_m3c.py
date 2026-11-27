"""Контракт r10 для импорта правил, редактора магазина и поисковых запросов."""
import json
import logging
from dataclasses import replace
from shutil import copytree

import pytest
import yaml
from fastapi.testclient import TestClient
from kuznitsa.app import create_app
from kuznitsa.engine import Engine
from kuznitsa.kb.loader import load
from kuznitsa.kb.upsell import validate
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


HARDWARE=[
    ("network_adapter","сетевой адаптер","86247"),("power_protection","фильтр питания","82661"),
    ("power_bank","внешний аккумулятор","91451"),("cables","кабель вывода","80081"),
    ("intercom","видеодомофон","137173"),("av_equipment","кинопроектор","91916"),
    ("office_furniture","кресло оператора","137214"),("home_appliances","кофемашина","174449"),
    ("power_tools","перфоратор","269374"),("webcam_conf","камера для звонков","89623"),
    ("scanner","сканер документов","94641"),("desktop","комп","70187"),("server","сервак","86563"),
]
RULE=dict(id="target",reason="Сохранение резервной копии",when={"families":["Alpha Desk"]},
          offer={"classes":["backup"],"families":["Vault Copy"],"strict":True,"exclude_words":["HOSTED"]})


@pytest.fixture
def snapshot(cfg,tmp_path,monkeypatch):
    root=copytree(cfg.kb,tmp_path/"kb")
    (root/"upsell_r9.yaml").write_text(yaml.safe_dump([RULE]))
    data=tmp_path/"feed"
    data.mkdir()
    def row(ident,title,section,domain="software",**fields):
        return dict(offer_id=ident,group_id=ident,family_id=ident,name=title,family_name=title,
                    vendor="Acme",category_id=section,class_id=section,category_path=[domain,section],
                    domain=domain,price=100,**fields)
    rows=[row("base","Alpha Desk","suite"),row("copy","Acme Vault Copy","backup"),
          row("hosted","Acme Vault Copy Hosted","backup"),row("other","Acme Archive","backup"),
          row("plugin","Extension for Vault Copy","backup",vendor_id="plugin-vendor"),
          row("devices","Alpha Seat","suite",lic={"metric":"device"}),row("cpu","Alpha DB (на 1 процессор)","suite"),
          row("server","Alpha Panel (лицензия на сервер)","suite"),
          row("cloud","Alpha Cloud","suite",attrs={"license_program":"CSP"}),
          row("crypto","КриптоПро CSP","suite")]
    slang=[dict(term=term,maps_to=dict(attr="hardware_class",value=kind),note=f"(фид {section})")
           for kind,term,section in HARDWARE if term not in ("сервак","комп")]
    slang.extend(dict(term=term,maps_to=dict(attr=attr,value=value)) for term,attr,value in
                 [("цсп","license_type","csp"),("комп","license_metric","device"),("сервак","license_metric","server")])
    slang.append(dict(term="крипто про цсп",maps_to={"family":"crypto"}))
    (root/"families/crypto.yaml").write_text(yaml.safe_dump([dict(id="crypto",name="КриптоПро CSP",vendor="east",category="office_suite")]))
    (root/"slang_more.yaml").write_text(yaml.safe_dump(slang,allow_unicode=True))
    rows.extend(row("hw"+section,"Модель "+kind,section,"hardware") for kind,_,section in HARDWARE)
    hints=[dict(id=kind,hardware_class=kind,hardware_feed_classes=[section],trigger_words=[term],
                prompt="Искали ПО?",software_classes=["suite"]) for kind,term,section in HARDWARE[-2:]]
    (root/"hardware_hints.yaml").write_text(yaml.safe_dump(hints))
    (data/"catalog.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n")
    monkeypatch.setenv("KZ_KB_DIR",str(root))
    return replace(cfg,data=data,kb=root)


def test_invalid_base_rule_does_not_interrupt_storefront(snapshot,caplog,monkeypatch):
    path=snapshot.kb/"upsell_r9.yaml"
    broken=RULE|dict(id="broken",offer={"classes":["backup"],"strict":"да"})
    path.write_text(yaml.safe_dump([broken,RULE]))
    caplog.set_level(logging.WARNING,logger="kuznitsa.kb.upsell")
    kb=load(snapshot.kb)
    assert list(kb.upsell)==["target"] and not kb.errors
    assert any("broken" in w and "upsell_r9.yaml [1]" in w for w in kb.report()["warnings"])
    assert "broken" in caplog.text
    engine=Engine.open(snapshot,llm=Disabled())
    monkeypatch.setenv("KZ_ADMIN_OPEN","1")
    monkeypatch.setenv("KZ_ADMIN_TOKEN","unit-test")
    try:
        with TestClient(create_app(engine,snapshot)) as api:
            result=api.post("/api/search",json={"q":"Alpha Desk","mode":"fast"})
            assert result.status_code==200
            cards=[item.get("card",item) for block in result.json()["blocks"] for item in block.get("items",[])]
            assert [c["card_id"] for c in cards if c.get("rule_id")=="target"]==["copy"]
            headers={"X-Admin-Token":"unit-test"}
            assert api.post("/api/admin/upsell",json=broken,headers=headers).status_code==422
            assert api.put("/api/admin/upsell/target",json={"offer":broken["offer"]},headers=headers).status_code==422
            rec=engine.catalog.feed.recommend
            assert rec.eligible_targets(dict(RULE["offer"],families=["Missing"]))==set()
            assert rec.eligible_targets({"vendors":["Acme"],"classes":["backup"],"strict":True,"exclude_words":["hosted"]})=={"copy","other","plugin"}
    finally:
        engine.close()


def test_context_and_hardware_sections(snapshot):
    engine=Engine.open(snapshot,llm=Disabled())
    def search(q):
        return engine.search(Request(q=q,mode="fast"))
    try:
        for _,term,section in HARDWARE:
            result=search(term)
            assert result["blocks"][0]["category_id"]==section,term
        for q,section in [("комп для оператора","70187"),("сервак в офис","86563")]:
            assert search(q)["blocks"][0]["category_id"]==section
        for q,attr,value,first in [("на сервак","metric","server","server"),("на процессор","metric","cpu","cpu"),
                                    ("лицензия на 5 компов","metric","device","devices"),("цсп","license_type","csp","cloud")]:
            r=search(q)
            assert r["understood"]["filters"][attr]==value
            assert r["blocks"][0]["items"][0]["card_id"]==first
        assert search("крипто про цсп")["blocks"][0]["items"][0]["card_id"]=="crypto"
    finally:
        engine.close()


@pytest.mark.parametrize("side",[{"classes":["1"],"strict":True},{"vendors":["v"],"exclude_words":"SSL"},
                                 {"vendors":["v"],"audience":["other"]},{"exclude_words":["SSL"]}])
def test_invalid_console_conditions(side):
    with pytest.raises(ValueError):
        validate(RULE|{"offer":side})


def test_restore_catalog_names_before_absence(snapshot):
    from kuznitsa.understand.repair import LAYOUT
    rows=[("area","Astra Linux Special Edition"),("line","Delta Endpoint Security"),("editor","Northwind Acrobat Professional"),
          ("suite","МойОфис Стандартный"),("seal","КриптоАрм ГОСТ"),("scanner","Сетевой сканер Про"),
          ("neo","Монитор Titan Neo"),("version","Map Editor 13")]
    with (snapshot.data/"catalog.jsonl").open("a") as f:
        for key,title in rows:
            r=dict(offer_id=key,group_id=key,family_id=key,name=title,family_name=title,class_id="tools",category_id="tools",
                   vendor="SoftTools",domain="software",price=100,category_path=["ПО","Утилиты"])
            print(json.dumps(r),file=f)
    engine=Engine.open(snapshot,llm=Disabled())
    try:
        for query,ident in [("астра линукс специальная".translate(LAYOUT),"area"),("крипто про цсп".translate(LAYOUT),"crypto"),
                            ("delat endpoint securtiy","line"),("northwind acroabt pro","editor"),
                            ("moy ofis standartnyy","suite"),("kripto arm gost","seal"),("setevoy skaner pro","scanner"),
                            ("дельта эндпоинт секьюрити","line")]:
            result=engine.search(Request(q=query,mode="fast"))
            assert result["understood"]["intent"]=="product",query
            assert result["blocks"][0]["items"][0]["card_id"]==ident,query
        for query in ("Reason 13","Luminar Neo"):
            result=engine.search(Request(q=query,mode="fast"))
            assert result["understood"]["intent"]=="out_of_catalog",query
            assert result["blocks"][0]["type"]=="not_in_catalog"
    finally:
        engine.close()


def test_feed_classes_quantities_and_small_business(snapshot):
    def row(key,title,section,category,unit=None):
        return dict(offer_id=key,group_id=key,family_id=key,name=title,family_name=title,vendor="Delta",
                    domain="software",class_id=section,category_id=section,category_path=["ПО",category],
                    lic={"metric":unit},price=100)
    rows=[row("micro","Delta Small Office Security","business","Антивирусы для организаций"),
          row("virt","Delta Security для виртуальных сред","business","Антивирусы для организаций"),
          row("home","Delta Family","home","Антивирусы для дома"),
          row("phone","SafeMobile","mobile","Защита информации для смартфонов","device"),
          row("server_suite","Server Fleet","servers","Серверное ПО","server"),
          row("video","VideoCut","edit","Видеоредакторы"),
          row("writer","TypeWriter","write","Текстовые редакторы")]
    rows.extend(row("user"+str(n),"Mobile User "+str(n),"phone_user","Защита данных на смартфоне","user")
                for n in range(3))
    with (snapshot.data/"catalog.jsonl").open("a") as f:
        for r in rows:print(json.dumps(r),file=f)
    engine=Engine.open(snapshot,llm=Disabled())
    try:
        for query,key in [("Delta для небольшой фирмы","micro"),("антивирь домой","home"),
                          ("редакторы видео","video"),("редактор текста","writer")]:
            result=engine.search(Request(q=query,mode="fast"))
            assert result["blocks"][0]["items"][0]["card_id"]==key,query
        for query,key in [("защита смартфонов на 18 узлах","phone"),("серверное ПО на 18 узлов","server_suite")]:
            result=engine.search(Request(q=query,mode="fast"))
            card=result["blocks"][0]["items"][0]
            assert result["understood"]["qty"]["value"]==18
            assert card["card_id"]==key and card["calc"]["total"]==1800
    finally:
        engine.close()


def test_unknown_audience_and_word_only_trigger(snapshot):
    engine=Engine.open(snapshot,llm=Disabled())
    try:
        rec=engine.catalog.feed.recommend
        rec.provider=None
        def picks(q,when,offer):
            rec.compiled=rec.compile([RULE|{"when":when,"offer":offer}])
            return [cid for cid,r in rec.picks(engine.journal,q,["base"],4) if r["id"]=="target"]
        # Оба поля независимы. Неопределённая аудитория покупки или товара допустима.
        assert picks("alpha",{"families":["Alpha Desk"],"audience":["business"]},{"families":["copy"]})==["copy"]
        assert picks("alpha",{"families":["Alpha Desk"]},{"families":["copy"],"audience":"home"})==["copy"]
        assert not picks("alpha для дома",{"families":["Alpha Desk"],"audience":["business"]},{"families":["copy"]})
        assert not picks("alpha для дома",{"families":["Alpha Desk"]},{"families":["copy"],"audience":["business"]})
        when={"query_words":["резервный архив"]}
        assert picks("нужен резервный архив",when,{"families":["copy"]})==["copy"]
        assert not picks("нужен резервный архиватор",when,{"families":["copy"]})
    finally:
        engine.close()


def test_price_ceiling_in_feed_keeps_hardware_and_software(snapshot):
    rows=[]
    for key,category,name,domain in (("pc","70187","desktop","hardware"),("av","av","Антивирусы для организаций","software")):
        for price in (10,500,9000):
            ident=key+str(price)
            rows.append(dict(offer_id=ident,group_id=ident,name=ident,family_name=ident,class_id=category,category_id=category,
                             category_path=[domain,name],domain=domain,lic={"metric":"device"},vendor="Acme",price=price))
    with (snapshot.data/"catalog.jsonl").open("a") as f:
        for r in rows:print(json.dumps(r),file=f)
    engine=Engine.open(snapshot,llm=Disabled())
    try:
        for q,section,limit in (("комп до 1 000 руб.","70187",1000),("антивирь до 20 ₽","av",20),
                                ("антивирус на 3 пк до 35 ₽","av",35),("комп до 1","70187",1)):
            r=engine.search(Request(q=q,mode="fast"))
            b=r["blocks"][0]
            assert r["understood"]["filters"]["price_max"]==limit
            if limit==1:
                # По требованиям N4: при отсутствии товаров в бюджете не обнуляем ответ,
                # а честно предупреждаем и показываем самые доступные карточки того же раздела.
                assert b["type"]=="products" and b["category_id"]==section and b["items"]
                assert "дешевле" in r["understood"]["agent_note"].lower()
                assert b["items"][0]["offer"]["price"]==10
                continue
            assert b["type"]=="products" and b["category_id"]==section and b["items"]
            for c in b["items"]:
                assert 0 < (c["calc"]["total"] or c["offer"]["price"]) <= limit
    finally:
        engine.close()
