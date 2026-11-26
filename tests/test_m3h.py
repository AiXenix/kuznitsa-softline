import json
from dataclasses import replace
from pathlib import Path
from shutil import copyfile, copytree

import httpx
import pytest

from kuznitsa.engine import Engine
from kuznitsa.kb.loader import load
from kuznitsa.llm.jev import Jev
from kuznitsa.schema import Request
from kuznitsa.suggest.index import suggest


@pytest.fixture(scope="module")
def snapshot(cfg,tmp_path_factory):
    data=tmp_path_factory.mktemp("m3h")
    kb=copytree(cfg.kb,data/"kb")
    copyfile(Path(__file__).parent/"fixtures/m3h/feed_analogs.yaml",kb/"feed_analogs.yaml")
    catalog=[]
    def add(cid,title,section,vendor="North",description="",registry=False,domain="software"):
        catalog.append(dict(offer_id=cid,group_id=cid,name=title,family_name=title,class_id=section,
                            category_id=section,category_path=[domain,section],domain=domain,vendor=vendor,
                            description=description,registry=registry,price=100))
    for section,names in [
        ("Программы для обработки цифрового фото",["ФотоМАСТЕР","Домашняя Фотостудия","PhotoKit","CameraPlus"]),
        ("Аудиоредакторы",["Ableton Live","SONAR X2 Studio","MusicKit","BeatPad"]),
        ("Файловые менеджеры",["File Commander","Eltima Commander One","FileKit","FileBoss"]),
        ("Другие решения удаленного доступа",["AnyDesk","Remote PC","BeamView"]),
        ("Российские решения удаленного доступа (Импортозамещение)",["RuDesktop","АССИСТЕНТ"]),
        ("Базовые программы",["Платформа nanoCAD","КОМПАС-3D","Bricsys BricsCAD Pro","ZWCAD","Плагин для AutoCAD"]),
        ("Операционные системы Windows",["Windows"]),
        ("Российские операционные системы (Импортозамещение)",["РЕД ОС","ОС Медведь"]),
        ("Операционные системы Linux & Unix",["Fedora","Astra Linux","ОС Рябина","Acme Linux"]),
        ("ЧПУ",["DNC Precision","CNC Syntax Editor"]),
    ]:
        for name in names:
            add(name,name,section,vendor={"AnyDesk":"AnyDesk","ФотоМАСТЕР":"AMS Software"}.get(name,"North"),
                registry=name=="ОС Рябина")
    add("wrong-vendor","AnyDesk","ЧПУ",vendor="Other")
    add("endpoint","Fern Guard","Антивирусы",vendor="Fern")
    add("endpoint2","Fern Desktop Security","Антивирусы",vendor="Fern")
    add("aux","Fern","Отчётность",vendor="Fern")
    add("security","Another Antivirus","Антивирусы",vendor="Oak")
    add("mix","WaveLoom","Музыкальные студии",description="Запись гитарных партий и создание аранжировок")
    add("closest","ChordKit","Музыкальные студии",description="Запись гитарных партий")
    add("other","TapeDeck","Музыкальные студии",description="Перегонка старых кассет")
    for n in range(62):
        add("device"+str(n),"Device "+str(n),"Класс приборов "+str(n),domain="hardware")
    (data/"catalog.jsonl").write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in catalog))
    return replace(cfg,data=data,kb=kb)


@pytest.fixture(scope="module")
def feed(snapshot):
    sent=[]
    def classify(request):
        data=json.loads(request.content)
        options=data["questions"]["section"]["criteria"]
        assert 40<=len(options)-1<=60 and "none" in options
        assert "Аудиоредакторы" in options and any("приборов" in text for text in options.values())
        name=data["state"]["название продукта"]
        sent.append(name)
        sid=next(k for k,v in options.items() if v=="Аудиоредакторы")
        p=.54 if name=="cloudreed" else .81
        return httpx.Response(200,json={"answers":{"section":{"choice":sid,"probabilities":{sid:p}}},"usage":{"cost":.0001}})
    engine=Engine.open(snapshot,llm=Jev(transport=httpx.MockTransport(classify)))
    engine.decisions.run_budget=.01
    yield engine,sent
    engine.close()


def search(feed,q,mode="fast"):
    return feed[0].search(Request(q=q,mode=mode,source="eval"))


def analogs(result):
    return next(block for block in result["blocks"] if block["type"]=="analogs")


