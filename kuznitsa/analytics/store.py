import json
import sqlite3
from contextlib import closing, contextmanager
from threading import RLock, Thread
from uuid import uuid4
from pathlib import Path
import logging
import os
import zlib
from pydantic_core import to_json
from .failures import classify,CANONICAL


def dump(value):
    return to_json(value).decode()


def result_cards(response):
    cards=[]
    for block in response.get("blocks",[]):
        if block["type"] in ("products","analogs"):
            cards.extend(item.get("card",item) for item in block.get("items",[]))
        elif block["type"] in ("kit","spec"):
            entries=block.get("slots",[]) if block["type"]=="kit" else block.get("lines",[])
            cards.extend(entry["card"] for entry in entries if entry.get("card"))
    return cards


class Journal:
    def __init__(self,path):
        self.path = path
        self.lock = RLock()
        self.writes=0
        self.checkpoint=None
        self.db = db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        db.row_factory = sqlite3.Row
        with self.lock:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA cache_size=-98304;
            PRAGMA mmap_size=268435456;
            PRAGMA wal_autocheckpoint=0;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS searches(search_id TEXT PRIMARY KEY,ts REAL,session_id TEXT,client_id TEXT,segment TEXT,
              source TEXT,engine TEXT,mode TEXT,q_raw TEXT,q_norm TEXT,q_corrected TEXT,intent TEXT,intent_conf REAL,category_ctx TEXT,
              entities_json TEXT,filters_json TEXT,n_cards INTEGER,zero INTEGER,relaxed INTEGER,fail_reason TEXT,
              top_cards_json TEXT,blocks_json TEXT,ms REAL,llm_calls INTEGER,llm_cost_usd REAL,cached INTEGER,trace_json TEXT);
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,ts REAL,search_id TEXT REFERENCES searches(search_id),
              session_id TEXT,client_id TEXT,type TEXT,card_id TEXT,offer_id TEXT,position INTEGER,qty INTEGER,value REAL,
              margin_value REAL,payload_json TEXT);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, kind TEXT, conditions TEXT, action TEXT, enabled INTEGER);
            CREATE TABLE IF NOT EXISTS insights(id TEXT PRIMARY KEY, type TEXT, status TEXT, body TEXT, verification TEXT);
            CREATE TABLE IF NOT EXISTS replays(id TEXT PRIMARY KEY, mode TEXT, fingerprint TEXT, limit_n INTEGER, created REAL);
            CREATE TABLE IF NOT EXISTS replay_results(run_id TEXT, q TEXT, result TEXT, PRIMARY KEY(run_id,q));
            CREATE INDEX IF NOT EXISTS searches_source ON searches(source,q_raw);
            CREATE INDEX IF NOT EXISTS searches_query_ts ON searches(q_raw,ts DESC,search_id DESC);
            CREATE INDEX IF NOT EXISTS events_search ON events(search_id,type);
            CREATE INDEX IF NOT EXISTS searches_session ON searches(session_id,ts);
            """)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS analytics_reports(key TEXT PRIMARY KEY,body TEXT);
                CREATE TABLE IF NOT EXISTS analytics_revision(revision INTEGER);
                INSERT INTO analytics_revision SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM analytics_revision);
                CREATE TABLE IF NOT EXISTS analytics_import_ids(id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS analytics_observation(id TEXT PRIMARY KEY,orders INTEGER,revenue INTEGER,clicks INTEGER);
                CREATE VIEW IF NOT EXISTS active_history AS SELECT * FROM searches WHERE source='history'
                AND CASE (SELECT value FROM kv WHERE key='settings:history_source')
                    WHEN 'mock' THEN search_id GLOB 's_mock_*'
                    WHEN 'import' THEN search_id IN (SELECT id FROM analytics_import_ids)
                    ELSE 1 END;
                CREATE VIEW IF NOT EXISTS active_replay AS SELECT * FROM replays WHERE id=coalesce(
                    (SELECT value FROM kv WHERE key='settings:active_replay'),(SELECT id FROM replays ORDER BY created DESC LIMIT 1));
                CREATE INDEX IF NOT EXISTS searches_engine_mode ON searches(engine,mode,search_id,llm_calls);
                CREATE INDEX IF NOT EXISTS search_recent ON searches(ts DESC) WHERE source IN ('ui','api','gallery','compare');
            """)
            for table,condition in (("searches","NEW.source='history'"),("events","EXISTS(SELECT 1 FROM searches WHERE search_id=NEW.search_id AND source='history')")):
                for op in ("INSERT","DELETE","UPDATE"):
                    expr=condition.replace("NEW.","OLD.") if op=="DELETE" else condition
                    db.execute(f"""CREATE TRIGGER IF NOT EXISTS invalidate_{table}_{op} AFTER {op} ON {table} WHEN {expr}
                        BEGIN DELETE FROM analytics_reports; UPDATE analytics_revision SET revision=revision+1; END""")
            for op,ref in (("INSERT","NEW"),("UPDATE","OLD"),("DELETE","OLD")):
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS mock_build_{op} AFTER {op} ON searches
                    WHEN {ref}.search_id GLOB 's_mock_*' BEGIN DELETE FROM kv WHERE key='settings:mock_build'; END""")
            for old in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name GLOB 'invalidate_replays_*' OR name GLOB 'invalidate_replay_results_*')").fetchall():
                db.execute(f'DROP TRIGGER "{old[0]}"')
            db.execute("""CREATE TRIGGER IF NOT EXISTS replay_progress AFTER INSERT ON replay_results
                       BEGIN DELETE FROM analytics_reports WHERE key='summary:'||NEW.run_id; END""")
            columns = {r[1] for r in db.execute("PRAGMA table_info(searches)")}
            for name, kind in [("response_z","BLOB"),("prev_search_id","TEXT")]:
                if name not in columns:
                    db.execute(f"ALTER TABLE searches ADD COLUMN {name} {kind}")

    @contextmanager
    def transaction(self):
        with self.lock:
            nested=self.db.in_transaction
            self.db.execute("SAVEPOINT journal_write" if nested else "BEGIN IMMEDIATE")
            try:
                yield self.db
            except BaseException:
                self.db.execute("ROLLBACK TO journal_write" if nested else "ROLLBACK")
                if nested:
                    self.db.execute("RELEASE journal_write")
                raise
            else:
                self.db.execute("RELEASE journal_write" if nested else "COMMIT")

    def rows(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql,params)]

    def read_report(self,sql,params=()):
        """Долгий отчёт читает снимок WAL без захвата блокировки записи."""
        if str(self.path)==":memory:":
            return self.rows(sql,params)
        uri=Path(self.path).resolve().as_uri()+"?mode=ro"
        with closing(sqlite3.connect(uri,uri=True,timeout=30)) as reader:
            reader.row_factory=sqlite3.Row
            return [dict(r) for r in reader.execute(sql,params)]

    def _schedule_checkpoint(self):
        # Не заставляем покупателя ждать fsync основного файла при пороге WAL.
        # Работает только пока есть страницы для переноса, не пишет события.
        self.writes+=1
        if self.writes%128 or self.db.in_transaction or str(self.path)==":memory:":
            return
        if self.checkpoint and self.checkpoint.is_alive():
            return
        try:
            if os.stat(str(self.path)+"-wal").st_size < 8*1024*1024:
                return
        except FileNotFoundError:
            return
        def flush():
            try:
                with closing(sqlite3.connect(self.path,timeout=1)) as maintenance:
                    maintenance.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            except sqlite3.Error:
                logging.getLogger(__name__).exception("Отложена контрольная точка журнала")
        self.checkpoint=Thread(target=flush,name="journal-checkpoint",daemon=True)
        self.checkpoint.start()

    def insert(self,table,row):
        with self.lock:
            self.db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",list(row.values()))
            self._schedule_checkpoint()

    def event(self,ts,data):
        data = data.copy()
        payload = data.pop("payload",{})
        data.setdefault("event_id", uuid4().hex)
        self.insert("events",dict(ts=ts,**data,payload_json=dump(payload)))

    def detail(self, ident):
        rows = self.rows("SELECT * FROM searches WHERE search_id=?", (ident,))
        if not rows:
            raise KeyError(ident)
        row = rows[0]
        blob = row.pop("response_z")
        if blob:
            response=json.loads(zlib.decompress(blob))
            understood=response.get("understood",{})
            if "zero_reason" not in understood:
                reason=classify(response,row["n_cards"],understood.get("reason")) if row["zero"] else None
                understood["zero_reason"]=CANONICAL.get(reason,reason)
            return response | {"ts":row["ts"],"n_cards":row["n_cards"]}
        return {**row, "trace":json.loads(row["trace_json"] or "[]"), "archived_summary":True}

    def search(self,ts,req,r,count,reason,relaxed):
        u,q = r["understood"],r["query"]
        cost = r.get("cost", {})
        cards=result_cards(r)
        ids = [c["card_id"] for c in cards]
        category=req.category or next(iter(u["filters"].get("category",[])),None)
        if not category and cards:
            category=(cards[0].get("category") or {}).get("id")
        count=max(count,len(ids))
        priority_ids = set()
        for step in r.get("trace", []):
            if step.get("step") == "business":
                for fired in step.get("detail", {}).get("priorities", []):
                    ident = fired.get("id") or fired.get("rule_id") if isinstance(fired, dict) else fired
                    if isinstance(ident, str):
                        priority_ids.add(ident)
        metadata = None
        if req.source in {"ui","api","widget"}:
            metadata = dump({"priority_ids": sorted(priority_ids),
                             "top_offers": [(c.get("offer") or {}).get("offer_id") for c in cards[:5]]})
        self.insert("searches",dict(search_id=r["search_id"],ts=ts,session_id=req.session_id,client_id=req.profile_id,
                    segment=r["profile"]["segment"],source=req.source,engine=r["engine"],mode=req.mode,q_raw=q["raw"],q_norm=q["normalized"],
                    q_corrected=q["corrected"],intent=u["intent"],intent_conf=u["intent_conf"],category_ctx=category,
                    entities_json=dump(u["entities"]),filters_json=dump(u["filters"]),n_cards=count,zero=int(not count),relaxed=int(relaxed),
                    fail_reason=classify(r,count,reason),top_cards_json=dump(ids),blocks_json=dump([b["type"] for b in r["blocks"]]),ms=r["timing_ms"]["total"],
                    llm_calls=cost.get("llm_calls",0),llm_cost_usd=cost.get("usd",0),cached=cost.get("cached",0),
                    prev_search_id=(u.get("inherited") or {}).get("from_search_id"),trace_json=metadata,
                    response_z=zlib.compress(to_json(r),1)))
