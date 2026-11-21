"""Лексические индексы. Кэш содержит массивы и JSON; загрузка не исполняет код."""
import hashlib
import json
import os
from tempfile import NamedTemporaryFile
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer,TfidfTransformer
from .bm25 import BM25F


def lexical(cfg,docs):
    digest=hashlib.sha256(json.dumps(docs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    path=cfg.cache/f"lex-v3-{digest}.npz"
    char=TfidfVectorizer(analyzer="char_wb",ngram_range=(3,5),dtype=np.float32)
    if path.exists():
        try:
            with np.load(path,allow_pickle=False) as data:
                vocab=json.loads(data["vocab"].item())
                char.vocabulary_=vocab
                char.fixed_vocabulary_=True
                char._tfidf=TfidfTransformer()
                char._tfidf.idf_=data["idf"]
                matrix=csr_matrix((data["values"],data["indices"],data["ptr"]),shape=(len(docs),len(vocab)))
                bm=BM25F([])
                bm.size=len(docs)
                bm.postings={k:(i,np.asarray(w)) for k,(i,w) in json.loads(data["bm"].item()).items()}
                return bm,char,matrix
        except (ValueError,KeyError,OSError):
            pass
    bm=BM25F(docs)
    if not docs:
        return bm,char,None
    matrix=char.fit_transform([" ".join(d[k] for k in ("title","aliases","vendor")) for d in docs])
    cfg.cache.mkdir(parents=True,exist_ok=True)
    with NamedTemporaryFile(dir=cfg.cache,delete=False) as out:
        np.savez_compressed(out,vocab=json.dumps(char.vocabulary_),idf=char.idf_,values=matrix.data,indices=matrix.indices,
                            ptr=matrix.indptr,bm=json.dumps({k:(i,w.tolist()) for k,(i,w) in bm.postings.items()}))
    os.replace(out.name,path)
    return bm,char,matrix
