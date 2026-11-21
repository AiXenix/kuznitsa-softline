from dataclasses import replace
from pathlib import Path
import shutil
import json
import pytest

from kuznitsa.engine import Engine
from kuznitsa.evaluation import cards_from, evaluate
from kuznitsa.kb.loader import load
from kuznitsa.mock.catalog_gen import offers_for,write_lines
from kuznitsa.schema import Request,Client


@pytest.fixture(scope="module")
def demo(cfg,tmp_path_factory):
    path=tmp_path_factory.mktemp("scenarios")
    kb_dir=path/"kb"
    shutil.copytree(cfg.kb,kb_dir)
    sample=Path(__file__).parent/"fixtures/m2"
    for file in sample.glob("*.yaml"):
        shutil.copy(file,kb_dir/("families/extra.yaml" if file.stem=="families" else file.name))
    with (kb_dir/"vendors.yaml").open("a") as out:
        out.write("- {id: lab, name: Kaspersky, aliases: [касперский]}\n- {id: microsoft, name: Microsoft}\n")
    cats=kb_dir/"categories.yaml"
    cats.write_text(cats.read_text().replace("title: Офисные пакеты","parent: office, title: Офисные пакеты")+
                    "- {id: office, title: Офис}\n- {id: os, title: Операционные системы}\n- {id: industrial, title: Промышленная безопасность}\n")
    kb=load(kb_dir)
    offers=[o for f in kb.rows["families"].values() if f.get("catalog",True)
            for o in offers_for(f,f.get("vendor"),3,120)]
    write_lines(path/"catalog.jsonl",(o.model_dump_json() for o in offers))
    c=Client(client_id="shop",segment="smb",title="Магазин",size_seats=18,
             owned=[dict(family_id="small",qty=10,expires_in_days=12)])
    write_lines(path/"clients.jsonl",[c.model_dump_json()])
    return Engine.open(replace(cfg,kb=kb_dir,cache=path/"cache",data=path))


def ask(demo,q,**kwargs):
    return demo.search(Request(q=q,mode="fast",**kwargs))


@pytest.mark.parametrize("query,intent,block",[
    ("чем заменить microsoft office","analog","analogs"),("софт для бухгалтера","role_kit","kit"),
    ("чем защитить почту от фишинга","task","products"),("мои лицензии","account","my_licenses"),
    ("РЕД ОС 100 рабочих мест\nщит 20 пк","spec_list","spec"),("как получить счет","question","answer"),
    ("ключ бесплатно","off_topic","answer"),("кряк","off_topic","answer"),
])
def test_regression_plans(demo,query,intent,block):
    r=ask(demo,query,profile_id="shop")
    assert r["understood"]["intent"]==intent
    b=next(b for b in r["blocks"] if b["type"]==block)
    if intent=="off_topic":
        assert r["understood"]["subtype"]=="piracy" and b["text"]
    if intent=="analog":
        assert any(c["card"]["card_id"]=="paper" for c in b["items"])
    if intent=="role_kit":
        assert b["slots"][0]["card"]["card_id"]=="paper" and b["seats"]==18
    if intent=="spec_list":
        assert [l["qty"] for l in b["lines"]]==[100,20]
        assert all(l["status"]=="matched" for l in b["lines"])


def test_office_leaf_and_quantity(demo):
    r=ask(demo,"офис для 20 сотрудников")
    assert r["understood"]["qty"]["value"]==20
    assert r["understood"]["filters"]["category"]==["office_suite"]
    r=ask(demo,"ред ос 100 рабочих мест")
    assert r["understood"]["qty"]==dict(value=100,metric="device")
    assert cards_from(r["blocks"])[0]["calc"]["qty"]==100


def test_chips_and_renewal(demo):
    r=ask(demo,"касперский касперский продление",profile_id="shop")
    labels=[c["label"] for c in r["understood"]["chips"]]
    assert len(set(labels))==len(labels)
    first=cards_from(r["blocks"])[0]
    assert first["card_id"]=="small" and first["offer"]["action"]=="renewal"
    assert any("Количество" in s for s in first["score"]["why"])
    grown=ask(demo,"ксос продление 30 пк",profile_id="shop")
    first=cards_from(grown["blocks"])[0]
    assert first["card_id"]=="endpoint" and first["offer"]["action"]=="new" and grown["notes"]
    assert cards_from(ask(demo,"ред ос")["blocks"])[0]["calc"]["qty"] is None


def test_session_modifiers(demo):
    a=ask(demo,"щит на 20 пк",session_id="chain")
    b=ask(demo,"а на 50?",session_id="chain")
    assert b["understood"]["inherited"]["from_search_id"]==a["search_id"]
    assert cards_from(b["blocks"])[0]["calc"]["qty"]==50
    assert not ask(demo,"а на 50?",context="off",session_id="chain")["understood"]["inherited"]


def test_eval_data_gap(demo,tmp_path):
    path=tmp_path/"rows.jsonl"
    path.write_text(json.dumps(dict(id="old",q="Old Guard",scenario="analog",**{"assert":{"top1_any":["Old Guard"]}})))
    assert evaluate(demo,path,"fast",tmp_path)["totals"]=={"data_gap":1}


def test_crosssell_and_relax_hint(demo):
    result=ask(demo,"ред ос")
    related=next(b for b in result["blocks"] if b["type"]=="crosssell")
    assert all(x["card"]["category"]["id"]=="office_suite" and x["reason"] for x in related["items"])
    result=ask(demo,"щит",filters={"platform":["macos"]})
    hint=next(h for h in result["relax_hints"] if h["drop"]=="platform")
    assert hint["count"]==1
    reopened=ask(demo,"щит",filters={"platform":["macos"]},**hint["apply"])
    assert "platform" not in reopened["understood"]["filters"]


def test_other_line_is_new_purchase(demo):
    result=ask(demo,"кес продление 30 пк",profile_id="shop")
    assert cards_from(result["blocks"])[0]["offer"]["action"]=="new"
    assert any("переход" in text.lower() for text in result["notes"])


@pytest.mark.parametrize("probability,expected",[(.54,"question"),(.88,"question")])
def test_closed_smart_decision(demo,probability,expected,tmp_path):
    import httpx
    from kuznitsa.llm.jev import Jev
    from kuznitsa.llm.decisions import Decisions
    from kuznitsa.analytics.store import Journal
    requests=[]
    def transport(request):
        payload=json.loads(request.content)
        requests.append(payload)
        answers={}
        for k,q in payload["questions"].items():
            value="broad" if k=="intent" else next(iter(q["criteria"]))
            answers[k]=dict(choice=value,probabilities={value:probability})
        return httpx.Response(200,json=dict(answers=answers,usage={"cost":.0002,"input_tokens":15,"output_tokens":8}))
    client=Jev(transport=httpx.MockTransport(transport))
    path=tmp_path/"jev.sqlite"
    engine=Engine(demo.catalog,demo.kb,demo.clients,Journal(path),llm=client,
                  decisions=Decisions(client,path,demo.clock,1))
    request=Request(q="как получить счет",mode="smart")
    result=engine.search(request)
    assert requests and "faq" in requests[0]["questions"] and 4<=len(requests[0]["questions"]["intent"]["criteria"])<=7
    assert result["understood"]["intent"]==expected
    assert result["cost"]["usd"]==pytest.approx(.0002*len(requests))
    cached=engine.search(request)
    assert cached["cost"]["llm_calls"]==0 and cached["cost"]["cached"]==len(requests)
    engine.decisions.pool.shutdown()
    client.close()
