import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from kuznitsa import cli
from kuznitsa.controls import Controls
from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from
from kuznitsa.kb.loader import load
from kuznitsa.llm.jev import Jev
from kuznitsa.schema import Offer,Client,Request

MINI=Path(__file__).parent/"fixtures/m2b"


@pytest.fixture(scope="module")
def shop(cfg,tmp_path_factory):
    path=tmp_path_factory.mktemp("m2b")
    kb=load(MINI)
    with (path/"catalog.jsonl").open("w") as out:
        for fid,f in kb.rows["families"].items():
            if f.get("catalog") is False:
                continue
            for ed in f.get("editions",[{}]):
                for action in ("new","renewal","addon"):
                    metric="company" if fid=="it" else "core" if fid in ("pg","ws") else "user" if fid in ("iw","accounting") else "device"
                    ident="-".join([fid,ed.get("id","base"),action])
                    o=Offer(offer_id=ident,sku=ident,name=f["name"],family_id=fid,family_name=f["name"],
                            vendor_id=f["vendor"],vendor=kb.rows["vendors"][f["vendor"]]["name"],category_id=f["category"],
                            edition=ed.get("id"),version=next(iter(f.get("versions",[])),None),price=2200 if f["vendor"]=="k" else 1500,
                            available=ed.get("id")!="total",registry=True,certs=["fstec"],platforms=["astra","linux"],
                            attrs={"promo":"true"},lic=dict(action=action,metric=metric,term_months=12,
                                qty_min=100 if fid=="guard" else 1,qty_max=25 if fid=="small" else None))
                    print(o.model_dump_json(),file=out)
                    if fid in ("drweb","astra"):
                        edu=o.model_copy(update={"offer_id":ident+"edu","sku":ident+"edu","lic":o.lic.model_copy(update={"audience":"edu","qty_min":100 if fid=="astra" else 1})})
                        print(edu.model_dump_json(),file=out)
    with (path/"clients.jsonl").open("w") as out:
        for ident,segment,owned in [("smb_trade","smb",[dict(family_id="small",qty=15,offer_id="small-base-new",card_id="small",expires_in_days=20)]),
                ("gov_clinic","gov",[]),("accounting_firm","smb",[]),("design_bureau","mid",[dict(family_id="nanocad",edition="spds",expires_in_days=20,qty=80)])]:
            c=Client(client_id=ident,title="ООО «Торговый дом»",segment=segment,owned=owned,
                     preferences={"registry_required":True,"certs_required":["fstec"]} if segment=="gov" else {},fleet={"os":["astra"]})
            print(c.model_dump_json(),file=out)
    def answer(request):
        body=json.loads(request.content)
        answers={}
        for k,q in body["questions"].items():
            value="off_topic" if k=="intent" else "none" if "none" in q["criteria"] else "yes" if "yes" in q["criteria"] else next(iter(q["criteria"]))
            answers[k]=dict(choice=value,probabilities={value:.93})
        return httpx.Response(200,json={"answers":answers,"usage":{"cost":.00001}})
    e=Engine.open(replace(cfg,data=path,kb=MINI,cache=path/"cache"),llm=Jev(transport=httpx.MockTransport(answer)))
    yield e
    e.close()


@pytest.fixture(params=["fast","smart"])
def find(shop,request):
    def search(q,profile="guest"):
        return shop.search(Request(q=q,mode=request.param,profile_id=profile))
    return search


def test_demo_layout_role_and_profiles(find):
    r=find("yfyjr","design_bureau")
    assert r["query"]["corrections"] and cards_from(r["blocks"])[0]["card_id"]=="nanocad:base"
    for fragment,family in (("fcnh","astra"),("кас","kesb")):
        result=find(fragment)
        assert cards_from(result["blocks"])[0]["card_id"].split(":")[0]==family
    kit=next(b for b in find("комплект бухгалтера на 5 человек","accounting_firm")["blocks"] if b["type"]=="kit")
    assert kit["total"]==sum(s["card"]["calc"]["total"] for s in kit["slots"])
    assert all(s["card"]["calc"]["qty"]==5 for s in kit["slots"])
    smb=find("антивирус на 30 пк","smb_trade")
    cards=cards_from(smb["blocks"])
    assert len(cards)>=5 and cards[0]["offer"]["available"] and any(c.get("qty_out_of_range") for c in cards)
    assert any("25" in note for note in smb["notes"])
    assert smb["blocks"][0]["items"][0]["card_id"]=="small"
    gov=find("антивирус на 30 пк","gov_clinic")
    assert gov["understood"]["filters"]["certs"]==["fstec"] and len(cards_from(gov["blocks"]))>1
    assert gov["understood"]["filters"]["platform"]==["astra"]


