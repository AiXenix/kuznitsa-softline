"""Выдача фида с пересекающимися названиями продуктов, разделов и кодов."""
from dataclasses import replace
import json
from shutil import copytree

import pytest
import yaml

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def feed(cfg,tmp_path_factory):
    data=tmp_path_factory.mktemp("m3g")
    kb=copytree(cfg.kb,data/"kb")
    tasks=[("crm","CRM/ERP-системы",["CRM для предприятия"]),("draw","Схемы и диаграммы",["редактор диаграмм"]),
           ("dtp","Издательские системы",["программы для вёрстки"]),("convert","Кодировщики",["конвертер медиафайлов"]),
           ("photo","Графические редакторы",["pixel art"]),("sound","Аудиоредакторы",["audio editor"])]
    (kb/"feed_tasks.yaml").write_text(yaml.safe_dump([dict(id=i,sections=[title],aliases=aliases)
                                                     for i,title,aliases in tasks],allow_unicode=True))
    rows=[]
    def add(cid,name,section,vendor="North",domain="software",sku=None,description=""):
        rows.append(dict(group_id=cid,offer_id=cid,family_id=cid,family_name=name,name=name,
                         vendor=vendor,domain=domain,class_id=section,category_id=section,
                         category_path=[domain,section],sku=sku,description=description,price=100))
    add("switch","N42","Коммутаторы",domain="hardware")
    add("ssd","Flash S12","Внутренние твердотельные накопители (SSD)",domain="hardware")
    add("net","Сетевой фильтр","Фильтры",domain="hardware")
    add("conf","Media Access Console","Связь",sku="SSD")
    add("pro","Professional Reporting Office","Аналитика")
    add("crm-name","Customer Resource Monitor","Мониторинг",vendor="Customer")
    add("suite","Other Pro Plus Premium Standard Business Home Suite Studio Edition 2024","Утилиты")
    add("audio","Demo Pro Audio","Аудиоредакторы")
    add("safe","Kaspersky Plus","Защита",vendor="Kaspersky")
    add("repair","North Canvas Pro","Графические редакторы")
    add("part","Partial Pixel Studio","Графические редакторы")
    for slot in range(4):
        add(f"mac{slot}",f"Quill {slot}","Текстовые редакторы",description="Платформа: Mac OSX • Поставка: подписка")
    for i,title,_ in tasks:add(i,"Demo "+i,title)
    tree={c["group_id"]:[c["family_name"],c["class_id"]] for c in rows}
    tree["absent"]=["DrawLark","Графические редакторы"]
    (data/"feed_categories.json").write_text(json.dumps(tree))
    (data/"catalog.jsonl").write_text("\n".join(json.dumps(c) for c in rows))
    engine=Engine.open(replace(cfg,data=data,kb=kb),llm=Disabled())
    try:
        yield lambda q:engine.search(Request(q=q,mode="fast",source="eval"))
    finally:
        engine.close()


@pytest.mark.parametrize("q",["LumaNest Pro","ShapelyForge Plus","VoxMint 4 Pro","InkGale для Mac",
                              "SilentQuill Premium","ClearNook Standard","VaultMuse Business","MintVale Home",
                              "RedQuill для Windows","SlateGlow Server","DewLeaf Suite","EbonSky Studio",
                              "FirWing Edition","RainMint 2024","«Берестограф» Pro","QuartzQuill v4.2"])
def test_edition_without_name_is_missing(feed,q):
    r=feed(q)
    assert r["understood"]["intent"]=="out_of_catalog"
    assert r["understood"]["zero_reason"]=="not_in_catalog" and r["blocks"][0]["type"]=="not_in_catalog"
    options=next(b["options"] for b in r["blocks"] if b["type"]=="clarify")
    sections={o["apply"]["category"] for o in options}
    cards=next(b["items"] for b in r["blocks"] if b["type"]=="products")
    assert len(cards)>=4 and all(c.get("fill") and c["domain"]=="software" for c in cards)
    assert cards[0]["category"]["id"] in sections
    assert all(c["category"]["title"] in c["label"] for c in cards)


def test_absent_family_resolves_to_its_tree_section(feed):
    r=feed("DrawLark Pro")
    assert r["blocks"][0]["type"]=="not_in_catalog"
    block=r["blocks"][1]
    assert block["type"]=="analogs" and block["items"][0]["card"]["category"]["id"]=="Графические редакторы"


def test_opaque_name_with_platform_offers_compatible_options(feed):
    r=feed("FableMuse для Mac")
    cards=next(b["items"] for b in r["blocks"] if b["type"]=="products")
    assert r["blocks"][0]["type"]=="not_in_catalog"
    assert len(cards)==4 and all(c["card_id"].startswith("mac") for c in cards)


@pytest.mark.parametrize("q,section",[("PrismPixel Pro","Графические редакторы"),
                                      ("VoxMint 4 Pro Audio","Аудиоредакторы")])
def test_subject_clue_proposes_replacements_without_claiming_match(feed,q,section):
    result=feed(q)
    assert result["blocks"][0]["type"]=="not_in_catalog"
    block=result["blocks"][1]
    assert block["type"]=="analogs" and block["items"]
    assert all(item["card"]["category"]["id"]==section for item in block["items"])


@pytest.mark.parametrize("q,cid",[("Kaspersky Plus","safe"),("North Canvsa Pro","repair")])
def test_confirmed_identity_survives_edition_filter(feed,q,cid):
    r=feed(q)
    assert r["understood"]["intent"]=="product" and r["blocks"][0]["items"][0]["card_id"]==cid


@pytest.mark.parametrize("q,cid",[("свитч сетевой","switch"),("управляемый свитч","switch"),("внутренний SSD","ssd")])
def test_hardware_class_precedes_modifier_or_partial_sku(feed,q,cid):
    r=feed(q)
    assert r["understood"]["intent"]=="category"
    assert r["blocks"][0]["items"][0]["card_id"]==cid


@pytest.mark.parametrize("q,cid",[("CRM для предприятия","crm"),("редакторы диаграмм","draw"),
                                   ("программы для вёрстки","dtp"),("конвертеры медиафайлов","convert")])
def test_class_name_opens_feed_section(feed,q,cid):
    r=feed(q)
    assert r["understood"]["intent"]=="category" and r["blocks"][0]["items"][0]["card_id"]==cid
