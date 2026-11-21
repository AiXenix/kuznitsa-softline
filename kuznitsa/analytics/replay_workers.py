"""Изолированные процессы для большого парного прогона в режиме fast."""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import get_context
import os

from kuznitsa.schema import Request
from kuznitsa.controls import Controls
from .controls import RuleControls
from .store import Journal, result_cards


def initialize(cfg, snapshot, merchant, now, names):
    from kuznitsa.engine import Engine, Disabled
    global worker_engine
    journal = Journal(":memory:")
    with journal.transaction() as db:
        for table, rows in snapshot.items():
            if rows:
                columns = list(rows[0])
                db.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                               ([row[k] for k in columns] for row in rows))
    controls = RuleControls(journal) if merchant else Controls()
    worker_engine = Engine.open(cfg, clock=lambda: now, llm=Disabled(), controls=controls, journal=journal)
    catalog = worker_engine.catalog
    catalog.offer_names.update({key:catalog.offers_by_id[oid] for key,oid in names.items()})


def search_batch(phrases):
    j = worker_engine.journal
    batch = []
    for q in phrases:
        response = worker_engine.search(Request(q=q, source="replay", mode="fast", page_size=10))
        ident = response["search_id"]
        archived = j.rows("SELECT * FROM searches WHERE search_id=?", (ident,))[0]
        with j.transaction() as db:
            db.execute("DELETE FROM searches WHERE search_id=?", (ident,))
        cards = [dict(card_id=c["card_id"],offer=c.get("offer")) for c in result_cards(response)]
        analogs = any(b["type"]=="analogs" and b.get("items") for b in response["blocks"])
        batch.append((q,archived,cards,bool(analogs)))
    return batch


def batches(engine, cfg, phrases):
    j = engine.journal
    rows = dict(rules=j.rows("SELECT * FROM rules"), priorities=j.rows("SELECT * FROM priorities"),
                kv=j.rows("SELECT * FROM kv WHERE key IN ('settings:weights','rules:version')"))
    workers = min(8, len(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else os.cpu_count() or 1)
    names = {key:o.offer_id for key,o in engine.catalog.offer_names.items()}
    chunks = iter(phrases[i:i+24] for i in range(0,len(phrases),24))
    with ProcessPoolExecutor(workers,mp_context=get_context("spawn"),initializer=initialize,
            initargs=(cfg,rows,isinstance(engine.controls,RuleControls),engine.clock(),names)) as pool:
        pending=set()
        while True:
            while len(pending)<2*workers:
                chunk=next(chunks,None)
                if chunk is None:
                    break
                pending.add(pool.submit(search_batch,chunk))
            if not pending:
                return
            ready,pending=wait(pending,return_when=FIRST_COMPLETED)
            for future in ready:
                yield future.result()
