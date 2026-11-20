import hashlib
import os
from functools import lru_cache
from tempfile import NamedTemporaryFile
from threading import Lock
import numpy as np


class Dense:
    def __init__(self,cfg,texts,knowledge=()):
        self.matrix=None
        self.knowledge_keys=[key for key,text in knowledge]
        self.knowledge_matrix=None
        if cfg.embed=="off" or not (texts or knowledge):
            return
        os.environ["HF_HUB_OFFLINE"]="1"
        from fastembed import TextEmbedding
        self.model=TextEmbedding(model_name=cfg.embed,cache_dir=str(cfg.models),threads=2,local_files_only=True)
        self.lock=Lock()
        self.encode=lru_cache(256)(self._query)
        self.matrix=self._cached(cfg,texts)
        self.knowledge_matrix=self._cached(cfg,[text for key,text in knowledge])

    def _cached(self,cfg,texts):
        if not texts:
            return None
        key=hashlib.sha256(("\0".join([cfg.embed,*texts])).encode()).hexdigest()
        cfg.cache.mkdir(parents=True,exist_ok=True)
        path=cfg.cache/f"dense-{key}.npy"
        if path.exists():
            try:
                matrix=np.load(path,allow_pickle=False)
                if matrix.ndim==2 and len(matrix)==len(texts):
                    return matrix
            except (OSError,ValueError):
                pass
        matrix=np.stack(list(self.model.embed(texts,batch_size=16)))
        matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-9)
        with NamedTemporaryFile(dir=cfg.cache,delete=False) as out:
            np.save(out,matrix,allow_pickle=False)
        os.replace(out.name,path)
        return matrix

    def _query(self,q):
        with self.lock:
            vector=next(self.model.query_embed(q))
        return vector/max(np.linalg.norm(vector),1e-9)

    def scores(self,q,n):
        if self.matrix is None:
            return np.zeros(n)
        return np.maximum(0,np.einsum("ij,j->i",self.matrix,self.encode(q)))

    def nearest_knowledge(self,q,threshold=.68):
        if self.knowledge_matrix is not None:
            sims=np.einsum("ij,j->i",self.knowledge_matrix,self.encode(q))
            i=int(np.argmax(sims))
            if sims[i]>=threshold:
                return (*self.knowledge_keys[i],float(sims[i]))
        return None
