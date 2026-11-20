from pathlib import Path
import pytest
from kuznitsa.config import Config
from kuznitsa.kb.loader import load
from kuznitsa.mock.catalog_gen import offers_for,write_lines
from kuznitsa.schema import Client
from kuznitsa.engine import Engine

MINI=Path(__file__).parent/"fixtures/kb_mini"


@pytest.fixture(scope="session")
def cfg(tmp_path_factory):
    path=tmp_path_factory.mktemp("catalog")
    cfg=Config(data=path,kb=MINI,cache=path/"cache",embed="off")
    kb=load(MINI)
    offers=[o for f in kb.rows["families"].values() if f.get("catalog",True)
            for o in offers_for(f,kb.rows["vendors"][f["vendor"]]["name"],17,1000)]
    write_lines(path/"catalog.jsonl",(o.model_dump_json() for o in offers))
    clients=[Client(client_id=i,title=t,segment=s,demo=True,
                    owned=[dict(family_id="shield",qty=30,expires_in_days=21,edition="pro")] if s=="smb" and i!="guest" else [])
             for i,t,s in [("guest","Гость","smb"),("smb_trade","Магазин","smb"),("gov_clinic","Клиника","gov"),("edu_university","Вуз","edu")]]
    write_lines(path/"clients.jsonl",(c.model_dump_json() for c in clients))
    return cfg


@pytest.fixture(scope="session")
def engine(cfg):
    return Engine.open(cfg,clock=lambda:1700000000.)
