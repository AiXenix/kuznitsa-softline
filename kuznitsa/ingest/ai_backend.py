"""The only import-time dependency on the engine's embedding and Decisions APIs."""
import json
import hashlib
import sqlite3
from contextlib import closing
from threading import Lock, local
import httpx
from time import time

import numpy as np

from kuznitsa.index.dense import Dense
from kuznitsa.llm.decisions import Decisions, choice
from kuznitsa.llm.jev import Disabled, Jev

GATEWAY="http://127.0.0.1:8098/decisions"


class Vectors:
    def __init__(self,cfg,documents,queries,volatile):
        fixed=[i for i in range(len(documents)) if i not in volatile]
        extra=sorted(volatile)
        # A path may contain ten nearly identical licensing configurations. Rank
        # by the distinct terms in the evidence and batch by length to reduce padding.
        def compact(text):
            return " ".join(dict.fromkeys(text.casefold().split()))[:560]
        lookups=list(dict.fromkeys([*queries,*(documents[i] for i in extra)]))
        texts={q:compact(q) for q in lookups}
        embeddings=sorted(set(texts.values()),key=lambda s:(len(s),s))
        dense=Dense(cfg,[documents[i] for i in fixed],list(enumerate(embeddings)))
        self.docs=None
        self.query={}
        if dense.knowledge_matrix is not None:
            by_text=dict(zip(embeddings,dense.knowledge_matrix))
            self.query={q:by_text[s] for q,s in texts.items()}
            self.docs=np.empty((len(documents),dense.knowledge_matrix.shape[1]),dtype=np.float32)
            if fixed:
                self.docs[fixed]=dense.matrix
            if extra:
                self.docs[extra]=[self.query[documents[i]] for i in extra]

    def scores(self,text,indices):
        if self.docs is None or not indices:
            return np.zeros(len(indices))
        return np.einsum("ij,j->i",self.docs[indices],self.query[text])


def estimate(state,questions):
    # Conservative reservation using UTF-8 byte count as a token upper bound.
    size=len(json.dumps([state,questions],ensure_ascii=False).encode())
    return (size+2048)*.042/1_000_000


def questionnaire(kind,options):
    return {kind:choice("Выберите наиболее подходящий вариант по назначению товара. При недостатке данных выберите none.",options)}


def cached_keys(path):
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as db:
        return {row[0] for row in db.execute("SELECT key FROM llm_cache")}


def forecast(state,kind,options,keys):
    questions=questionnaire(kind,options)
    payload=json.dumps([Disabled.model,state,questions],sort_keys=True,ensure_ascii=False)
    hit=hashlib.sha256(payload.encode()).hexdigest() in keys
    return (0. if hit else estimate(state,questions)),hit


class ImportClient(Jev):
    def __init__(self,transport):
        super().__init__(url=GATEWAY,transport=transport)
        self.last=local()

    def complete(self,state,questions):
        self.last.error=None
        try:
            return super().complete(state,questions)
        except httpx.HTTPStatusError as exc:
            self.last.error=f"http_{exc.response.status_code}"
            raise
        except httpx.TransportError:
            self.last.error="network"
            raise


def search_client(mode):
    return Jev(url=GATEWAY) if mode=="smart" else Disabled()


class Gateway:
    def __init__(self,path,budget,transport=None):
        self.client=ImportClient(transport)
        self.live=Decisions(self.client,path,time,budget=float("inf"))
        self.cache=Decisions(Disabled(),path,time,budget=0)
        self.remaining=budget
        self.lock=Lock()
        self.failure=None

    def request(self,obj,state,kind,options):
        questions=questionnaire(kind,options)
        reserve=estimate(state,questions)
        with self.lock:
            reason=self.failure or ("budget" if reserve>self.remaining else None)
            if not reason:
                self.remaining-=reserve
        answers,meta=(self.cache if reason else self.live).request(obj,"import","catalog_"+kind,state,questions)
        with self.lock:
            if not reason:
                self.remaining+=reserve-meta["usd"]
                if not meta["ok"]:
                    self.failure=getattr(self.client.last,"error",None) or "gateway"
        return answers.get(kind),meta,None if meta["ok"] else reason or self.failure or "gateway"

    def close(self):
        self.client.close()
        for decisions in (self.live,self.cache):
            decisions.pool.shutdown()


def reuse_knowledge_vectors(cfg):
    """Compose the index's immutable knowledge matrix from cached base and imported labels."""
    import os
    from pathlib import Path
    from tempfile import NamedTemporaryFile
    from kuznitsa.kb.loader import load
    if cfg.embed=="off" or not (cfg.data/"kb_auto.yaml").exists():
        return
    kb=load(cfg.kb,cfg.data)
    def cache_path(texts):
        digest=hashlib.sha256("\0".join([cfg.embed,*texts]).encode()).hexdigest()
        return cfg.cache/f"dense-{digest}.npy"
    texts=[]
    base=[]
    for group in ("categories","use_cases","roles","industries","faq"):
        for key,row in kb.rows[group].items():
            words=[row.get("title",key),*row.get("phrases",[])[:3],*row.get("questions",[])[:3],*row.get("synonyms",[])[:3]]
            texts.append(". ".join(map(str,words)))
            if not key.startswith("auto_"):
                base.append(texts[-1])
    dest=cache_path(texts)
    src=cache_path(base)
    if dest.exists() or not src.is_file():
        return
    try:
        vectors=np.load(src,mmap_mode="r",allow_pickle=False)
    except (ValueError,OSError):
        return
    if vectors.ndim!=2 or len(vectors)!=len(base):
        return
    by_text=dict(zip(base,vectors))
    missing=list(dict.fromkeys(t for t in texts if t not in by_text))
    if missing:
        imported=Dense(cfg,missing)
        by_text.update(zip(missing,imported.matrix))
    with NamedTemporaryFile(dir=cfg.cache,delete=False) as stream:
        try:
            np.save(stream,np.stack([by_text[t] for t in texts]),allow_pickle=False)
            stream.flush()
            os.replace(stream.name,dest)
        finally:
            Path(stream.name).unlink(missing_ok=True)
