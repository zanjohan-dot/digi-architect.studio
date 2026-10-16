#!/usr/bin/env python3
"""Month-end maintenance run for the Muslim-Friendly Dining Directory.

Usage:
  python _directory-sync/sync.py                 # scheduled run (exits unless today is month-end in SGT)
  python _directory-sync/sync.py --force         # run now regardless of date
  python _directory-sync/sync.py --force --offline fixture.json   # tests: no network

What it does (and does not do):
  * Checks the published workbook for duplicates, incomplete records and
    certification records that need re-verification. It never edits it.
  * Refreshes candidate records from lawfully reusable sources
    (OpenStreetMap; any permitted dataset in inbox/permitted/).
  * Matches candidates to existing listings, flags duplicates, keeps
    branches separate, and records new / changed / no-longer-found records.
  * Writes state/candidates.csv (the review queue), state/sync-log.csv
    (audit trail) and reports/YYYY-MM.md (monthly report).
"""
import argparse
import calendar
import csv
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dsync import SGT_TZ  # noqa: E402
from dsync.match import dedupe_sources, directory_checks, match_candidate, TRUEISH  # noqa: E402
from dsync.sources import SourceError, fetch_osm, load_permitted, osm_record  # noqa: E402
from dsync.workbook import read_directory  # noqa: E402

REPO = HERE.parent
WORKBOOK = REPO / "data" / "muslim-friendly-establishments.xlsx"
STATE = HERE / "state"
REPORTS = HERE / "reports"
INBOX = HERE / "inbox" / "permitted"
PARTIAL_THRESHOLD = 0.7  # a source returning <70% of last month's count is treated as incomplete

CAND_FIELDS = [
    "source_id", "source", "name", "address", "postal_code", "unit", "latitude", "longitude",
    "establishment_type", "cuisine", "website", "halal_claim", "certificate_number",
    "certifying_body", "certificate_expiry", "source_url", "licence",
    "match_status", "directory_id", "match_note", "duplicate_of",
    "first_seen", "last_seen", "missing_runs", "change_note", "record_hash",
    "review_status", "review_note",
]
TRACKED = ["name", "address", "postal_code", "unit", "latitude", "longitude",
           "halal_claim", "certificate_number", "certificate_expiry"]
LOG_FIELDS = ["run_at_sgt", "trigger", "status", "sources", "records_retrieved", "new", "updated",
              "unchanged", "no_longer_found", "duplicates", "needs_review", "directory_issues",
              "errors"]


def now_sgt():
    return dt.datetime.now(ZoneInfo(SGT_TZ))


def is_month_end(day):
    return day.day == calendar.monthrange(day.year, day.month)[1]


