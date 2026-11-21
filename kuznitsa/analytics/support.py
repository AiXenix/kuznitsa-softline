"""Обращения покупателей, тематическая сводка и подтверждение проблемы поиском."""
import hashlib
import re
from collections import Counter
from functools import lru_cache

from kuznitsa.plans.knowledge import STOP
from kuznitsa.text import lemma, normalize, tokens
from .replay import products
from .store import dump


TOPICS = [
    ("Совместимость", r"совместим|работает ли|поддержива|операционн"),
    ("Продление", r"продл|истека|заканчива"),
    ("Цена и оплата", r"цен[ауые]|стоимост|оплат|счет"),
    ("Поставка и наличие", r"наличи|постав|купить|прода[её]те|найти"),
    ("Установка и активация", r"установ|активир|активац"),
    ("Лицензирование", r"лиценз|право использован"),
]


def digest_key(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def import_chat(engine, db, path, records, columns, timestamp, resolve):
    db.execute("""CREATE TABLE IF NOT EXISTS support_messages(
        id TEXT PRIMARY KEY, ts REAL, client TEXT, question TEXT, topic TEXT, faq TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS support_mentions(
        message TEXT REFERENCES support_messages(id) ON DELETE CASCADE, product TEXT, phrase TEXT,
        product_key TEXT, phrase_key TEXT, PRIMARY KEY(message,product_key,phrase_key))""")
    db.execute("""CREATE TABLE IF NOT EXISTS support_files(
        file TEXT, message TEXT REFERENCES support_messages(id) ON DELETE CASCADE, PRIMARY KEY(file,message))""")
    db.execute("DELETE FROM support_files WHERE file=?", (path.name,))

    @lru_cache(4096)
    def classify(question):
        terms = set(map(lemma, tokens(question))) - STOP
        for fid in engine.knowledge.nearest("faq", question):
            entry = engine.kb.rows["faq"][fid]
            labels = engine.knowledge.labels["faq"][fid]
            if entry.get("answer") and any(words and len(words & terms)/max(len(terms),len(words)) >= .60
                                           for words in labels):
                return entry.get("title") or entry["questions"][0], fid
        return next((name for name, pattern in TOPICS if re.search(pattern, question, re.I)), "Другие вопросы"), None

    @lru_cache(4096)
    def mentions(question, product, code):
        if product or code:
            offer = resolve(code)
            label = product or (offer.family_name or offer.name if offer else code)
            return [(label, code or product)]
        found = {}
        words = tokens(question)
        for start,end,matches in engine.lex.match(words):
            for kind,fid,_ in matches:
                if kind == "family" and fid in engine.kb.rows["families"]:
                    title = engine.kb.rows["families"][fid]["title"]
                    found[normalize(title)] = (title," ".join(words[start:end]))
        for word in re.findall(r"[\w.-]+",question):
            if any(c.isdigit() for c in word) and (offer := resolve(word)):
                title = offer.family_name or offer.name
                found[normalize(title)] = (title,word)
        if not found:
            for name in re.findall(r'(?:товар|продукт|программу|пакет|лицензию на)\s+[«"]([^»"]{2,80})[»"]',question,re.I):
                found[normalize(name)] = (name,name)
            for name in re.findall(r"(?i:есть ли (?:у вас )?|поставляете |можно купить )"
                                   r"([A-Z][a-zA-Z0-9.-]+(?: [A-Z][a-zA-Z0-9.-]+){0,3})(?=[?!,;.]|$)",
                                   question):
                found[normalize(name)] = (name,name)
            for code in re.findall(r"(?:артикул|sku|код товара)\s*[:№#]?\s*([\w]+[.-][\w.-]+)",question,re.I):
                found[normalize(code)] = (code,code)
        return list(found.values())

    topics = Counter()
    skipped = Counter()
    read = duplicates = 0
    first = last = None
    for raw in records:
        read += 1
        row = {field:str(raw.get(k) or "").strip() for k,field in columns.items()}
        question = row.get("question","")
        if not question:
            skipped["Пустой вопрос"] += 1
            continue
        try:
            ts = timestamp(row.get("ts"), None)
            if ts is None:
                raise ValueError
        except ValueError:
            skipped["Нет даты обращения"] += 1
            continue
        client = digest_key(row["client_id"].casefold()) if row.get("client_id") else None
        empty = {"", "-", "—", "нет", "не указано", "n/a", "null"}
        product, code = (row.get(k,"") if row.get(k,"").casefold() not in empty else "" for k in ("product","target"))
        ident = digest_key([ts, client, normalize(question), normalize(product), normalize(code)])
        topic, faq = classify(question)
        db.execute("INSERT INTO support_messages VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET topic=excluded.topic,faq=excluded.faq",
                   (ident, ts, client, question, topic, faq))
        if not db.execute("INSERT OR IGNORE INTO support_files VALUES (?,?)", (path.name, ident)).rowcount:
            duplicates += 1
            continue
        db.execute("DELETE FROM support_mentions WHERE message=?", (ident,))
        for label, phrase in mentions(question,product,code):
            db.execute("INSERT OR IGNORE INTO support_mentions VALUES (?,?,?,?,?)",
                       (ident,label,phrase,normalize(label),normalize(phrase)))
        topics[topic] += 1
        first = min(first,ts) if first is not None else ts
        last = max(last,ts) if last is not None else ts
    db.execute("DELETE FROM support_messages WHERE id NOT IN (SELECT message FROM support_files)")
    return path.name, dict(kind="support_chat", file=path.name, source_type="Чат поддержки",
            summary_only=True, searches=0, events=0, rows_read=read, rows_accepted=read-sum(skipped.values())-duplicates,
            duplicates=duplicates, skipped=sum(skipped.values()), skip_reasons=dict(skipped), columns=columns,
            recognized=list(columns), ignored=[], period=[first,last] if first is not None else None,
            missing=["Обращения учитываются отдельно от поисковых визитов."], topics=dict(topics))


def exists(journal):
    return bool(journal.rows("SELECT 1 FROM sqlite_master WHERE name='support_messages'"))


def overview(journal):
    note = "Вопрос попадает в список, если в базе FAQ не найден близкий по словам вопрос с ответом."
    result = dict(messages=0, clients=0, unanswered_count=0, topics=[], products=[], unanswered=[], note=note)
    if exists(journal):
        result.update(journal.rows("""SELECT count(*) messages,count(DISTINCT client) clients,
                    count(*) FILTER (WHERE faq IS NULL) unanswered_count FROM support_messages""")[0])
        result["topics"] = journal.rows("""SELECT topic,count(*) messages FROM support_messages
                    GROUP BY topic ORDER BY messages DESC,topic LIMIT 30""")
        result["products"] = journal.rows("""SELECT min(product) product,count(DISTINCT message) messages
                    FROM support_mentions GROUP BY product_key ORDER BY messages DESC,product LIMIT 30""")
        result["unanswered"] = journal.rows("""SELECT question,count(*) messages FROM support_messages WHERE faq IS NULL
                    GROUP BY question ORDER BY messages DESC,question LIMIT 30""")
    return result


def proposals(engine, probe, dataset):
    j = engine.journal
    if not exists(j):
        return
    from kuznitsa.ingest.history import offer_resolver
    resolve = offer_resolver(engine.catalog)
    catalog_names = {}
    for card in engine.catalog.cards.values():
        for name in (card.title, card.offers[0].family_name):
            if name:
                catalog_names.setdefault(normalize(name),set()).add(card.id)
    counts = j.rows("""SELECT min(product) product,min(phrase) phrase,product_key,phrase_key,count(*) messages,count(DISTINCT client) clients
        FROM support_mentions JOIN support_messages ON id=message
        GROUP BY product_key,phrase_key HAVING clients>=2
        ORDER BY clients DESC,messages DESC,product,phrase LIMIT 100""")
    for row in counts:
        name, phrase = row["product"], row["phrase"]
        if len(phrase)>300 or normalize(name) in engine.catalog.retired:
            continue
        offer = resolve(phrase) or engine.catalog.offer_names.get(normalize(name))
        targets = {offer.card_id} if offer else {
            card for _,_,matches in engine.lex.match(tokens(name)) for kind,fid,_ in matches if kind=="family"
            for card in engine.catalog.by["family"].get(fid,())}
        if not offer:
            targets.update(catalog_names.get(normalize(name),()))
        resp = probe(phrase)
        cards = [c["card_id"] for c in products(resp)[:5]]
        if resp["understood"].get("zero_reason") == "vendor_left" or any(
                b.get("reason") == "vendor_left" for b in resp["blocks"]):
            continue
        absent = any(b["type"]=="not_in_catalog" for b in resp["blocks"])
        if targets.intersection(cards):
            continue
        if not targets and (cards and not absent or resp["query"].get("corrections")):
            continue
        kind = "fix_card" if targets else "add_product"
        examples = j.rows("""SELECT id,question FROM support_messages JOIN support_mentions ON id=message
                WHERE product_key=? AND phrase_key=? ORDER BY ts DESC,id LIMIT 3""",(row["product_key"],row["phrase_key"]))
        sid = resp["search_id"]
        evidence = dict(source="support_chat", clients=row["clients"], messages=row["messages"], questions=examples,
                        sample_queries=[phrase], examples=[dict(q=phrase,search_id=sid)], search_ids={phrase:sid},
                        checks={phrase:dict(search_id=sid,top5=cards)}, target_card_ids=sorted(targets))
        title = ("Проверить поиск карточки" if targets else "Проверить поставку") + " · " + name
        effect = "Денежная оценка недоступна. В обращениях нет заказов, связанных с этим товаром."
        text = (f"Обращений — {row['messages']}, клиентов — {row['clients']}. "
                f"Проверен запрос «{phrase}». " + ("Карточка отсутствует в первой пятёрке." if targets else
                  "Поиск сообщает об отсутствии товара." if absent else "Поиск не вернул товарных карточек."))
        payload = dict(product=name)
        if targets:
            payload.update(card_ids=sorted(targets),field="search_terms",phrase=phrase)
        yield dict(id=kind+"-chat-"+digest_key([dataset,normalize(name),normalize(phrase)])[:16],
                   type=kind, role="content_manager", dataset=dataset, status="new", priority="medium", confidence=None,
                   title=title, summary=text, evidence=evidence, evidence_text=text, impact_text=effect,
                   action=dict(kind="ticket",label="Создать задачу контент-менеджеру",payload_json=payload),
                   impact=dict(expected_rub=None,conservative_rub=None,formula_note=effect))