def test_alternatives_and_ownership(find):
    r=find("autocad","design_bureau")
    assert r["understood"]["zero_reason"]=="vendor_left"
    assert [(c["card_id"],c["offer"]["action"]) for c in cards_from(r["blocks"])]==[("nanocad:base","new")]
    r=find("докупить 5 лицензий kaspersky","smb_trade")
    assert {"addon","new"}<={c["offer"]["action"] for c in cards_from(r["blocks"])}
    assert cards_from(find("сапр 10 лицензий")["blocks"])[0]["calc"]["qty"]==10
    for q in ["cursor","резервилка","ндв 4"]:
        assert find(q)["understood"]["zero_reason"] in ("unknown_term","not_in_catalog")
    for q in ["купить айфон","зимняя резина r16","доставка пиццы москва","купить спецодежду и каску"]:
        r=find(q)
        assert r["understood"]["intent"]=="off_topic" and not cards_from(r["blocks"])
    cheaper=cards_from(find("дешевле касперского")["blocks"])
    assert cheaper and all(c["vendor"]["id"]!="k" and c["offer"]["price"]<2600 for c in cheaper)


def test_spell_editions_metrics_and_vendor(find):
    for q,fid in [("касперски эндпоинт секюрити","kesb:standard"),("windows 11 pro","win11:pro"),
                  ("КриптоПро CSP 5.0","crypto"),("Windows Server 2022 Standard","ws:standard")]:
        r=find(q)
        assert cards_from(r["blocks"])[0]["card_id"]==fid
        if fid=="win11:pro":
            assert any(b["type"]=="analogs" for b in r["blocks"])
    for q in ["postgres pro enterprise на 16 ядер","windows server 16 ядер"]:
        r=find(q)
        assert r["understood"]["intent"]=="product" and cards_from(r["blocks"])[0]["calc"]["qty"]==16
    for q in ["криптопро","юзергейт","astra linux 1000 рабочих мест","infowatch dlp 1500 пользователей"]:
        r=find(q)
        assert r["understood"]["intent"]=="product" and cards_from(r["blocks"])
    assert "server" not in cards_from(find("антивирус для школы 120 компьютеров")["blocks"])[0]["card_id"]


def test_blocks_and_next_steps(find):
    for q,count in [("чем отличается kesb стандартный от расширенного",2),("чем отличается астра орел воронеж смоленск",3)]:
        r=find(q)
        assert r["understood"]["intent"]=="compare" and len(r["blocks"][0]["columns"])==count
    assert find("чем отличается oem от box и esd")["blocks"][0]["source"]=="faq:packaging"
    for q,kind in [("акции","promo"),("внедрение 1с","services")]:
        blocks=find(q)["blocks"]
        assert any(b["type"]==kind for b in blocks) and not any(b["type"]=="products" for b in blocks)
    r=find("антивирус")
    assert r["related_queries"] and all(cards_from(find(q)["blocks"]) for q in r["related_queries"])
    assert all(c["score"]["tier_label"] for c in cards_from(r["blocks"]))
    assert r["profile"]["segment_title"] and len(r["profile"]["short"])<=24


def test_merch_alternatives(shop,monkeypatch):
    seen=[]
    class Rules(Controls):
        def merch(self,ctx,cards):
            seen.extend(c["card_id"] for c in cards)
            return super().merch(ctx,cards)
    monkeypatch.setattr(shop,"controls",Rules())
    shop.search(Request(q="autocad",mode="fast"))
    assert "nanocad:base" in seen


def test_loader_extensions(tmp_path):
    root=tmp_path/"kb"
    root.mkdir()
    (root/"vendors.yaml").write_text("- {id: v, name: Основное}")
    (root/"vendors_r3.yaml").write_text("- {id: v, name: Повтор}\n- {id: v2, name: Новый}")
    (tmp_path/"kb_auto.yaml").write_text("vendors: [{id: auto_v, name: Импорт}, {id: v, name: Повтор}]")
    kb=load(root,tmp_path)
    assert kb.rows["vendors"]["v"]["name"]=="Основное" and "v2" in kb.rows["vendors"]
    assert kb.auto["vendors"]==1 and len(kb.warnings)==2 and not kb.errors


