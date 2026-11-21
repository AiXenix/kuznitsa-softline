"""Лексические признаки класса, операции и количества для запросов без названия продукта."""
import re

ENGLISH=(
    (r"antivirus|endpoint (?:security|protection)","endpoint_security","антивирус","category"),
    (r"(?:file |data )?compression|archiv(?:e|er|ing)","archivers","архиватор","category"),
    (r"(?:software )?(?:setup|install(?:ation)?|support) service","tech_support","техническая поддержка","service"),
    (r"office suite|spreadsheet|word processor","office_suite","офисный пакет","category"),
    (r"backup|disaster recovery","backup_recovery","резервное копирование","category"),
)
TASKS=(
    (r"(?:сохран|восстанов|скопир)\w* .*(?:баз|данны|виртуальн|машин|файл)","backup_recovery","резервное копирование"),
    (r"(?:заполн|созда|состав|рассчит)\w* .*таблиц","office_suite","электронные таблицы"),
)


def domain_request(text):
    for pattern,category,label,intent in ENGLISH:
        if re.search(r"\b(?:"+pattern+r")\b",text):
            return category,label,intent
    for pattern,category,label in TASKS:
        if re.search(pattern,text):
            return category,label,"task"


def mapped_class(engine,category,label):
    if category in engine.catalog.by["category"]:return category
    for title,ids in engine.catalog.source_classes.items():
        if any(w[:5] in title.lower() for w in label.split() if len(w)>4):
            return next(iter(sorted(ids)),None)


def descriptive_class(catalog,text):
    """У действия и объекта задачи должны быть свидетельства в описании товара."""
    if not re.match(r"^(?:нужно |хочу |как )?(?:сохрани|восстанови|состави|спланирова|обработа|рассчита|зашифрова|подписа)ть\b",text):
        return None
    from kuznitsa.text import tokens,lemma
    meaningful={lemma(w) for w in tokens(text) if len(w)>3}
    scores=catalog.bm.scores(text)
    for index in scores.argsort()[::-1][:5]:
        if scores[index]<.20:break
        card=catalog.cards[catalog.ids[index]]
        description=" ".join([card.title,card.offers[0].description,*card.offers[0].category_path])
        if len(meaningful & {lemma(w) for w in tokens(description)})>=2:
            return card.category
    return None
