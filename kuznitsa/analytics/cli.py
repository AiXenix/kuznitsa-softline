import json


def register(subparsers):
    for name in ("gen-history","gen-metrika","import-history","replay","insights","kpi","digest","cost"):
        p=subparsers.add_parser(name)
        if name=="gen-history":
            p.add_argument("--today")
            p.add_argument("--seed",type=int,default=20261126)
        if name=="import-history":
            p.add_argument("file",nargs="+")
            p.add_argument("--mapping")
        if name=="replay":
            p.add_argument("--limit",type=int,default=None)
            p.add_argument("--mode",choices=["smart","fast"],default="fast")
        if name=="digest":
            p.add_argument("--role")


def run(args,cfg):
    name=args.cmd
    if name not in ("gen-history","gen-metrika","import-history","replay","insights","kpi","digest","cost"):
        return False
    from .store import Journal
    journal=Journal(cfg.data/"kuznitsa.sqlite")
    if name in ("gen-history","gen-metrika","import-history","replay","insights"):
        from kuznitsa.engine import Engine
        from .controls import RuleControls
        e=Engine.open(cfg,journal=journal,controls=RuleControls(journal))
        if name=="gen-history":
            from kuznitsa.mock.querylog_gen import generate
            out=generate(e,args.seed,args.today)
        elif name=="gen-metrika":
            from kuznitsa.mock.metrika_gen import export
            out=export(e,cfg.data/"mock_metrika")
        elif name=="import-history":
            from kuznitsa.ingest.history import ingest_files
            out=ingest_files(e,args.file,args.mapping)
        elif name=="insights":
            from .insights import discover
            out=discover(e)
        else:
            from .replay import run
            out=run(e,args.mode,args.limit,cfg=cfg)
        if name in ("gen-history","import-history","insights","replay"):
            from .dashboard import warm
            warm(e)
    elif name=="kpi":
        from .kpi import report
        out=report(journal)
    elif name=="digest":
        from .digest import digest
        out=digest(journal,args.role)
    else:
        from .cost import report
        out=report(journal)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return True
