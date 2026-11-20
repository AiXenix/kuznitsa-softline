import json
import math
from time import time
from uuid import uuid4
from kuznitsa.controls import Controls,PhraseRules
from kuznitsa.text import normalize
from kuznitsa.rank.merch import apply,matches
from .store import dump


def validate(kind,conditions,action):
    if kind not in {"synonym","redirect","pin","boost","bury","ban","banner"}:
        raise ValueError("Неизвестный вид правила")
    if set(conditions)-{"phrase","pattern","category","intent","segment","start","end"}:
        raise ValueError("Неизвестное условие")
    for k,v in conditions.items():
        if k in ("start","end"):
            if type(v) not in (int,float) or not math.isfinite(v):
                raise ValueError("Срок задаётся в секундах Unix")
        elif not isinstance(v,str):
            raise ValueError("Условие должно быть строкой")
    if kind=="synonym":
        if (set(conditions)-{"start","end"} and action.get("kind","text")!="text") or action.get("kind","text") not in {"vendor","family","category","use_case","text"}:
            raise ValueError("Контекстный синоним можно оформить как перенаправление")
        keys=["phrase","to"]
    elif kind=="redirect":
        keys=[k for k in ("q","category","intent") if k in action]
        if len(keys)!=1:
            raise ValueError("Укажите одну цель перенаправления")
    else:
        keys=["text" if kind=="banner" else "card_id"]
    if any(not isinstance(action.get(k),str) or not action[k].strip() for k in keys):
        raise ValueError("Заполните действие")
    if "position" in action and (type(action["position"])!=int or action["position"]<1):
        raise ValueError("Позиция начинается с единицы")
    if "factor" in action and (type(action["factor"]) not in (float,int) or not math.isfinite(action["factor"]) or action["factor"]<=0):
        raise ValueError("Множитель должен быть положительным")


class RuleControls(Controls):
    def __init__(self,journal):
        self.journal=journal

    def rules(self):
        return [{**r,"conditions":json.loads(r["conditions"]),"action":json.loads(r["action"]),"enabled":bool(r["enabled"])}
                for r in self.journal.rows("SELECT * FROM rules ORDER BY rowid")]

    def active(self):
        now=time()
        return [r for r in self.rules() if r["enabled"] and r["conditions"].get("start",0)<=now<r["conditions"].get("end",float("inf"))]

    def bump(self,db):
        db.execute("""INSERT INTO kv VALUES ('rules:version','1',?) ON CONFLICT(key) DO UPDATE SET
                      value=CAST(value AS INTEGER)+1,updated=excluded.updated""",(time(),))

    def version(self):
        rows=self.journal.rows("SELECT value FROM kv WHERE key='rules:version'")
        revision=int(rows[0]["value"]) if rows else 0
        boundaries=sum(r["conditions"][key]<=time() for r in self.rules() for key in ("start","end") if key in r["conditions"])
        return revision*1000000+boundaries

    def save(self,kind,conditions,action,enabled=True,ident=None):
        validate(kind,conditions,action)
        with self.journal.transaction() as db:
            if ident and not db.execute("SELECT 1 FROM rules WHERE id=?",(ident,)).fetchone():
                raise KeyError(ident)
            ident=ident or uuid4().hex
            db.execute("INSERT OR REPLACE INTO rules VALUES (?,?,?,?,?)",(ident,kind,dump(conditions),dump(action),int(enabled)))
            self.bump(db)
        return ident

    def remove(self,ident):
        with self.journal.transaction() as db:
            if not db.execute("DELETE FROM rules WHERE id=?",(ident,)).rowcount:
                raise KeyError(ident)
            self.bump(db)

    def synonyms(self):
        return [dict(kind="text")|r["action"]|dict(rule_id=r["id"]) for r in self.active() if r["kind"]=="synonym" and not set(r["conditions"])-{"start","end"}]

    def redirect(self,ctx):
        for r in reversed(self.active()):
            if not matches(r["conditions"],ctx):
                continue
            if r["kind"]=="redirect":
                return r["action"]|dict(rule_id=r["id"])
            if r["kind"]=="synonym" and set(r["conditions"])-{"start","end"}:
                rewritten,fired=PhraseRules([r["action"]]).apply(normalize(ctx["q_raw"]))
                if fired:
                    return dict(q=rewritten,rule_id=r["id"])
        return None

    def merch(self,ctx,cards):
        return apply(self.active(),ctx,cards)

    def weights(self):
        rows=self.journal.rows("SELECT value FROM kv WHERE key='settings:weights'")
        return json.loads(rows[0]["value"]) if rows else None

    def set_weights(self,weights):
        from kuznitsa.config import WEIGHTS
        if set(weights)!=set(WEIGHTS) or not all(type(v) in (float,int) and 0<=v<=1 for v in weights.values()) or abs(sum(weights.values())-1)>.0001:
            raise ValueError("Укажите четыре неотрицательных веса с суммой 1")
        with self.journal.transaction() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES ('settings:weights',?,?)",(dump(weights),time()))
            self.bump(db)
