"""Run from repository root after build-mock. No catalog descriptions are copied."""
import csv
import json
import random
from pathlib import Path
from xml.etree import ElementTree as ET
from openpyxl import Workbook

ROOT=Path(__file__).parent
rng=random.Random(26)
families=["kaspersky_kesb","windows_server","astra_linux_se","myoffice_standard",
          "drweb_enterprise_security_suite","kaspersky_ksos","windows_11","onec_accounting"]
catalog=list(map(json.loads,Path("var/data/catalog.jsonl").read_text().splitlines()))
rows=[]
truth={}
for family in families:
    pool=[r for r in catalog if r["family_id"]==family and r.get("price") and r["lic"]["action"] in ("new","renewal")]
    chosen=rng.sample(pool,3)
    if family=="kaspersky_kesb":
        anchor=next(r for r in pool if r["edition"]=="standard" and r["lic"].get("qty_min")==25
                    and r["lic"]["action"]=="new" and r["lic"]["term_months"]==12 and r["lic"]["audience"]=="business")
        chosen=[anchor,*[r for r in chosen if r!=anchor][:2]]
    for r in chosen:
        title,*parts=r["name"].split(", ")
        rng.shuffle(parts)
        name=", ".join([title,*parts])
        rows.append({"Артикул":r["sku"],"Наименование товара":name,"Цена, руб.":r["price"],"Примечание":"учебная выгрузка"})
        truth[r["sku"]]=dict(family=r["family_id"],vendor=r["vendor_id"],edition=r.get("edition"),lic=r["lic"])
rows[1]["Цена, руб."]="по запросу"
rows[3]["Цена, руб."]=""
rows += [rows[0],{"Артикул":"ERR-0","Наименование товара":"","Цена, руб.":0}]
(ROOT/"expected.yaml").write_text(json.dumps(truth,ensure_ascii=False,indent=2)+"\n")
for ext,sep,enc in [("csv",";","cp1251"),("tsv","\t","utf-8-sig")]:
    with (ROOT/("price."+ext)).open("w",encoding=enc,newline="") as f:
        w=csv.DictWriter(f,list(rows[0]),delimiter=sep)
        w.writeheader()
        w.writerows(rows)
(ROOT/"price.json").write_text(json.dumps({"export":{"products":rows}},ensure_ascii=False,indent=2))
(ROOT/"price.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n{broken\n")
wb=Workbook()
for idx,subset in enumerate([rows[:10],rows[10:]]):
    ws=wb.active if idx==0 else wb.create_sheet()
    ws.title=f"Прайс {idx+1}"
    ws.append(["Прайс-лист поставщика"])
    ws.merge_cells("A1:D1")
    ws.append(list(rows[0]))
    for row in subset:
        ws.append([row.get(k) for k in rows[0]])
wb.save(ROOT/"price.xlsx")
root=ET.Element("yml_catalog")
shop=ET.SubElement(root,"shop")
categories=ET.SubElement(shop,"categories")
ET.SubElement(categories,"category",id="1").text="ПО"
ET.SubElement(categories,"category",id="2",parentId="1").text="Программы для организаций"
offers=ET.SubElement(shop,"offers")
for row in rows:
    offer=ET.SubElement(offers,"offer",id=row["Артикул"],available="true")
    for key,value in [("name",row["Наименование товара"]),("price",row["Цена, руб."]),("categoryId","2")]:
        ET.SubElement(offer,key).text=str(value)
    ET.SubElement(offer,"param",name="Язык").text="ru"
ET.ElementTree(root).write(ROOT/"price.yml",encoding="utf-8",xml_declaration=True)
with (ROOT/"unknown.csv").open("w") as f:
    f.write("brand;sku;name;category;price\n")
    for i in range(40):
        f.write(f"AiXenix;AX-{i};Oriole Planner, {i+1} User, 1Y Renewal License;Каталог > Орнитология;{1200+i}\n")