def test_ingest_hook(monkeypatch):
    from types import SimpleNamespace
    import sys
    observed=[]
    monkeypatch.setitem(sys.modules,"kuznitsa.ingest.cli",SimpleNamespace(
        register=lambda sub:sub.add_parser("test-import"),run=lambda args,cfg:observed.append(args.cmd) or True))
    assert cli.main(["test-import"])==0 and observed==["test-import"]


def test_kind_of_negative_reference(find):
    for phrase in ("вместо касперского","не касперский","альтернатива касперскому","аналог касперского подешевле"):
        r=find(phrase)
        cards=cards_from(r["blocks"])
        assert cards and all(c["vendor"]["id"]!="k" for c in cards)


def test_layers_and_certainty(shop):
    from kuznitsa.understand.repair import repair
    expected={"кас":"каспер","1c ,e[ufknthbz":"1с бухгалтерия","дштгч":"linux","каспэрский эндпоинт":"касперский эндпоинт"}
    from kuznitsa.text import normalize
    for raw,first in expected.items():
        fixed,changes=repair(normalize(raw),shop.lex)
        assert " ".join(fixed).startswith(first) and changes


def test_reason_is_passed_to_journal(shop,monkeypatch):
    captured=[]
    monkeypatch.setattr(shop.journal,"search",lambda ts,req,r,n,reason,relaxed:captured.append((reason,r["understood"]["zero_reason"])))
    shop.search(Request(q="резервилка",mode="fast"))
    shop.search(Request(q="autocad",mode="fast"))
    assert captured==[("unknown_term","unknown_term"),("vendor_left","vendor_left")]


def test_smart_deadline_and_final_charge(tmp_path):
    from threading import Event
    from time import perf_counter,time
    import sqlite3
    from kuznitsa.llm.decisions import Decisions,choice
    started=Event()
    finish=Event()
    def slow(request):
        started.set()
        assert finish.wait(3)
        return httpx.Response(200,json={"answers":{"intent":{"choice":"broad","probabilities":{"broad":1.}}},
                                        "usage":{"cost":.001}})
    llm=Jev(transport=httpx.MockTransport(slow))
    service=Decisions(llm,tmp_path/"calls.sqlite",time,1)
    before=perf_counter()
    try:
        _,meta=service.decide_before(before+.1,"sid","ui","intent",{"запрос":"по"},{"intent":choice("Цель",{"broad":"Уточнить"})})
        assert started.is_set() and meta["pending"] and not meta["ok"] and perf_counter()-before<.6
    finally:
        finish.set()
        service.pool.shutdown()
        llm.close()
    with sqlite3.connect(service.path) as db:
        assert db.execute("select cost_usd from llm_calls where search_id='sid'").fetchone()==(.001,)


def test_education_empty_fast_path_asks_model(shop):
    r=shop.search(Request(q="астра линукс для школы 40 мест",mode="smart"))
    cards=cards_from(r["blocks"])
    assert cards and all(c["card_id"].startswith("astra:") for c in cards)
    assert all(c["offer"]["audience"]=="edu" and c.get("qty_out_of_range") for c in cards)
    assert r["relax_hints"] and any(c["score"]["why"] for c in cards)
    intent=next(t for t in r["trace"] if t["step"]=="intent")
    assert any("recovery" in m["probabilities"] for m in intent["detail"]["calls"])


def test_saved_cost_and_unpriced_cache(shop):
    request=Request(q="Что такое oem от box и esd?",mode="smart")
    shop.search(request)
    second=shop.search(request)
    assert second["cost"]["cached"] and second["cost"]["usd"]==0
    assert second["cost"]["saved_rub"]==pytest.approx(.00001*shop.usd_rub*second["cost"]["cached"])
    assert all(m["rub"]==0 and m["saved_rub"]>0 for step in second["trace"] for m in step["detail"].get("calls",[]))
    from kuznitsa.llm.recovery import cost_summary
    assert cost_summary([dict(sent=False,cached=1,tokens_in=0,usd=0.,saved_usd=None)],100)["saved_rub"] is None


