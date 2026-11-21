from .decisions import choice


def ask_recovery(engine,deadline,sid,req,state,calls,steps,options,examples):
    criteria={**options,"clarify":"Попросить покупателя уточнить термин или обязательное условие"}
    if not options:
        criteria["unavailable"]="Сообщить об отсутствии подходящего предложения"
    facts={**state,"доступные_варианты":examples,"строго_подходящих":0}
    answers,meta=engine.decisions.decide_before(deadline,sid,req.model_source,"intent",facts,{
        "recovery":choice("Выберите следующий шаг поиска. Показывайте только подтверждённые варианты.",criteria)})
    meta["probabilities"]={k:v["probabilities"] for k,v in answers.items()}
    calls.append(meta)
    step=next(s for s in steps if s["step"]=="intent")
    step["detail"]["calls"].append(meta)
    step["summary"]+=" · проверены варианты уточнения"
    if not meta["ok"]:
        step["status"]="fallback"
    answer=answers.get("recovery",{})
    result=answer.get("choice")
    if answer.get("probabilities",{}).get(result,0)>=.55:
        return result


def cost_summary(calls,usd_rub):
    savings=0.
    for meta in calls:
        meta["rub"]=meta["usd"]*usd_rub
        if meta["cached"]:
            original=meta.get("saved_usd")
            meta["saved_rub"]=None if original is None else original*usd_rub
            if savings is not None:
                savings=None if original is None else savings+original*usd_rub
    usd=sum(m["usd"] for m in calls)
    return dict(llm_calls=sum(m["sent"] for m in calls),cached=sum(m["cached"] for m in calls),
                tokens_in=sum(m["tokens_in"] for m in calls),usd=usd,rub=usd*usd_rub,saved_rub=savings,
                pending=any(m.get("pending") for m in calls))
