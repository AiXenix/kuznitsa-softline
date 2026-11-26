"""Документы классов и линеек из дерева поставщика."""
import numpy as np


def tree_documents(tree, descriptions):
    for key,(title,parent) in tree.items():
        if parent not in tree or not tree[parent][1]:
            continue
        yield key,parent,f"{tree[parent][0]}. {title}. {descriptions.get(key,'')[:220]}"


class TreeVectors:
    def __init__(self,tree,descriptions,dense,cfg):
        rows=list(tree_documents(tree,descriptions))
        self.leaves={key:i for i,(key,_,_) in enumerate(rows)}
        self.parents=[parent for _,parent,_ in rows]
        self.positions={key:i for i,key in enumerate(dict.fromkeys(self.parents))}
        self.groups=np.array([self.positions[k] for k in self.parents],dtype=np.intp)
        self.matrix=dense.cached_embeddings(cfg,[text for _,_,text in rows]) if hasattr(dense,"model") else None

    def neighbors(self,anchor,members):
        if self.matrix is None or anchor not in self.leaves:return {}
        return self.similarity(self.matrix[self.leaves[anchor]],members)

    def similarity(self,vector,members):
        if self.matrix is None:return {}
        hits=[cid for cid in members if cid in self.leaves]
        if not hits:return {}
        rows=self.matrix[[self.leaves[cid] for cid in hits]]
        scores=np.einsum("ij,j->i",rows,vector)
        return dict(zip(hits,scores))

    def scores(self,vector):
        if self.matrix is None:
            return {}
        sims=np.einsum("ij,j->i",self.matrix,vector)
        scores=np.full(len(self.positions),-1.,dtype=sims.dtype)
        np.maximum.at(scores,self.groups,sims)
        return {k:float(scores[i]) for k,i in self.positions.items()}
