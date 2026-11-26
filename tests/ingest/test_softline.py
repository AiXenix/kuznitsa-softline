import json
from pathlib import Path

from kuznitsa.config import Config
from kuznitsa.ingest.catalog import import_catalog
from kuznitsa.ingest.day import identify
from kuznitsa.schema import Offer


def test_grouped_store_feed(tmp_path):
    path=tmp_path/"feed.xml"
    path.write_text("""<yml_catalog><shop><name>store.softline.ru</name><categories>
      <category id="86562">Серверы и опции</category>
      <category id="c" parentId="86562">Серверы</category>
      <category id="g" parentId="c">O&amp;amp;O</category></categories><offers>
      <offer id="one" group_id="g" available="false"><name>O&amp;amp;O Rack, лицензия на год</name>
      <categoryId>c</categoryId><vendorCode>R-01</vendorCode><vendor>O&amp;amp;O</vendor>
      <url>https://example.org/one</url><vendorUrl>https://example.org/o</vendorUrl>
      <sales_notes>Доставка отдельно</sales_notes><picture>https://example.org/i</picture>
      <price>100</price><oldprice>120</oldprice>
      <param name="К-во узлов">25</param><param name="К-во узлов">49</param>
      <param name="Совместимая архитектура/платформа">Linux</param>
      <param name="Тип организации">Академическая</param><param name="Срок действия">12 мес.</param>
      <param name="Разъём">AM5</param><param name="Тип поставки">электронная</param>
      <param name="Назначение">расчёты</param>
      <param name="Номер записи в реестре отечественного ПО">123</param></offer>
      <offer id="two"><group_id>g</group_id><name>O&amp;amp;O Rack, продление</name>
      <categoryId>g</categoryId><price>0</price><oldprice>100</oldprice>
      <param name="К-во пользователей до">100</param></offer>
      <offer id="g"><categoryId>c</categoryId><name>Кабель</name><price>20</price><oldprice>20</oldprice>
      </offer></offers></shop></yml_catalog>""")
    cfg=Config(data=tmp_path/"data",kb=Path("kb"),cache=tmp_path/"cache",embed="off")
    assert identify(path)[0]=="catalog"
    report=import_catalog([path],cfg.data,cfg.kb,ai="off",config=cfg)
    assert report["feed"]["cards"]==2
    rows=[Offer.model_validate_json(s) for s in (cfg.data/"catalog.jsonl").read_text().splitlines()]
    a,b,c=rows
    assert a.card_id==b.card_id=="g" and c.card_id=="sku_g"
    assert a.family_name==b.family_name=="O&O Rack"
    assert a.category_path==b.category_path==["Серверы и опции","Серверы","O&O"]
    assert c.category_path==["Серверы и опции","Серверы"]
    assert a.attrs["domain"]=="hardware" and a.attrs["line_id"]=="g"
    assert a.attrs["Разъём"]=="AM5" and a.attrs["edition"]=="Академическая"
    assert (a.lic.metric,a.lic.qty_min,a.lic.qty_max)==("device",25,49)
    assert (b.lic.metric,b.lic.qty_max)==("user",100)
    assert (a.lic.audience,a.lic.term_months,a.delivery,a.platforms)==("edu",12,"esd",["Linux"])
    assert a.attrs["task"]=="расчёты" and a.attrs["registry_no"]=="123"
    assert a.registry and b.registry is None
    assert a.source_ids==["one","R-01"] and a.image.endswith("/i") and a.url.endswith("/one")
    assert a.attrs["vendorUrl"].endswith("/o") and a.attrs["sales_notes"]=="Доставка отдельно"
    assert [a.attrs["group_id"],b.attrs["group_id"],c.attrs["group_id"]]==["g","g",""]
    assert a.attrs["feed_category_path_ids"]==["86562","c","g"]
    assert a.attrs["feed_category_id"]=="c" and b.attrs["feed_category_id"]=="g"
    assert a.attrs["feed_offer_id"]=="one" and a.category_id=="auto_sl_c"
    native=[json.loads(s) for s in (cfg.data/"catalog.jsonl").read_text().splitlines()]
    assert native[0]["picture"]==a.image and native[0]["vendorUrl"]==a.attrs["vendorUrl"]
    assert native[1]["price"]==0 and native[1]["oldprice"]==100
    assert a.price==100 and a.promo and not a.available
    assert b.price_on_request and not b.promo and not c.promo
    assert json.loads((cfg.data/"feed_categories.json").read_text())["g"]==["O&O","c"]

    kb=tmp_path/"kb"
    kb.mkdir()
    (kb/"categories.yaml").write_text("- id: rack_servers\n  title: Серверы\n")
    mapped=import_catalog([path],cfg.data,kb,ai="embed",config=cfg)
    assert mapped["ai"]["selected"]=={"classes":1,"offers":3}
    linked=json.loads((cfg.data/"catalog.jsonl").read_text().splitlines()[0])
    assert linked["category_id"]==linked["attrs"]["kb_category"]=="rack_servers"
    assert linked["attrs"]["feed_category_id"]=="c" and linked["attrs"]["group_id"]=="g"


def test_card_title_keeps_product_identity():
    from kuznitsa.ingest.softline_feed import card_title
    assert card_title("Лаборатория","Редактор 4","Лаборатория","","software")=="Редактор 4"
    assert card_title("Редактор DOC-24: подписка на год","Редактор","Вендор","DOC-24","software")=="Редактор"
    assert card_title("Сканер C-42","Сканеры","Вендор","C-42","hardware")=="Сканер C-42"
