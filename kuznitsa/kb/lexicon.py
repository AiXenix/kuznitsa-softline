from collections import defaultdict
from kuznitsa.text import tokens,lemma
from .loader import many

GROUP = dict(vendor="vendors",family="families",category="categories",role="roles",industry="industries",use_case="use_cases",faq="faq",compliance="compliance")
ATTR = dict(license_action="action",license_metric="metric",license_model="model",cert="certs",compat_ru_os="platform")
BUILTIN = {
    "metric":{"device":"пк|комп|компьютер|устройство|узел|node","user":"пользователь|сотрудник|место|user|человек",
              "server":"сервер","core":"ядро|core","cpu":"процессор|сокет","vm":"виртуальная машина|вм","mailbox":"почтовый ящик"},
    "action":{"renewal":"продление|продлить|продленка|renewal","new":"новая лицензия|базовая лицензия","upgrade":"апгрейд","addon":"докупить"},
    "model":{"perpetual":"бессрочная|вечная","subscription":"подписка"},
    "platform":{"linux":"linux|линукс","windows":"windows|виндовс","macos":"macos|макос"},
    "audience":{"edu":"для образования|академическая|для вуза|для школы","gov":"для госучреждений","business":"для бизнеса"},
    "delivery":{"box":"коробка","esd":"электронная поставка"},
    "edition":{"pro":"про|pro"},
    "certs":{"fstec":"фстэк","fsb":"фсб"},
    "registry":{True:"из реестра"}
}


class Lexicon:
    def __init__(self,kb,catalog):
        self.entries = defaultdict(list)
        self.words = set()
        self.phrases = defaultdict(set)
        self.compact = {}
        for kind,group in GROUP.items():
            for ident,r in kb.rows[group].items():
                for field in ("name","name_ru","title","title_short","aliases","synonyms","slang","phrases","questions"):
                    for alias in many(r.get(field)):
                        self.add(alias,kind,ident,"kb")
                if kind=="family":
                    for ed in r.get("editions",[]):
                        for alias in [ed.get("name"),ed["id"],*many(ed.get("aliases"))]:
                            self.add(alias,"edition",ed["id"],"kb")
        for c in catalog.cards.values():
            o = c.offers[0]
            for name,kind,ident in [(o.family_name or o.name,"family",c.family),(o.vendor,"vendor",c.vendor),(o.edition,"edition",o.edition),
                                    ((o.category_path or [None])[-1],"category",c.category)]:
                self.add(name,kind,ident,"catalog")
        for k,values in BUILTIN.items():
            for v,aliases in values.items():
                for alias in aliases.split("|"):
                    self.add(alias,k,v,"dictionary")
        for phrase,r in kb.rows["slang"].items():
            mapping = r["maps_to"]
            if "attr" in mapping:
                pairs = [(ATTR.get(mapping["attr"],mapping["attr"]),mapping.get("value"))]
            else:
                pairs = mapping.items()
            for k,v in pairs:
                if k not in GROUP or str(v) in kb.rows[GROUP[k]]:
                    self.add(phrase,k,v,"slang")

    def add(self,phrase,k,v,source):
        if not phrase or v is None or not isinstance(v,(str,bool,int)):
            return
        raw = tokens(str(phrase))
        key = tuple(map(lemma,raw))
        if not 1<=len(key)<=6:
            return
        self.words.update(raw)
        if k in {"vendor","family","category"}:
            self.phrases[" ".join(raw)].add((k,v))
        if len(raw)>1:
            self.compact.setdefault("".join(raw)," ".join(raw))
        if all((k,v)!=item[:2] for item in self.entries[key]):
            self.entries[key].append((k,v,source))

    def match(self,words):
        keys = list(map(lemma,words))
        i=0
        while i<len(keys):
            for end in range(min(i+6,len(keys)),i,-1):
                found = self.entries.get(tuple(keys[i:end]))
                if found:
                    yield i,end,found
                    i=end
                    break
            else:
                i+=1