def test_suggest_segment_corrections_queries_and_owned(shop):
    from kuznitsa.suggest.index import suggest
    def groups(q,p):
        return {g["type"]:g["items"] for g in suggest(shop,q,p)["groups"]}
    company=groups("касп","smb_trade")
    assert company["products"][0]["meta"] in ("kesb","small")
    assert any(i.get("hint") and i.get("q") for i in company["licenses"])
    assert "corrections" in groups("yfyjr","design_bureau")
    assert any("на 30" in i["text"] for i in groups("антив","guest")["queries"])


def test_semantic_chips_guest_and_mode_titles(shop):
    from fastapi.testclient import TestClient
    from kuznitsa.app import create_app
    with TestClient(create_app(engine=shop)) as client:
        meta=client.get("/api/meta").json()
        assert meta["mode_titles"]["naive"]=="Обычный поиск по словам"
        assert client.get("/api/profile/guest").json()["segment_title"]=="Гость"
        r=client.post("/api/search",json={"q":"комплект бухгалтера на 5 человек","mode":"fast"}).json()
        labels=[c["label"] for c in r["understood"]["chips"]]
        assert "Роль: бухгалтер" in labels and "5 рабочих мест" in labels
        assert all(c["score"]["parts"]["pers"]==0 for c in cards_from(r["blocks"]))
        simple=client.get("/api/search",params={"q":"кес","mode":"naive"}).json()
        assert simple["trace"][0]["title"]==meta["mode_titles"]["naive"]

def test_workplaces_respect_license_unit(shop):
    from kuznitsa.rank.variants import select_for_workplaces
    profile=shop.clients["guest"]
    def quantity(fid):
        cid=next(iter(shop.catalog.by["family"][fid]))
        return select_for_workplaces(shop.catalog.cards[cid],profile,{"action":"new"},{},{"value":5})[1]
    assert quantity("it")==1
    assert quantity("pg") is None
    result=shop.search(Request(q="комплект бухгалтера",mode="fast"))
    kit=next(b for b in result["blocks"] if b["type"]=="kit")
    assert kit["seats"] is None and kit["total"] is None


def test_smart_clarifies_class_with_matching_offers(shop,monkeypatch):
    from kuznitsa.llm.decisions import Decisions
    from kuznitsa import engine as module
    # Общее название ОС распознано как настольные ОС, но у них нет лицензий по ядрам.
    monkeypatch.setattr(module,"category_options",lambda *args:["desktop_os_ru","server_os"])
    def answer(request):
        questions=json.loads(request.content)["questions"]
        options={"intent":("category",{"category":1.0}),
                 "category":("desktop_os_ru",{"desktop_os_ru":.6,"server_os":.4}),
                 "recovery":("clarify",{"clarify":.8,"category_server_os":.2})}
        answers={}
        for k in questions:
            val,probs=options[k]
            assert probs.keys()<=questions[k]["criteria"].keys()
            answers[k]={"choice":val,"probabilities":probs}
        return httpx.Response(200,json={"answers":answers,"usage":{"cost":.00001}})
    client=Jev(model="test-os",transport=httpx.MockTransport(answer))
    decisions=Decisions(client,shop.journal.path,shop.clock,1)
    monkeypatch.setattr(shop,"decisions",decisions)
    try:
        r=shop.search(Request(q="операционные системы на 8 ядер",mode="smart"))
        assert r["understood"]["filters"]["category"]==["server_os"] and r["understood"]["qty"]["value"]==8
        assert any(b["type"]=="clarify" and len(b["options"])==2 for b in r["blocks"])
        assert all(c["offer"]["metric"]=="core" for c in cards_from(r["blocks"]))
    finally:
        decisions.pool.shutdown()
        client.close()


def test_situation_kit(find):
    r=find("открытие филиала на 5 человек","smb_trade")
    assert r["understood"]["intent"]=="role_kit"
    assert "Комплект: новый филиал" in [chip["label"] for chip in r["understood"]["chips"]]
    assert any(block["type"]=="kit" and block["seats"]==5 for block in r["blocks"])


