from pathlib import Path
from kuznitsa.kb.loader import load
from kuznitsa.mock.pricing import price
from kuznitsa.rank.variants import calculation
from kuznitsa.rank.packs import bundle
from kuznitsa.schema import License,Offer


def test_optional_titles_and_whole_field_override(tmp_path):
    folder=tmp_path/"families"
    folder.mkdir()
    (folder/"a.yaml").write_text("""
- {id: a, name: Пример (Пример 2.0), editions: [{id: e, name: Пример Старшая}], certs: [fstec]}
- {id: b, name: Программа (Прежнее имя), editions: [{id: base, name: Программа Базовая}]}
""")
    (tmp_path/"overrides").mkdir()
    (tmp_path/"overrides/families.yaml").write_text("""
a: {title: Новое имя, editions: {e: Проф}, certs: [fsb], price_rub: {unit: user_year, typical: 4500}}
unknown: {title: Пропуск}
""")
    kb=load(tmp_path)
    a,b=kb.rows["families"].values()
    assert a["title"]=="Новое имя" and a["editions"][0]["title"]=="Проф" and a["certs"]==["fsb"]
    assert a["price_rub"]["typical"]==4500 and a["name"] in a["aliases"]
    assert b["title"]=="Программа" and b["editions"][0]["title"]=="Базовая"
    assert any("unknown" in msg for msg in kb.dangling)


def test_price_progressions():
    f=dict(editions=[{},{}],license={"bands":["1-9","10-99","100+"]},price_rub={"low":2000,"typical":3500,"high":6000})
    def value(ed=0,band=0,months=12,action="new",aud="business"):
        return price(f,ed,band,None,months,action,aud,3000)
    assert .8*2000<=value(band=2)<value(band=1)<value()<value(ed=1)<=1.2*6000
    assert value(months=24)==1.8*value() and value(months=36)==2.5*value()
    assert .6*value()<=value(action="renewal")<=.75*value()
    assert value(action="addon")==value() and value(aud="edu")<value(aud="gov")<value()
    f["price_rub"]["unit"]="pack_year"
    f["license"]={"packs":[5,10,20]}
    amounts=[price(f,0,0,k,12,"new","business",3000) for k in (5,10,20)]
    assert amounts[0]<amounts[1]<amounts[2] and amounts[0]/5>amounts[1]/10>amounts[2]/20


def test_combined_packages_and_core_baseline():
    def offer(size,amount):
        return Offer(name="Ядра",offer_id=str(size),lic=License(pack=size,metric="core"),price=amount)
    small,base=offer(2,1500),offer(16,10000)
    line=bundle([small,base],18,base_required=True)
    assert [(o.lic.pack,n) for o,n in line]==[(16,1),(2,1)]
    assert calculation(base,line)["total"]==11500
    assert bundle([small,base],1,True)==[(base,1)]
    single=calculation(offer(1,2000),None)
    assert single["total"] is None and single["qty"] is None and "пакет" not in single["text"]
