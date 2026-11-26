"""Правила допродаж для выдачи и редактора магазина."""
from functools import lru_cache
import hashlib
import logging
import re
from urllib.parse import urlsplit

import yaml
from kuznitsa.text import normalize


def validate(body):
    allowed = {"id","when","offer","reason","weight","source","enabled"}
    if not isinstance(body,dict) or body.keys()-allowed:
        raise ValueError("Неизвестное поле правила")
    rule = dict(enabled=True,source="kb",weight=1.) | body
    for key in ("id","reason","source"):
        if not isinstance(rule.get(key),str) or not rule[key].strip():
            raise ValueError("Заполните поле "+key)
    if len(rule["id"])>160 or "/" in rule["id"]:
        raise ValueError("Недопустимый идентификатор")
    if type(rule["weight"]) not in (int,float) or not 0<=rule["weight"]<=1 or type(rule["enabled"]) is not bool:
        raise ValueError("Укажите вес от 0 до 1 и логический признак включения")
    if rule["source"]!="kb":
        source=urlsplit(rule["source"].removeprefix("vendor_site:"))
        if not rule["source"].startswith("vendor_site:") or source.scheme not in ("https","http") or not source.hostname:
            raise ValueError("Источник должен быть kb или vendor_site с адресом сайта")
    for key in ("when","offer"):
        group=rule.get(key)
        fields={"classes","families","vendors","audience"}
        if key=="when":
            fields.add("query_words")
        else:
            fields.update(("strict","exclude_words"))
        if not isinstance(group,dict) or group.keys()-fields:
            raise ValueError("Проверьте условия "+key)
        clean={}
        for k,values in group.items():
            if k=="audience":
                audiences=values if isinstance(values,list) else [values]
                if not audiences or any(v not in ("home","business") for v in audiences):
                    raise ValueError("Укажите аудиторию home или business")
                clean[k]=values
                continue
            if k=="strict":
                if type(values) is not bool:
                    raise ValueError("Признак строгого подбора должен быть логическим")
                clean[k]=values
                continue
            if k=="exclude_words" and (not isinstance(values,list) or any(not isinstance(v,str) for v in values)):
                raise ValueError("Слова-исключения должны быть строками")
            if not isinstance(values,list) or any(type(v) not in (str,int) or not str(v).strip() for v in values):
                raise ValueError("Ожидается список идентификаторов в "+k)
            clean[k]=list(dict.fromkeys(str(v).strip() for v in values))
        if clean.get("strict") and not (clean.get("families") or clean.get("vendors")):
            raise ValueError("Для строгого подбора укажите линейку или производителя")
        if not any(clean.get(k) for k in ("classes","vendors","families","query_words")):
            raise ValueError("Нужно хотя бы одно условие в "+key)
        rule[key]=clean
    return rule

@lru_cache(8)
def load_rules(path,mtime,size):
    """Прочитать одну редакцию файла, сохранив действующие правила и диагностику."""
    raw=path.read_bytes()
    stamp=int.from_bytes(hashlib.sha256(raw).digest()[:6],"big")
    rules={}
    warnings=[]
    try:
        rows=yaml.load(raw,Loader=yaml.CSafeLoader)
        if isinstance(rows,dict):
            rows=rows.get("rules")
        if not isinstance(rows,list):
            raise ValueError("ожидается список правил")
    except (ValueError,yaml.YAMLError,UnicodeError) as exc:
        rows=[]
        warnings.append(f"{path.name}: {exc}")
    for number,row in enumerate(rows,1):
        try:
            rule=validate(row)
            if rule["id"] in rules:
                raise ValueError("повтор идентификатора")
            rules[rule["id"]]=rule
        except ValueError as exc:
            ident=row.get("id","") if isinstance(row,dict) else ""
            warnings.append(f"{path.name} [{number}] {ident}: правило пропущено. {exc}")
    for message in warnings:
        logging.getLogger(__name__).warning("%s",message)
    return rules,stamp,warnings


@lru_cache(512)
def query_pattern(phrases):
    return re.compile(r"(?<!\w)(?:"+"|".join(re.escape(normalize(w)) for w in phrases)+r")(?!\w)")


def query_matches(phrases,q):
    return bool(phrases and query_pattern(tuple(phrases)).search(q))