def next_month_end(day):
    y, m = day.year, day.month
    if is_month_end(day):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def record_hash(rec):
    blob = json.dumps({k: str(rec.get(k) or "") for k in TRACKED}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def fmt_coord(v):
    try:
        return f"{float(v):.6f}"
    except (TypeError, ValueError):
        return ""


def gather_sources(offline=None):
    """Return {source_name: (records | None, status, note)}."""
    results = {}
    if offline:
        fixture = json.loads(Path(offline).read_text(encoding="utf-8"))
        osm = fixture.get("osm")
        results["osm"] = ([osm_record(e) for e in osm], "ok", "offline fixture") if osm is not None \
            else (None, "failed", "fixture: OpenStreetMap unavailable")
    else:
        try:
            recs = fetch_osm()
            results["osm"] = (recs, "ok", "Overpass API")
        except SourceError as exc:
            results["osm"] = (None, "failed", str(exc))
    permitted, notes = load_permitted(INBOX)
    results["permitted"] = (permitted, "ok" if permitted else "none", " ".join(notes))
    return results


def run(args):
    started = now_sgt()
    today = dt.date.fromisoformat(args.today) if args.today else started.date()
    if not args.force and not is_month_end(today):
        print(f"{today} is not the last day of the month in Singapore; nothing to do.")
        return 0
    STATE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    errors = []

    # 1. Directory health ---------------------------------------------------
    _, directory = read_directory(args.workbook)
    issues = directory_checks(directory, today)

    # 2. Sources ------------------------------------------------------------
    previous = {r["source_id"]: r for r in read_csv(STATE / "candidates.csv")}
    xref = {r["source_id"]: r["directory_id"] for r in read_csv(STATE / "xref.csv")}
    sources = gather_sources(args.offline)
    source_status = {}
    fresh = []
    refreshed_sources = set()
    for name, (recs, status, note) in sources.items():
        if recs is None:
            source_status[name] = f"Failed - {note}"
            errors.append(f"{name}: {note}")
            continue
        prev_count = sum(1 for r in previous.values() if r["source"].split(":")[0] == name.split(":")[0])
        if name == "osm" and prev_count and len(recs) < PARTIAL_THRESHOLD * prev_count:
            source_status[name] = (f"Partial - {len(recs)} records vs {prev_count} last run; "
                                   "previous data kept, nothing marked missing")
            errors.append(f"{name}: suspiciously small extract ({len(recs)} vs {prev_count})")
            continue
        source_status[name] = f"Successful - {len(recs)} records ({note})" if status == "ok" else note
        fresh.extend(recs)
        if status == "ok":
            refreshed_sources.add(name)

    duplicates = dedupe_sources(fresh)

    # 3. Merge into review queue -------------------------------------------
    stamp = today.isoformat()
    queue, counts = {}, {"new": 0, "updated": 0, "unchanged": 0, "no_longer_found": 0}
    for rec in fresh:
        rec = dict(rec)
        rec["latitude"], rec["longitude"] = fmt_coord(rec.get("latitude")), fmt_coord(rec.get("longitude"))
        status, dir_id, note = match_candidate(rec, directory, xref)
        rec.update(match_status=status, directory_id=dir_id or "", match_note=note,
                   duplicate_of=rec.get("duplicate_of", ""), last_seen=stamp, missing_runs="0",
                   record_hash=record_hash(rec))
        old = previous.get(rec["source_id"])
        if old:
            rec["first_seen"] = old.get("first_seen") or stamp
            rec["review_status"] = old.get("review_status") or "pending"
            rec["review_note"] = old.get("review_note", "")
            if old.get("record_hash") != rec["record_hash"]:
                changed = [k for k in TRACKED if str(old.get(k) or "") != str(rec.get(k) or "")]
                rec["change_note"] = f"{stamp}: changed {', '.join(changed)}"
                counts["updated"] += 1
                if rec["review_status"] == "promoted":
                    issues.append({"directory_id": rec["directory_id"], "name": rec["name"],
                                   "issue": "Source record changed",
                                   "detail": f"{rec['source_id']} changed ({', '.join(changed)}) after it was listed"})
            else:
                rec["change_note"] = old.get("change_note", "")
                counts["unchanged"] += 1
        else:
            rec.update(first_seen=stamp, review_status="pending", review_note="",
                       change_note=f"{stamp}: first seen")
            counts["new"] += 1
        if status == "listed" and rec["review_status"] == "pending":
            rec["review_status"] = "already_listed"
        queue[rec["source_id"]] = rec

    for sid, old in previous.items():
        if sid in queue:
            continue
        kept = dict(old)
        src = old["source"].split(":")[0]
        if src in refreshed_sources:
            kept["missing_runs"] = str(int(old.get("missing_runs") or 0) + 1)
            kept["change_note"] = f"{stamp}: not found in latest {src} extract ({kept['missing_runs']} run(s))"
            counts["no_longer_found"] += 1
            if old.get("review_status") == "promoted":
                issues.append({"directory_id": old.get("directory_id"), "name": old.get("name"),
                               "issue": "Source record no longer found",
                               "detail": f"{sid} missing from {src} for {kept['missing_runs']} run(s); "
                                         "verify the listing - it has not been removed"})
        queue[sid] = kept

    rows = sorted(queue.values(), key=lambda r: (r.get("review_status") != "pending", r.get("name", "").lower()))
    needs_review = sum(1 for r in rows if r.get("review_status") == "pending"
                       and r.get("match_status") in ("new", "new_branch", "possible_duplicate"))

    # 4. Outputs ------------------------------------------------------------
    states = [v.split(" - ")[0] for k, v in source_status.items() if k != "permitted"]
    if states and all(s == "Failed" for s in states):
        run_status = "Failed"
    elif errors:
        run_status = "Partial"
    else:
        run_status = "Successful"
    if not args.dry_run:
        write_csv(STATE / "candidates.csv", CAND_FIELDS, rows)
        write_csv(STATE / "directory-issues.csv", ["directory_id", "name", "issue", "detail"], issues)
        log = read_csv(STATE / "sync-log.csv")
        log.append({
            "run_at_sgt": started.strftime("%Y-%m-%d %H:%M"), "trigger": args.trigger, "status": run_status,
            "sources": "; ".join(f"{k}: {v.split(' - ')[0]}" for k, v in source_status.items()),
            "records_retrieved": len(fresh), **counts, "duplicates": duplicates,
            "needs_review": needs_review, "directory_issues": len(issues), "errors": " | ".join(errors),
        })
        write_csv(STATE / "sync-log.csv", LOG_FIELDS, log)
    report = render_report(today, started, directory, issues, source_status, counts, duplicates,
                           needs_review, len(fresh), rows, run_status)
    if not args.dry_run:
        (REPORTS / f"{today:%Y-%m}.md").write_text(report, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    print(report)
    return 0 if run_status != "Failed" else 2


def render_report(today, started, directory, issues, source_status, counts, duplicates,
                  needs_review, retrieved, rows, run_status):
    live = [r for r in directory if str(r.get("Is Demo", "")).lower() not in TRUEISH]
    certified = [r for r in live if str(r.get("Halal Certified", "")).lower() in TRUEISH
                 or str(r.get("Listing Status", "")).lower() == "halal certified"]
    muis = [r for r in certified if "muis" in str(r.get("Certifying Body", "")).lower()]
    selfdecl = [r for r in live if str(r.get("Listing Status", "")).startswith("Self-declared")]
    community = [r for r in live if str(r.get("Listing Status", "")).startswith("Community")]
    by_issue = {}
    for i in issues:
        by_issue.setdefault(i["issue"], []).append(i)
    pending = [r for r in rows if r.get("review_status") == "pending"
               and r.get("match_status") in ("new", "new_branch", "possible_duplicate")]
    out = [
        "# Muslim-Friendly Dining Directory — Monthly Synchronisation Report",
        "",
        f"**Reporting date:** {today:%d %b %Y}  ",
        f"**Run completed:** {started:%d %b %Y, %H:%M} SGT  ",
        f"**Overall status:** {run_status}",
        "",
        "## Directory summary",
        "",
        "| Measure | Count |",
        "|---|---|",
        f"| Total live listings (excluding demo) | {len(live)} |",
        f"| Halal-certified listings (any body) | {len(certified)} |",
        f"| — of which Muis-certified | {len(muis)} |",
        f"| Self-declared Muslim-friendly | {len(selfdecl)} |",
        f"| Community suggested — not verified | {len(community)} |",
        f"| Demo listings | {len(directory) - len(live)} |",
        "",
        "## Changes in candidate sources this month",
        "",
        "| Measure | Count |",
        "|---|---|",
        f"| Source records retrieved | {retrieved} |",
        f"| New records | {counts['new']} |",
        f"| Updated records | {counts['updated']} |",
        f"| Unchanged records | {counts['unchanged']} |",
        f"| No longer found (kept, flagged) | {counts['no_longer_found']} |",
        f"| Cross-source duplicates detected | {duplicates} |",
        f"| Awaiting administrator review | {needs_review} |",
        "",
        "## System status",
        "",
    ]
    out += [f"- **{k}:** {v}" for k, v in source_status.items()]
    out += ["- **Muis portal:** not queried (reuse requires Muis permission)",
            "- **Published workbook:** not modified by this run",
            f"- **Next scheduled run:** {next_month_end(today):%d %b %Y}, 23:00 SGT", "",
            "## Administrative attention required", ""]
    if not by_issue and not pending:
        out.append("None this month.")
    for kind, items in sorted(by_issue.items()):
        out.append(f"**{kind}** ({len(items)})")
        out += [f"- {i['directory_id'] or '—'} {i['name']}: {i['detail']}" for i in items[:25]]
        if len(items) > 25:
            out.append(f"- … {len(items) - 25} more in state/directory-issues.csv")
        out.append("")
    if pending:
        kinds = {}
        for r in pending:
            kinds[r["match_status"]] = kinds.get(r["match_status"], 0) + 1
        out.append(f"**Candidates to review** ({len(pending)}: "
                   + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(kinds.items())) + ")")
        out.append("Review in `_directory-sync/state/candidates.csv`: set review_status to "
                   "`approved` or `rejected`, then run promote.py for approved rows.")
        out.append("")
    out += ["---",
            "Community data © OpenStreetMap contributors, ODbL 1.0. OpenStreetMap halal tags are "
            "community-contributed and are not evidence of Muis certification.", ""]
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workbook", default=str(WORKBOOK))
    p.add_argument("--force", action="store_true", help="run even if today is not month-end")
    p.add_argument("--today", help="override date (YYYY-MM-DD), for testing")
    p.add_argument("--offline", help="JSON fixture instead of network sources")
    p.add_argument("--dry-run", action="store_true", help="print the report without writing files")
    p.add_argument("--trigger", default=os.environ.get("SYNC_TRIGGER", "manual"))
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