def test_extension_defaults_references_and_counts(tmp_path):
    root=tmp_path/"kb"
    root.mkdir()
    (root/"families").mkdir()
    (root/"families"/"core.yaml").write_text("- {id: known, name: Товар}")
    (root/"faq_r3.yaml").write_text("- {id: q, questions: [Вопрос], answer: Ответ, related_families: [known, gone]}")
    (root/"compliance_r3.yaml").write_text("- {id: regulation, title: Правило, explain: Справка}")
    (root/"use_cases_r3.yaml").write_text("- {id: backup, title: Скопировать, phrases: [скопировать данные]}")
    (root/"roles_r3.yaml").write_text("- {id: kit_branch, title: Филиал, slots: [{families: [gone, known]}]}")
    (root/"slang_r3.yaml").write_text("- {term: нет, maps_to: {family: gone}}\n- {term: сбой, maps_to: {unrecognized: some}}")
    (tmp_path/"kb_auto.yaml").write_text("families: [{id: auto_other, name: Иная линейка}]")
    kb=load(root,tmp_path)
    assert kb.rows["faq"]["q"]["tags"]==[] and kb.rows["faq"]["q"]["related_families"]==["known"]
    assert kb.rows["roles"]["kit_branch"]["slots"][0]["families"]==["known"]
    assert kb.rows["compliance"]["regulation"]["effect"]=={} and kb.rows["use_cases"]["backup"]["products"]==[]
    assert kb.sources["families"]==dict(base=1,extensions=0,auto=1)
    assert kb.sources["slang"]["extensions"]==0 and not kb.rows["slang"]
    assert any("gone" in w for w in kb.warnings) and any("unrecognized" in w for w in kb.warnings)


def test_procurement_classification_explains_registry_selection(find):
    result=find("окпд2 58.29","gov_clinic")
    assert result["understood"]["intent"]=="compliance"
    assert result["understood"]["filters"]["registry"] and not result["understood"]["zero_reason"]
    assert [b["type"] for b in result["blocks"]]==["answer","products"]
    assert "классификации" in result["blocks"][0]["text"]


def test_imported_renewal_only_family_remains_searchable(cfg,tmp_path):
    auto={"vendors":[{"id":"auto_v","name":"AiXenix"}],"categories":[{"id":"auto_c","title":"Планирование"}],
          "families":[{"id":"auto_f","name":"Oriole Planner","vendor":"auto_v","category":"auto_c","catalog":True}]}
    import yaml
    (tmp_path/"kb_auto.yaml").write_text(yaml.safe_dump(auto,allow_unicode=True))
    o=Offer(offer_id="bundle",sku="AX-1",name="Oriole Planner Renewal License",family_id="auto_f",family_name="Oriole Planner",
            category_id="auto_c",vendor_id="auto_v",vendor="AiXenix",price=1200,lic={"action":"renewal","metric":"user"})
    (tmp_path/"catalog.jsonl").write_text(o.model_dump_json()+"\n")
    engine=Engine.open(replace(cfg,kb=MINI,data=tmp_path,cache=tmp_path/"cache"))
    try:
        r=engine.search(Request(q="Oriole Planner",mode="fast"))
        assert cards_from(r["blocks"])[0]["offer"]["sku"]=="AX-1"
        assert any("продление" in note and "подтвердить" in note for note in r["notes"])
    finally:
        engine.close()


@pytest.mark.parametrize("mode", ["fast","smart"])
def test_installed_line_upgrade_gov_and_academic_results(shop,monkeypatch,mode):
    gov=shop.clients["gov_clinic"].model_copy(update={"owned":[
        dict(family_id="kesb",edition="advanced",qty=150,product="Установленная защита Linux")]})
    edu=Client(client_id="college",title="Колледж",segment="edu",
               owned=[dict(family_id="drweb",edition="desktop",qty=150,product="Защита учебных классов")])
    monkeypatch.setitem(shop.clients,"gov_clinic",gov)
    monkeypatch.setitem(shop.clients,"college",edu)
    def first(profile):
        r=shop.search(Request(q="антивирус на 30 пк",profile_id=profile,mode=mode))
        return next(b["items"][0] for b in r["blocks"] if b["type"]=="products")
    smb,clinic,college=map(first,("smb_trade","gov_clinic","college"))
    assert smb["card_id"]=="kesb:standard" and any("переход" in s for s in smb["score"]["why"])
    assert clinic["card_id"]=="kesb:advanced" and any("Linux" in s for s in clinic["score"]["why"])
    assert college["card_id"]=="drweb:desktop" and college["offer"]["audience"]=="edu"
    assert any("учебных" in s for s in college["score"]["why"])
