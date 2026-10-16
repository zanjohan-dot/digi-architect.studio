#!/usr/bin/env python3
"""Remove demonstration listings from the published workbook.

  python _directory-sync/remove_demo.py           # list demo rows only
  python _directory-sync/remove_demo.py --apply   # back up, then remove them

Only rows with Is Demo = TRUE are removed. A full copy of the workbook is
saved to _directory-sync/backups/ first. The website's DATA_VERSION is bumped
so browsers fetch the new file.
"""
import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dsync import SGT_TZ  # noqa: E402
from dsync.match import TRUEISH  # noqa: E402
from dsync.workbook import bump_data_version, read_directory, remove_records  # noqa: E402

WORKBOOK = HERE.parent / "data" / "muslim-friendly-establishments.xlsx"
PAGE = HERE.parent / "muslim-friendly-directory.html"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--workbook", default=str(WORKBOOK))
    args = p.parse_args()
    _, rows = read_directory(args.workbook)
    demo = [r for r in rows if str(r.get("Is Demo", "")).strip().lower() in TRUEISH]
    live = [r for r in rows if r not in demo]
    for r in demo:
        print(f"DEMO  {r['ID']}  {r['Name']}  ({r.get('Listing Status')})")
    print(f"{len(demo)} demo listing(s); {len(live)} live listing(s) will be kept.")
    if not demo or not args.apply:
        return 0
    today = dt.datetime.now(ZoneInfo(SGT_TZ)).date()
    backup = HERE / "backups" / f"{today.isoformat()}-before-demo-removal.xlsx"
    backup.parent.mkdir(exist_ok=True)
    shutil.copyfile(args.workbook, backup)
    remove_records(args.workbook, {r["ID"] for r in demo})
    if Path(args.workbook).resolve() == WORKBOOK.resolve():
        bump_data_version(PAGE, today.strftime("%Y%m%d"))
    print(f"Removed {len(demo)} demo listing(s). Backup: {backup.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
