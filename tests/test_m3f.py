"""Раздел, семейство и издатель должны переживать естественные уточнения."""
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
    data=tmp_path_factory.mktemp("m3f")
    kb=copytree(cfg.kb,data/"kb")
    def write(relative,rows):
        (kb/relative).write_text(yaml.safe_dump(rows,allow_unicode=True))
    write("feed_tasks.yaml",[dict(id="copies",sections=["Резервное копирование"],aliases=["бэкап"],phrases=["сохранить копию"])])
    write("categories_scanners.yaml",[dict(id="audits",title="Сканеры уязвимостей")])
    write("use_cases_scanners.yaml",[dict(id="audit_test",phrases=["оценить защищенность сети"],categories=["audits"],
                                         products=["AuditStar"])])
    write("analogs.yaml",[dict(product="Microsoft Windows Server",aliases=["windows server"],family="server_os",
                               russian_analogs=[dict(family="smallguard",note="Тестовая замена")])])
    write("vendors_example.yaml",[dict(id="lab",name="Cyberprotect",name_ru="Киберпротект"),
                                  dict(id="guard",name="North Guard",name_ru="Северный Щит",aliases=["щит"])])
    write("slang_acronyms.yaml",[dict(term="аналитика сети",type="translit",maps_to={"vendor":"guard"},
                                      note="North Network Analytics (NNA)")])
    families=[("smallguard","North Small Office Security","nsos"),("center","North Security Center","nsc"),
              ("end","North Endpoint Security","nes"),("crypto","North CSP","csp"),
              ("server_os","Microsoft Windows Server","windows server")]
    write("families/m3f.yaml",[dict(id=fid,name=name,aliases=[alias],vendor="guard",category="office_suite",
                                    popularity=4) for fid,name,alias in families])
    rows=[]
    def product(cid,title,section,vendor,unit="device",family=None,domain="software"):
        for upper in (8,500):
            rows.append(dict(group_id=cid,offer_id=f"{cid}-{upper}",family_id=family or cid,
                             family_name=title,name=title,domain=domain,category_id=section,
                             class_id=section,category_path=["Программы",section],vendor=vendor,price=100,
                             lic=dict(metric=unit,qty_min=1 if upper==8 else 9,qty_max=upper)))
    for title,section,metric in [("Копия","Резервное копирование","device"),("Цикл","Системы автоматизации","user"),
                                 ("Сжатие","Архиваторы","device"),("Монтаж","Видеоредакторы","device"),
                                 ("Сервер","Серверное ПО","device")]:
        product("x"+title,title+" Стандарт",section,"Киберпротект",metric)
        product("y"+title,title+" Проф",section,"НПО «Сигма»",metric)
    product("license","Базовые лицензии центра","Другое","Учёт")
    product("files","Общие Файлы","Другое","Учёт")
    product("firm","Учет Предприятие","Другое","Учёт")
    product("os","Операционная система Microsoft Windows Server 2022","Операционные системы","Microsoft",family="server_os")
    product("access","Windows Server CAL 2022","Операционные системы","Microsoft")
    product("addon","Модуль для Windows Server","Модули","ArtWare")
    product("meet","МТС Линк Встречи","Связь","Телеком")
    product("scanner","Поиск-ВС","Сканеры уязвимостей","НПО «Сигма»")
    product("other","Поиск-ВС Модуль","Другое","Другой")
    product("paper","Paper Lens","Сканеры","Оптика",domain="hardware")
    product("audit","AuditStar","Защита данных","Киберпротект")
    product("small","North Small Office Security","Антивирусы для организаций","Северный Щит",family="smallguard")
    product("endpoint","North Endpoint Security","Антивирусы для организаций","Северный Щит")
    product("console","North Security Center","Средства управления","Северный Щит",family="center")
    product("control","Falcon Security Center","Средства управления","Falcon")
    product("provider","North CSP","Криптография","Северный Щит",family="crypto")
    product("foreign","North Office Antivirus","Антивирусы для организаций","Иной издатель")
    (data/"catalog.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    engine=Engine.open(replace(cfg,kb=kb,data=data),llm=Disabled())
    try:
        yield lambda q:engine.search(Request(q=q,mode="fast",source="eval"))
    finally:
        engine.close()


@pytest.mark.parametrize("query,section,n,metric",[
    ("бэкап, лицензии на 7 узлов","Резервное копирование",7,"device"),
    ("лицензия на резервное копирование на 30 устройств","Резервное копирование",30,"device"),
    ("системы автоматизации предприятия на 220 пользователей","Системы автоматизации",220,"user"),
    ("серверное ПО, лицензия на 15 ПК","Серверное ПО",15,"device"),
    ("видеоредакторы на 18 рабочих мест","Видеоредакторы",18,None),
    ("архиваторы файлов на 32 компьютера","Архиваторы",32,"device"),
    ("автоматизация предприятия, 6 сотрудников","Системы автоматизации",6,"user"),
    ("лицензия на архиваторы, 12 устройств","Архиваторы",12,"device"),
])
def test_count_selects_tier_within_entire_section(feed,query,section,n,metric):
    result=feed(query)
    block=result["blocks"][0]
    assert result["understood"]["intent"]=="category" and block["category_id"]==section
    assert result["understood"]["qty"]==dict(value=n,metric=metric)
    core=[c for c in block["items"] if not c.get("kind") and not c.get("fill")]
    assert block["total"]==len(core)==2
    assert all(c["calc"]["qty"]==n and c["offer"]["qty_min"]<=n<=c["offer"]["qty_max"] for c in core)


@pytest.mark.parametrize("query",["лицензия Windows Server","лицензия на Windows Server 2022","Windows Server лицензия"])
def test_license_keeps_named_os(feed,query):
    assert feed(query)["blocks"][0]["items"][0]["card_id"]=="os"


def test_requested_access_license_is_still_first(feed):
    assert feed("лицензия Windows Server CAL")["blocks"][0]["items"][0]["card_id"]=="access"


def test_known_initials_without_a_sold_family(feed):
    r=feed("сканер NNA")
    assert r["understood"]["zero_reason"]=="not_in_catalog"
    assert "North Network Analytics" in r["blocks"][0]["text"]
    assert r["blocks"][1]["type"]=="products"
    assert r["blocks"][1]["items"][0]["vendor"]["name"]=="Северный Щит"


@pytest.mark.parametrize("query,cid",[("вебинары MTS Линк","meet"),("МТС link","meet"),("North смол офис","small")])
def test_mixed_script_family(feed,query,cid):
    assert feed(query)["blocks"][0]["items"][0]["card_id"]==cid


@pytest.mark.parametrize("query,owner",[("Cyberprotect решения для бэкапа","Киберпротект"),
                                      ("антивирус от Северного Щита для офиса","Северный Щит")])
def test_alias_keeps_actual_publisher(feed,query,owner):
    result=feed(query)
    assert result["understood"]["filters"]["vendor"]
    core=[c for c in result["blocks"][0]["items"] if not c.get("kind") and not c.get("fill")]
    assert core and all(c["vendor"]["name"]==owner for c in core)


def test_find_product_from_vendor(feed):
    r=feed("купить Поиск ВС от НПО Сигма")
    assert r["blocks"][0]["items"][0]["card_id"]=="scanner" and r["understood"]["filters"]["vendor"]


def test_software_publisher_disambiguates_scanner(feed):
    r=feed("Cyberprotect сканер")
    assert r["blocks"][0]["items"][0]["card_id"]=="audit"
    assert r["blocks"][0]["category_id"]=="Защита данных"


def test_cyrillic_name_of_feed_only_publisher(feed):
    assert feed("средства управления от Фалкона")["blocks"][0]["items"][0]["card_id"]=="control"


@pytest.mark.parametrize("query,cid",[("North лицензия для защиты офиса NSOS","small"),
                                     ("North управление защитой NSC","console"),
                                     ("защита рабочего места NES","endpoint"),("North шифрование CSP","provider"),
                                     ("Falcon для управления защитой FSC","control"),("сканер защиты (NSOS)","small")])
def test_family_initials_beat_descriptive_words(feed,query,cid):
    assert feed(query)["blocks"][0]["items"][0]["card_id"]==cid


@pytest.mark.parametrize("query",["архиваторы документов","архиваторы чертежей"])
def test_class_with_generic_object(feed,query):
    r=feed(query)
    assert r["blocks"][0]["category_id"]=="Архиваторы" and r["blocks"][0]["total"]==2
