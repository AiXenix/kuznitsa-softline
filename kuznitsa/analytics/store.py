import json
import sqlite3
from contextlib import closing
from uuid import uuid4


class Journal:
    def __init__(self,path):
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS searches(search_id TEXT PRIMARY KEY,ts REAL,session_id TEXT,client_id TEXT,segment TEXT,
              source TEXT,engine TEXT,mode TEXT,q_raw TEXT,q_norm TEXT,q_corrected TEXT,intent TEXT,intent_conf REAL,category_ctx TEXT,
              entities_json TEXT,filters_json TEXT,n_cards INTEGER,zero INTEGER,relaxed INTEGER,fail_reason TEXT,
              top_cards_json TEXT,blocks_json TEXT,ms REAL,llm_calls INTEGER,llm_cost_usd REAL,cached INTEGER,trace_json TEXT);
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,ts REAL,search_id TEXT REFERENCES searches(search_id),
              session_id TEXT,client_id TEXT,type TEXT,card_id TEXT,offer_id TEXT,position INTEGER,qty INTEGER,value REAL,
              margin_value REAL,payload_json TEXT);
            """)

    def insert(self,table,row):
        with closing(sqlite3.connect(self.path,timeout=5)) as db,db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",list(row.values()))

    def event(self,ts,data):
        payload = data.pop("payload",{})
        self.insert("events",dict(event_id=uuid4().hex,ts=ts,**data,payload_json=json.dumps(payload,ensure_ascii=False)))

    def search(self,ts,req,r,count,reason,relaxed):
        u,q = r["understood"],r["query"]
        def dump(v):
            return json.dumps(v,ensure_ascii=False)
        ids = [i.get("card",i)["card_id"] for b in r["blocks"] if b["type"] in ("analogs","products") for i in b["items"]]
        self.insert("searches",dict(search_id=r["search_id"],ts=ts,session_id=req.session_id,client_id=req.profile_id,
                    segment=r["profile"]["segment"],source=req.source,engine="kuznitsa",mode=req.mode,q_raw=q["raw"],q_norm=q["normalized"],
                    q_corrected=q["corrected"],intent=u["intent"],intent_conf=u["intent_conf"],category_ctx=req.category,
                    entities_json=dump(u["entities"]),filters_json=dump(u["filters"]),n_cards=count,zero=int(not count),relaxed=int(relaxed),
                    fail_reason=reason,top_cards_json=dump(ids),blocks_json=dump([b["type"] for b in r["blocks"]]),ms=r["timing_ms"]["total"],
                    llm_calls=0,llm_cost_usd=0,cached=0,trace_json=dump(r["trace"])))
