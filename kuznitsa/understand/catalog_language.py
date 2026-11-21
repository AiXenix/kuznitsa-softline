"""Лексические признаки класса, операции и количества для запросов без названия продукта."""
import re

CLASSES=(
    (r"антивирь|от вирусов|защит[ауы] (?:телефон|смартфон)\w*","endpoint_security","антивирус","category"),
    (r"резервировани\w*|резервн\w+ копи[яюи]","backup_recovery","резервное копирование","category"),
    (r"архиватор\w*","archivers","архиватор","category"),
    (r"менеджер\w* парол\w*","iam_pam_mfa","менеджеры паролей","category"),
    (r"antivirus|endpoint (?:security|protection)","endpoint_security","антивирус","category"),
    (r"(?:file |data )?compression|archiv(?:e|er|ing)","archivers","архиватор","category"),
    (r"(?:software )?(?:setup|install(?:ation)?|support) service","tech_support","техническая поддержка","service"),
    (r"translation (?:tool|software|suite)s?","translation_dictionaries","переводчики словари","category"),
    (r"office (?:productivity )?suites?|spreadsheet|word processor","office_suite","офисный пакет","category"),
    (r"backup|disaster recovery","backup_recovery","резервное копирование","category"),
)
TASKS=(
    (r"(?:метрик\w*|мониторинг)\s+(?:pgsql|postgres\w*|постгрес\w*)","db_management_tools","мониторинг субд"),
    (r"(?:провер\w*|измер\w*|анализ\w*).*покрыти\w*.*(?:вайф|wi[ -]?fi|беспроводн)","wireless_survey","замер покрытия wifi беспроводная сеть"),
    (r"восстановлени\w* носител","data_recovery","восстановление данных"),
    (r"(?:сохран|восстанов|скопир)\w* .*(?:баз|данны|виртуальн|машин|файл)","backup_recovery","резервное копирование"),
    (r"(?:заполн|созда|состав|рассчит)\w* .*таблиц","office_suite","электронные таблицы"),
)


def domain_request(text):
    from .audience import audience
    if text.startswith("антивирус ") and audience(text)=="home":
        return "endpoint_security","антивирус","category"
    for pattern,category,label,intent in CLASSES:
        if re.search(r"\b(?:"+pattern+r")\b",text):
            if re.fullmatch("[a-z0-9 -]+",text):
                tail=re.sub(pattern,"",text,count=1)
                if set(re.findall(r"[a-z]+",tail))-{"for","a","the","software","tools","program","seats","seat","users","user","devices","device","licenses","license"}:
                    continue
            return category,label,intent
    for pattern,category,label in TASKS:
        if re.search(pattern,text):
            return category,label,"task"


def mapped_class(engine,category,label):
    from kuznitsa.text import lemma,tokens
    if engine.catalog.by["category"].get(category):return category
    # На чужом дереве выбираем наиболее близкий продаваемый лист.
    hints={"archivers":"сжатие архиватор архивация файлов","tech_support":"услуги установка настройка поддержка",
           "office_suite":"офисный пакет текст таблица","translation_dictionaries":"перевод переводчик словарь",
           "endpoint_security":"антивирус антивирусный","wireless_survey":"беспроводной wifi вайфай",
           "db_management_tools":"мониторинг субд серверов","backup_recovery":"резервный копирование"}
    terms={lemma(w)[:5] for w in tokens(label+" "+hints.get(category,"")) if len(w)>2}
    scored=[]
    for title,ids in engine.catalog.source_classes.items():
        words={lemma(w)[:5] for w in tokens(title.replace("Wi-Fi","wifi").replace("wi-fi","wifi"))}
        overlap=terms & words
        if overlap:
            scored.extend((len(overlap)/len(words),len(overlap),cid) for cid in ids if cid)
    return max(scored)[2] if scored else None


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
