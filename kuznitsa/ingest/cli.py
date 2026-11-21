import argparse
import json
from pathlib import Path

from kuznitsa.config import Config
from .catalog import import_catalog


def register(sub):
    day=sub.add_parser("day")
    day.add_argument("folder",type=Path)
    day.add_argument("--out",type=Path)
    day.add_argument("--mapping",type=Path)
    day.add_argument("--ai",choices=("off","embed","jev"),default="embed")
    day.add_argument("--ai-budget-usd",type=float,default=.5)
    day.add_argument("--n",type=int,default=300)
    check=sub.add_parser("selfcheck")
    check.add_argument("--n",type=int,default=300)
    check.add_argument("--seed",type=int,default=7)
    check.add_argument("--mode",choices=["fast","smart"],default="fast")
    check.add_argument("--report",type=Path)
    p=sub.add_parser("import-catalog")
    p.add_argument("files",type=Path,nargs="+")
    p.add_argument("--out",type=Path)
    p.add_argument("--mapping",type=Path)
    p.add_argument("--report",type=Path)
    p.add_argument("--ai",choices=("off","embed","jev"),default="embed")
    p.add_argument("--ai-budget-usd",type=float,default=.5)
    p.add_argument("--dry-run",action="store_true")


def run(args,cfg):
    if args.cmd=="day":
        from .day import day
        try:
            result=day(args.folder,cfg,args.out,args.ai,args.ai_budget_usd,args.n,args.mapping)
        except (OSError,ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        print(Path(result["out"])/"day_report.md")
        return True
    if args.cmd=="selfcheck":
        from .selfcheck import selfcheck
        result=selfcheck(cfg,args.n,args.mode,args.seed)
        body=json.dumps(result,ensure_ascii=False,indent=2)
        (args.report or cfg.data/"selfcheck.json").write_text(body)
        print(body)
        return True
    if args.cmd!="import-catalog":
        return False
    report=import_catalog(args.files,args.out or cfg.data,cfg.kb,args.mapping,args.report,args.dry_run,ai=args.ai,ai_budget_usd=args.ai_budget_usd)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report["offers"]:
        raise SystemExit("Нет пригодных предложений. Проверьте заголовки и соответствие столбцов.")
    return True


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    register(parser.add_subparsers(dest="cmd",required=True))
    run(parser.parse_args(),Config())
