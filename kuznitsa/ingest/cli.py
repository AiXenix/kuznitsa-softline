import argparse
import json
from pathlib import Path

from kuznitsa.config import Config
from .catalog import import_catalog


def register(sub):
    p=sub.add_parser("import-catalog")
    p.add_argument("files",type=Path,nargs="+")
    p.add_argument("--out",type=Path)
    p.add_argument("--mapping",type=Path)
    p.add_argument("--report",type=Path)
    p.add_argument("--dry-run",action="store_true")


def run(args,cfg):
    if args.cmd!="import-catalog":
        return False
    report=import_catalog(args.files,args.out or cfg.data,cfg.kb,args.mapping,args.report,args.dry_run)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report["offers"]:
        raise SystemExit("Нет пригодных предложений. Проверьте заголовки и соответствие столбцов.")
    return True


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    register(parser.add_subparsers(dest="cmd",required=True))
    run(parser.parse_args(),Config())
