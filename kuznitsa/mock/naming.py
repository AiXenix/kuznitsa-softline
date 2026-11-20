AUD = dict(gov="для госучреждений",edu="академическая",business="для организаций",home="для дома",med="для медучреждений",nonprofit="для НКО")
METRIC = dict(device="устройств",user="пользователей",core="ядер",server="серверов",vm="виртуальных машин",company="организаций",
              concurrent="одновременных подключений",cpu="процессоров",mailbox="почтовых ящиков",site="площадок",storage="ед. хранения")
ACTION = dict(renewal="продление",new="новая лицензия",addon="расширение",crossgrade="переход",support="поддержка",upgrade="обновление")


def sku_name(f,edition,version,action,term,lo,hi,pack,aud,metric,delivery):
    title=" ".join(str(x) for x in [f["name"],version,edition.get("name")] if x)
    size=f"{lo}–{hi}" if lo and hi else f"{lo}+" if lo else str(pack or 1)
    if f.get("vendor")=="kaspersky":
        english_metric={"device":"Node","user":"User"}.get(metric,metric.title())
        duration=f"{term//12} year" if term and term%12==0 else f"{term} month" if term else "Perpetual"
        return f"{title} Russian Edition. {size} {english_metric} {duration} {action.title()} License {aud.upper()}"
    if f.get("vendor")=="microsoft":
        return f"{title} Russian {delivery.upper()} {size} {metric.title()} {aud.upper()} {action.title()} "+(f"{term}M" if term else "Perpetual")
    scope=f"пакет на {pack}" if pack else size
    duration=f"{term} мес." if term else "бессрочная"
    return f"{title}, {ACTION.get(action,action)}, {scope} {METRIC.get(metric,'ед.')}, {duration}, {AUD.get(aud,aud)}, {delivery.upper()}"