@pytest.mark.parametrize("q,first,section",[
    ("Luminar Neo","ФотоМАСТЕР","Программы для обработки цифрового фото"),
    ("Reason 13","Ableton Live","Аудиоредакторы"),
    ("Total Commander","File Commander","Файловые менеджеры"),
    ("чем заменить Тимвьюер","AnyDesk","Другие решения удаленного доступа"),
    ("замена Автокад","Платформа nanoCAD","Базовые программы"),
])
@pytest.mark.parametrize("mode",["fast","smart"])
def test_curated_replacements(feed,q,first,section,mode):
    result=search(feed,q,mode)
    assert result["blocks"][0]["type"]=="not_in_catalog"
    block=analogs(result)
    assert block["title"]=="Нет в каталоге. Похожие по назначению: "+section
    ids=[item["card"]["card_id"] for item in block["items"]]
    assert len(set(ids))>=4 and ids[0]==first and "wrong-vendor" not in ids
    assert not ({"DNC Precision","CNC Syntax Editor","Плагин для AutoCAD"}&set(ids))
    assert all(item["reason"] in item["card"]["score"]["why"] for item in block["items"])
    assert not result["cost"]["llm_calls"]
    if first=="Платформа nanoCAD":assert ids[:4]==[first,"КОМПАС-3D","Bricsys BricsCAD Pro","ZWCAD"]


def test_absent_alias_typo_and_suggest(feed):
    result=search(feed,"альтернатива TeamVeiwer")
    assert analogs(result)["items"][0]["card"]["card_id"]=="AnyDesk"
    for spelling in ["Тимвьюер","TeamViwer","timvyuer"]:
        groups=suggest(feed[0],spelling)["groups"]
        assert groups[0]["title"]=="Аналоги в каталоге"
        assert [item["card_id"] for item in groups[0]["items"]]==["AnyDesk","RuDesktop","АССИСТЕНТ"]
    assert not any(g["type"]=="analogs" for g in suggest(feed[0],"Windows")["groups"])


@pytest.mark.parametrize("q",["российский аналог Windows","отечественная замена Виндовс","чем заменить Windows в России"])
def test_origin_is_filter_inside_os_class(feed,q):
    result=search(feed,q)
    assert result["understood"]["intent"]=="analog" and all(b["type"]!="not_in_catalog" for b in result["blocks"])
    block=analogs(result)
    ids=[item["card"]["card_id"] for item in block["items"]]
    assert ids[:2]==["Astra Linux","РЕД ОС"] and set(ids)=={"Astra Linux","РЕД ОС","ОС Рябина","ОС Медведь"}


def test_sold_product_uses_its_own_class_and_purpose(feed):
    block=analogs(search(feed,"аналог WaveLoom"))
    assert [i["card"]["card_id"] for i in block["items"]]==["closest","other"]
    # Нехватка замен в узком классе не разрешает показывать товары из чужих разделов.
    assert block["category_id"]=="Музыкальные студии"


def test_unknown_smart_uses_model_knowledge_cache_and_threshold(feed):
    assert any(b["type"]=="clarify" for b in search(feed,"аналог EmberReed")["blocks"])
    result=search(feed,"аналог EmberReed","smart")
    assert analogs(result)["category_id"]=="Аудиоредакторы" and result["understood"]["intent_source"]=="jev"
    assert search(feed,"аналог EmberReed","smart")["cost"]["cached"]==1
    uncertain=search(feed,"аналог CloudReed","smart")
    options=next(b["options"] for b in uncertain["blocks"] if b["type"]=="clarify")
    assert len(options)==3 and feed[1].count("emberreed")==1
    examples=next(b for b in uncertain["blocks"] if b["type"]=="products")
    assert all(c["category"]["id"] in {o["apply"]["category"] for o in options} for c in examples["items"])


def test_kb_check_validates_live_titles_vendors_and_sections(snapshot,monkeypatch,capsys,tmp_path):
    from kuznitsa.cli import main
    root=copytree(snapshot.kb,tmp_path/"kb")
    path=root/"feed_analogs.yaml"
    path.write_text(path.read_text().replace("vendor: AMS Software","vendor: Wrong publisher")
                    .replace("[Аудиоредакторы]","[Несуществующий класс]")
                    .replace("title: ZWCAD","title: Отсутствующий продукт"))
    monkeypatch.setenv("KZ_KB_DIR",str(root))
    monkeypatch.setenv("KZ_DATA_DIR",str(snapshot.data))
    assert main(["kb-check"])==0
    report=json.loads(capsys.readouterr().out)
    assert report["counts"]["feed_analogs"]==6 and not report["errors"]
    assert all(any(word in warning for warning in report["warnings"]) for word in
               ["Несуществующий класс","Wrong publisher","Отсутствующий продукт"])
    assert len(load(snapshot.kb).rows["feed_analogs"]["luminar"]["analogs"])==2

def test_vendor_replacements_use_main_product_class(feed):
    block=analogs(search(feed,"аналог Fern"))
    assert block["category_id"]=="Антивирусы"
    assert [i["card"]["card_id"] for i in block["items"]]==["security"]


def test_registry_filter_requires_a_registered_offer(feed):
    result=feed[0].search(Request(q="аналог Windows",mode="fast",filters={"registry":True}))
    assert [i["card"]["card_id"] for i in analogs(result)["items"]]==["ОС Рябина"]


def test_no_foreign_fill_if_no_domestic_matches(feed):
    result=search(feed,"отечественный аналог WaveLoom")
    assert analogs(result)["items"]==[] and "не найдено" in result["understood"]["agent_note"]
