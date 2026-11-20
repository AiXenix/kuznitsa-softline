from collections import Counter, defaultdict
from math import log1p
import numpy as np
from kuznitsa.text import tokens,lemma


class BM25F:
    def __init__(self,documents):
        combined = defaultdict(dict)
        for name,weight in dict(title=3,aliases=3,vendor=2,category=1.5,keywords=1.5,summary=1,names=.7).items():
            counts = [Counter(lemma(w) for w in tokens(d[name])) for d in documents]
            avg = max(1,sum(c.total() for c in counts)/max(1,len(counts)))
            for i,c in enumerate(counts):
                length_norm = .25+.75*c.total()/avg
                for word,n in c.items():
                    row = combined[word]
                    row[i] = row.get(i,0)+weight*n/length_norm
        self.size = len(documents)
        self.postings = {}
        for word, row in combined.items():
            idf = log1p((self.size-len(row)+.5)/(len(row)+.5))
            values = np.array(list(row.values()))
            self.postings[word] = (list(row),idf*2.2*values/(values+1.2))

    def scores(self,q):
        scores = np.zeros(self.size)
        for w in set(map(lemma,tokens(q))):
            if w in self.postings:
                indices,weights = self.postings[w]
                scores[indices] += weights
        return scores/(scores+3)
