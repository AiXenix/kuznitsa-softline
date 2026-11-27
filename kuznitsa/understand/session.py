import json
import sqlite3
from threading import Lock
import re


class Sessions:
    def __init__(self,path,clock):
        self.clock=clock
        self.lock=Lock()
        self.db=sqlite3.connect(path,check_same_thread=False,timeout=5)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT,updated REAL)")

    def close(self):
        with self.lock:
            self.db.close()

    def key(self,req):
        return "session:"+json.dumps([req.profile_id,req.session_id],ensure_ascii=False)

    def previous(self,req):
        if not req.session_id or req.context=="off" or "context" in req.ignore:
            return None
        with self.lock:
            r=self.db.execute("SELECT value FROM kv WHERE key=? AND updated>=?",(self.key(req),self.clock()-900)).fetchone()
        return json.loads(r[0]) if r else None

    def save(self,req,r,cards,extra=None):
        if not req.session_id:
            return
        u=r["understood"]
        data=dict(id=r["search_id"],q=req.q,filters=u["filters"],exclude=u["exclude"],qty=u["qty"],intent=u["intent"],
                  first_vendor=cards[0]["vendor"]["id"] if cards else None,
                  first_family=cards[0]["card_id"].split(":")[0] if cards else None)
        if extra is not None:
            data["feed"]=extra
        with self.lock,self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)",(self.key(req),json.dumps(data,ensure_ascii=False),self.clock()))


def inherit(previous,text,f,exc,qty):
    if not previous:
        return qty,None
    platform_pivot=re.match(r"^(?:а )?(?:под|для) (астр\w*|линукс|linux|макос|windows)",text)
    if platform_pivot:
        for key in ("family","category","vendor"):
            f.pop(key,None)
        f["platform"]=["astra" if platform_pivot[1].startswith("астр") else {"линукс":"linux","макос":"macos"}.get(platform_pivot[1],platform_pivot[1])]
    if re.search(r"\bк (ней|нему|этому)\b",text) and previous.get("first_family"):
        return qty or previous["qty"],dict(from_search_id=previous["id"],from_q=previous["q"],fields=["совместимость"])
    if f.get("family") or f.get("category") or f.get("vendor"):
        return qty,None
    number=re.match(r"^(?:а )?на (\d+)\s*\??$",text)
    if not (f or qty or number or re.search("дешев|вместо|альтернатив|другой вендор",text)):
        return qty,None
    before=set(f)
    for k,v in previous["filters"].items():
        f.setdefault(k,v)
    for k,v in previous["exclude"].items():
        exc.setdefault(k,v)
    if number:
        qty=dict(value=int(number[1]),metric=(previous["qty"] or {}).get("metric"))
    if re.search("вместо|другой (?:производитель|вендор)",text) and previous.get("first_vendor"):
        exc.setdefault("vendor",[]).append(previous["first_vendor"])
    if "вместо" in text and previous.get("first_family"):
        f["family"]=[previous["first_family"]]
    return qty or previous["qty"],dict(from_search_id=previous["id"],from_q=previous["q"],fields=sorted(set(f)-before))
