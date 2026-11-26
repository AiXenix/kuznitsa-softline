"""Регрессии понимания класса на фиде с пересекающимися именами и лицензиями."""
from dataclasses import replace
import json
from shutil import copytree

import pytest
import yaml

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def shop(cfg,tmp_path_factory):
    data=tmp_path_factory.mktemp("feed_language")
    kb=copytree(cfg.kb,data/"kb")
    def dictionary(group,rows):
        (kb/(group+".yaml")).write_text(yaml.safe_dump(rows,allow_unicode=True))
    dictionary("hardware_hints",[
        dict(id="portable",hardware_class="laptop",hardware_feed_classes=["hw"],
             trigger_words=["ноут","ноутбук"],prompt="Искали ПО для ноутбука?",software_classes=["tools"])])
    dictionary("slang_feed",[dict(term="норддеск",maps_to={"text":"NordDesk"})])
    dictionary("feed_tasks",[
        dict(id="archive",sections=["Архиваторы"],phrases=["уменьшить архив","сжать папку"]),
        dict(id="remote",sections=["Дистанционное управление"],aliases=["удаленный рабочий стол"]),
        dict(id="virtual",sections=["Гипервизоры"],aliases=["виртуальные машины"])])
    rows=[]
    def add(key,name,group,label,vendor="SoftWorks",action="new",metric=None,domain="software",**limits):
        rows.append(dict(offer_id=key+"_"+action,group_id=key,family_id=key,class_id=group,category_id=group,
                         name=name+" "+action,family_name=name,vendor=vendor,price=100,domain=domain,
                         category_path=[domain,label],lic=dict(action=action,metric=metric,**limits)))
    add("pc","Mobile Note","hw","Ноутбуки",domain="hardware")
    add("desk","NordDesk","tools","Утилиты")
    add("desk","NordDesk","tools","Утилиты",action="renewal")
    add("home","Terra Home","tools","Утилиты",action="renewal",audience="home")
    add("noise","Удаленный рабочий стол с роботами","tools","Утилиты")
    add("arch","Zip Kit","zip","Архиваторы")
    add("access","RemoteStation","remote","Дистанционное управление")
    for i in range(5):
        add("vm"+str(i),"Hyper Rack "+str(i),"virt","Гипервизоры",vendor="Blue Hill" if i==3 else "Lab")
        add("auto"+str(i),"Process Control "+str(i),"auto","Системы автоматизации",
            metric="user" if i==4 else "server",qty_max=100)
    (data/"catalog.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.MonkeyPatch.context() as env:
        env.setenv("KZ_KB_DIR",str(kb))
        engine=Engine.open(replace(cfg,data=data,kb=kb),llm=Disabled())
        try:
            yield lambda q: engine.search(Request(q=q,mode="fast",source="eval"))
        finally:
            engine.close()


@pytest.mark.parametrize("q",["легкий ноут","ноут компактный","офисный ноут для сотрудника"])
def test_hardware_inside_phrase(shop,q):
    r=shop(q)
    assert r["blocks"][0]["category_id"]=="hw"
    assert r["blocks"][0]["items"][0]["domain"]=="hardware"


def test_unrecognized_query_clarifies_feed_sections(shop):
    r=shop("щцхвфз")
    b=r["blocks"][0]
    assert r["understood"]["intent"]=="broad" and b["type"]=="clarify"
    options={x["apply"]["category"] for x in b["options"]}
    assert len(options) in (2,3)
    assert all(x["type"]!="categories" for x in r["blocks"])
    assert all(c["fill"] for x in r["blocks"] if x["type"]=="products" for c in x["items"])


@pytest.mark.parametrize("q",["приложение норддеск","платформа норддеск","операционная система норддеск"])
def test_brand_with_introductory_noun(shop,q):
    r=shop(q)
    assert r["understood"]["intent"]=="product"
    assert r["blocks"][0]["items"][0]["card_id"]=="desk"


def test_task_dictionary_is_order_independent(shop):
    assert shop("чем папки с фотографиями сжать")["blocks"][0]["category_id"]=="zip"


def test_quantity_selects_variants_and_keeps_the_section(shop):
    r=shop("системы автоматизации на 36 пользователей")
    b=r["blocks"][0]
    assert b["category_id"]=="auto" and b["total"]==5
    assert b["items"][0]["card_id"]=="auto4" and b["items"][0]["calc"]["total"]==3600
    assert all(c["calc"]["qty"] is None and any("уточн" in w for w in c["score"]["why"])
               for c in b["items"][1:])


def test_two_word_vendor_with_only_one_product(shop):
    r=shop("виртуальные машины Blue Hill")
    cards=r["blocks"][0]["items"]
    assert r["blocks"][0]["category_id"]=="virt" and cards[0]["card_id"]=="vm3"
    assert len(cards)>=4 and all(c.get("fill") and c["card_id"].startswith("vm") for c in cards[1:])


def test_class_is_kept_when_vendor_only_sells_in_another_section(shop):
    r=shop("виртуальные машины SoftWorks")
    b=r["blocks"][0]
    assert b["category_id"]=="virt" and "нет" in r["understood"]["agent_note"]
    assert b["items"][0]["card_id"] in {"desk","noise","arch","access","home","pc"}
    assert all(c.get("fill") and not c["card_id"].startswith("vm") for c in b["items"])


def test_section_alias_wins_over_partial_product(shop):
    b=shop("удаленные рабочие столы")["blocks"][0]
    assert b["category_id"]=="remote" and b["items"][0]["card_id"]=="access"


def test_renewal_for_specific_named_product(shop):
    for q in ("лицензия на продление NordDesk","продление лицензии Норддеск"):
        r=shop(q)
        c=r["blocks"][0]["items"][0]
        assert r["understood"]["intent"]=="renewal" and c["card_id"]=="desk"
        assert c["offer"]["offer_id"]=="desk_renewal"
        assert all(card["offer"]["action"]=="renewal" for card in r["blocks"][0]["items"])
        assert any(card.get("fill") for b in r["blocks"][1:] if b["type"]=="products" for card in b["items"])


def test_guest_can_renew_a_home_product(shop):
    r=shop("продлить свою лицензию Terra Home")
    item=r["blocks"][0]["items"][0]
    assert r["understood"]["intent"]=="renewal" and item["offer"]["offer_id"]=="home_renewal"
