"""Учёт и ограничение закрытых классификаторов Jev. Один экземпляр на движок."""
import hashlib
import json
from math import isfinite
import sqlite3
from contextlib import closing
from threading import BoundedSemaphore, Lock
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor


def choice(instructions,criteria):
    return dict(type="choice",instructions=instructions,criteria=criteria)

def validate_answers(answers,questions):
    if not isinstance(answers,dict) or set(questions)!=set(answers):
        raise ValueError("questions")
    for k,q in questions.items():
        answer=answers[k]
        if answer["choice"] not in q["criteria"]:
            raise ValueError("choice")
        probs=answer["probabilities"]
        if not isinstance(probs,dict) or set(probs)-set(q["criteria"]) or answer["choice"] not in probs:
            raise ValueError("probabilities")
        answer["probabilities"]={k:float(v) for k,v in probs.items()}
        if any(not 0<=v<=1 for v in answer["probabilities"].values()):
            raise ValueError("probabilities")
    return answers


class Decisions:
    def __init__(self,client,path,clock,budget,concurrency=2,price_in=.042):
        self.client,self.path,self.clock,self.budget=client,path,clock,budget
        self.price_in=price_in
        self.limit=BoundedSemaphore(concurrency)
        self.lock=Lock()
        self.pool=ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix="jev")
        self.run_budget=None
        self.run_spent=0.
        self.failures=0
        self.until=0.
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS llm_calls(id INTEGER PRIMARY KEY,ts REAL,search_id TEXT,kind TEXT,model TEXT,
                    cached INTEGER,tokens_in INTEGER,tokens_out INTEGER,cost_usd REAL,ms REAL,ok INTEGER,source TEXT);
                CREATE INDEX IF NOT EXISTS llm_day ON llm_calls(ts);
                CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY,kind TEXT,schema_hash TEXT,response_json TEXT,
                    cost_usd REAL,created_at REAL,hits INTEGER DEFAULT 0);
            """)

    def request(self, sid, source, purpose, state, questions):
        model=self.client.model
        def digest(x):
            return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        key=digest([model,state,questions])
        start=perf_counter()
        meta=dict(sent=False,kind=purpose,model=model,cached=0,tokens_in=0,tokens_out=0,usd=0.,ms=0.,ok=False)
        answers={}
        def finish(db):
            meta["ms"]=round((perf_counter()-start)*1000,2)
            db.execute("INSERT INTO llm_calls(ts,search_id,kind,model,cached,tokens_in,tokens_out,cost_usd,ms,ok,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (self.clock(),sid,purpose,model,meta["cached"],meta["tokens_in"],meta["tokens_out"],meta["usd"],meta["ms"],meta["ok"],source))
        try:
            with self.limit, closing(sqlite3.connect(self.path,timeout=5)) as db, db:
                row=db.execute("SELECT response_json FROM llm_cache WHERE key=?",(key,)).fetchone()
                if row:
                    answers=validate_answers(json.loads(row[0]),questions)
                    db.execute("UPDATE llm_cache SET hits=hits+1 WHERE key=?",(key,))
                    meta.update(cached=1,ok=True)
                else:
                    midnight=int(self.clock()//86400)*86400
                    spent=db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls WHERE ts>=? AND source NOT IN ('eval','replay')",(midnight,)).fetchone()[0]
                    batch=source in {"eval","replay"} and self.run_budget is not None
                    if not self.client.enabled:
                        meta["note"]="Категоризатор выключен, сохранённого решения нет"
                    elif source in {"eval","replay"} and not batch:
                        meta["note"]="Для этого прогона не задан бюджет"
                    elif self.until>self.clock():
                        meta["note"]="Категоризатор временно недоступен"
                    elif (self.run_spent>=self.run_budget if batch else spent>=self.budget):
                        meta["note"]="Достигнут дневной бюджет"
                    else:
                        try:
                            meta["sent"]=True
                            data=self.client.complete(state,questions)
                            usage=data.get("usage",{})
                            meta.update(tokens_in=int(usage.get("input_tokens",0)),tokens_out=int(usage.get("output_tokens",0)))
                            meta["estimated"]=usage.get("cost") is None
                            meta["usd"]=(meta["tokens_in"]*self.price_in/1_000_000 if meta["estimated"] else float(usage["cost"]))
                            if not isfinite(meta["usd"]) or meta["usd"]<0:
                                meta["usd"]=0.
                                raise ValueError("cost")
                            if batch:
                                with self.lock:
                                    self.run_spent+=meta["usd"]
                            answers=validate_answers(data["answers"],questions)
                            meta["ok"]=True
                            db.execute("INSERT OR REPLACE INTO llm_cache(key,kind,schema_hash,response_json,cost_usd,created_at) VALUES(?,?,?,?,?,?)",
                                       (key,purpose,digest(questions),json.dumps(answers),meta["usd"],self.clock()))
                            with self.lock:
                                self.failures=0
                        except Exception:
                            answers={}
                            meta.update(ok=False,note="Не удалось получить решение модели")
                            with self.lock:
                                self.failures+=1
                                if self.failures>=5:
                                    self.until=self.clock()+60
                finish(db)
        except (sqlite3.Error,ValueError,TypeError,KeyError):
            answers={}
            meta.update(ok=False,note="Не удалось прочитать или сохранить решение модели")
        return answers,meta

    def rerank(self,sid,source,state,cards):
        batches=[cards[i:i+20] for i in range(0,len(cards),20)]
        def run(batch):
            content={str(i):c for i,c in enumerate(batch)}
            questions={i:choice(f"Подходит ли предложение {i} покупателю?",{"yes":"Подходит","part":"Подходит частично","no":"Не подходит"}) for i in content}
            answers,m=self.request(sid,source,"rerank",{**state,"предложения":content},questions)
            m["probabilities"]={batch[int(i)]["card_id"]:a["probabilities"] for i,a in answers.items()}
            return m
        return list(self.pool.map(run,batches))
