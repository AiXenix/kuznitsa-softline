import argparse
import json
from pathlib import Path
from .config import Config,ROOT
from .kb.loader import load
from .mock.catalog_gen import build
from .schema import Request
from .optional import optional_module


def show(value):
    print(json.dumps(value,ensure_ascii=False,indent=2))


def main(argv=None):
    cfg=Config()
    parser=argparse.ArgumentParser(prog="kuznitsa")
    sub=parser.add_subparsers(dest="cmd",required=True)
    sub.add_parser("kb-check")
    sub.add_parser("build-index")
    mock=sub.add_parser("build-mock")
    from datetime import date
    mock.add_argument("--today",type=date.fromisoformat)
    mock.add_argument("--seed",type=int,default=20261126)
    p=sub.add_parser("search")
    p.add_argument("q")
    p.add_argument("--profile",default="guest")
    p.add_argument("--explain",action="store_true")
    p.add_argument("--mode",choices=["smart","fast","naive"],default=cfg.mode)
    p=sub.add_parser("eval")
    p.add_argument("file",type=Path)
    p.add_argument("--mode",default="fast",choices=["smart","fast","naive"])
    p.add_argument("--budget-usd",type=float,default=cfg.daily_budget)
    p=sub.add_parser("serve")
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8097)
    analytics = optional_module("kuznitsa.analytics.cli")
    if analytics is not None:
        analytics.register(sub)
    args=parser.parse_args(argv)
    if analytics is not None and analytics.run(args, cfg):
        return 0
    if args.cmd in ("kb-check","build-mock"):
        kb=load(cfg.kb)
        if args.cmd=="kb-check":
            show(kb.report())
            return int(bool(kb.syntax))
        print(f"Предложений · {build(cfg,kb,args.seed,args.today)}")
    elif args.cmd=="serve":
        import uvicorn
        uvicorn.run("kuznitsa.app:app",host=args.host,port=args.port)
    else:
        from .engine import Engine
        engine=Engine.open(cfg)
        if args.cmd=="build-index":
            print(f"Карточек · {len(engine.catalog.cards)}")
        elif args.cmd=="search":
            show(engine.search(Request(q=args.q,profile_id=args.profile,mode=args.mode,explain=args.explain)))
        else:
            from .evaluation import evaluate
            path = args.file
            if not path.exists() and path.resolve()==ROOT/"eval/queries.dev.jsonl":
                print("Файл dev ещё не появился. Запущена отдельная проверка на трёх демонстрационных запросах.")
                path=ROOT/"tests/fixtures/dev_smoke.jsonl"
            if engine.decisions:
                engine.decisions.run_budget=args.budget_usd
            result=evaluate(engine,path,args.mode,cfg.data)
            show(result)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
