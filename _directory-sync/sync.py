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
from dsync.match import dedupe_sources, directory_checks, match_candidate, TRUEISH, _date  # noqa: E402
from dsync.sources import SourceError, fetch_osm, load_permitted, osm_record  # noqa: E402
from dsync.verification import VERIFICATION_FIELDS, personal_data_flags, suspended_fields  # noqa: E402
from dsync.workbook import WorkbookError, bump_data_version, read_directory, update_records  # noqa: E402

REPO = HERE.parent
WORKBOOK = REPO / "data" / "muslim-friendly-establishments.xlsx"
PAGE = REPO / "muslim-friendly-directory.html"
STATE = HERE / "state"
PRIVATE = STATE / "private"   # git-ignored: never committed to the public repository
REPORTS = HERE / "reports"
INBOX = HERE / "inbox" / "permitted"
PARTIAL_THRESHOLD = 0.7  # a source returning <70% of last month's count is treated as incomplete
DEFAULT_SETTINGS = {"osm_publishing_accepted": False, "suspend_expired_certificates": True,
                    "geocode_with_onemap": True, "reverify_days": 31, "expiry_warning_days": 30}


def load_settings():
    path = HERE / "settings.json"
    settings = dict(DEFAULT_SETTINGS)
    if path.exists():
        settings.update({k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items()
                         if not k.startswith("_")})
    return settings

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


def late_start_date(started, override):
    """GitHub sometimes starts scheduled jobs late. If the 23:00 month-end job
    starts after midnight (before 06:00 SGT on the 1st) and last month has no
    run logged yet, run it for last month's final day instead of skipping."""
    if override or started.day != 1 or started.hour >= 6:
        return None
    last_day = started.date() - dt.timedelta(days=1)
    month = f"{last_day:%Y-%m}"
    if any(r.get("run_at_sgt", "").startswith(month) and r.get("status") != "Failed"
           for r in read_csv(STATE / "sync-log.csv")):
        return None
    return last_day


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
    try:
        fetch_permitted_from_secret()
    except SourceError as exc:
        results["permitted"] = (None, "failed", str(exc))
        return results, False
    permitted, notes, publishable = load_permitted(INBOX)
    results["permitted"] = (permitted, "ok" if permitted else "none", " ".join(notes))
    return results, publishable


def fetch_permitted_from_secret():
    """In GitHub Actions, a licensed dataset can be supplied without committing it.

    PERMITTED_DATASET_URL (secret): HTTPS link to the CSV.
    PERMITTED_PROVENANCE (secret): the text of PROVENANCE.md.
    Both are written into the git-ignored inbox for this run only.
    """
    url, prov = os.environ.get("PERMITTED_DATASET_URL"), os.environ.get("PERMITTED_PROVENANCE")
    if not url or not prov:
        return
    import requests
    INBOX.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Never echo the URL: it is a secret and this message reaches committed files.
        raise SourceError(f"licensed feed download failed ({type(exc).__name__})") from None
    (INBOX / "licensed-feed.csv").write_bytes(resp.content)
    (INBOX / "PROVENANCE.md").write_text(prov, encoding="utf-8")


def privacy_scan(verifications, candidates):
    """Flag free-text fields in committed files that look like personal data.

    The detail names the field only, never the matched text.
    """
    found = []
    for v in verifications:
        for f in ("evidence_ref", "verified_by", "notes"):
            for flag in personal_data_flags(v.get(f)):
                found.append({"directory_id": v.get("applied_to", ""), "name": v.get("establishment_name", ""),
                              "issue": "Possible personal data in a public file",
                              "detail": f"verifications.csv {v.get('verification_id')} {f} {flag}; edit it out"})
    for c in candidates:
        for flag in personal_data_flags(c.get("review_note")):
            found.append({"directory_id": c.get("directory_id", ""), "name": c.get("name", ""),
                          "issue": "Possible personal data in a public file",
                          "detail": f"candidates.csv {c['source_id']} review_note {flag}; edit it out"})
    return found


def suspend_expired(args, directory, today, errors):
    """Withdraw certified status from listings whose recorded certificate has expired."""
    expired = {}
    for rec in directory:
        certified = str(rec.get("Halal Certified", "")).lower() in TRUEISH or \
            str(rec.get("Listing Status", "")).lower() == "halal certified"
        expiry = _date(rec.get("Certificate Expiry"))
        if certified and expiry and expiry < today and str(rec.get("Is Demo", "")).lower() not in TRUEISH:
            expired[rec["ID"]] = suspended_fields(rec, today)
    if not expired or args.dry_run:
        return list(expired)
    try:
        update_records(args.workbook, expired)
        if Path(args.workbook).resolve() == WORKBOOK.resolve():
            bump_data_version(PAGE, today.strftime("%Y%m%d"))
        return list(expired)
    except (WorkbookError, OSError) as exc:
        errors.append(f"Could not withdraw expired certifications ({exc}); workbook left unchanged")
        return []


def run(args):
    started = now_sgt()
    today = dt.date.fromisoformat(args.today) if args.today else started.date()
    if not args.force and not args.today and is_month_end(today) and started.hour < 6:
        print("This is the previous day's scheduled job starting late; the month-end run happens at 23:00 tonight.")
        return 0
    if not args.force and not is_month_end(today):
        late = late_start_date(started, args.today)
        if not late:
            print(f"{today} is not the last day of the month in Singapore; nothing to do.")
            return 0
        print(f"Scheduled job started late ({started:%d %b %H:%M} SGT); running for {late:%d %b %Y}.")
        today = late
    STATE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    errors = []

    # 1. Directory health ---------------------------------------------------
    _, directory = read_directory(args.workbook)
    issues = directory_checks(directory, today, settings["reverify_days"], settings["expiry_warning_days"])
    suspended = suspend_expired(args, directory, today, errors) if settings["suspend_expired_certificates"] else []
    for lid in suspended:
        issues.append({"directory_id": lid, "name": next(r["Name"] for r in directory if r["ID"] == lid),
                       "issue": "Certified status withdrawn",
                       "detail": "Certificate expired; listing set to Pending verification until renewal is verified"
                                 + (" (dry run: not written)" if args.dry_run else "")})
    verifications = read_csv(STATE / "verifications.csv")
    if not (STATE / "verifications.csv").exists() and not args.dry_run:
        write_csv(STATE / "verifications.csv", VERIFICATION_FIELDS, [])
    issues.extend(privacy_scan(verifications, read_csv(STATE / "candidates.csv")))

    # 2. Sources ------------------------------------------------------------
    previous = {r["source_id"]: r for r in read_csv(STATE / "candidates.csv")}
    previous.update({r["source_id"]: r for r in read_csv(PRIVATE / "candidates-permitted.csv")})
    xref = {r["source_id"]: r["directory_id"] for r in read_csv(STATE / "xref.csv")}
    sources, permitted_publishable = gather_sources(args.offline)
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
    private = [r for r in rows if r.get("source", "").startswith("permitted") and not permitted_publishable]
    private_ids = {r["source_id"] for r in private}
    public = []
    for r in rows:
        if r["source_id"] in private_ids:
            continue
        if r.get("duplicate_of") in private_ids:  # never leak a private identifier into a public file
            r = dict(r, duplicate_of="licensed record (held privately)")
        public.append(r)
    if not args.dry_run:
        write_csv(STATE / "candidates.csv", CAND_FIELDS, public)
        if private or (PRIVATE / "candidates-permitted.csv").exists():
            write_csv(PRIVATE / "candidates-permitted.csv", CAND_FIELDS, private)
        write_csv(STATE / "directory-issues.csv", ["directory_id", "name", "issue", "detail"], issues)
        log = read_csv(STATE / "sync-log.csv")
        log.append({
            "run_at_sgt": started.strftime("%Y-%m-%d %H:%M"), "trigger": args.trigger, "status": run_status,
            "sources": "; ".join(f"{k}: {v.split(' - ')[0]}" for k, v in source_status.items()),
            "records_retrieved": len(fresh), **counts, "duplicates": duplicates,
            "needs_review": needs_review, "directory_issues": len(issues), "errors": " | ".join(errors),
        })
        write_csv(STATE / "sync-log.csv", LOG_FIELDS, log)
    if suspended and not args.dry_run:
        _, directory = read_directory(args.workbook)
    report = render_report(today, started, directory, issues, source_status, counts, duplicates,
                           needs_review, len(fresh), rows, run_status, verifications, len(private), settings)
    if not args.dry_run:
        (REPORTS / f"{today:%Y-%m}.md").write_text(report, encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS"):
        for e in errors:
            print(f"::error title=Directory sync::{e}".replace("\n", " "))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    print(report)
    return 0 if run_status != "Failed" else 2


def render_report(today, started, directory, issues, source_status, counts, duplicates,
                  needs_review, retrieved, rows, run_status, verifications=(), private_count=0, settings=None):
    settings = settings or DEFAULT_SETTINGS
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
        f"| Licensed records held privately (not published) | {private_count} |",
        "",
        "## Certification verification",
        "",
        "| Measure | Count |",
        "|---|---|",
        f"| Draft checks in progress | {sum(1 for v in verifications if v.get('status') in ('', 'draft'))} |",
        f"| Approved, awaiting apply | {sum(1 for v in verifications if v.get('status') == 'approved')} |",
        f"| Applied this month | {sum(1 for v in verifications if v.get('status') == 'applied' and str(v.get('applied_on', '')).startswith(f'{today:%Y-%m}'))} |",
        f"| Applied to date | {sum(1 for v in verifications if v.get('status') == 'applied')} |",
        "",
        "## System status",
        "",
    ]
    out += [f"- **{k}:** {v}" for k, v in source_status.items()]
    out += ["- **Muis portal:** not queried (reuse requires Muis permission)",
            ("- **Published workbook:** expired certified claims withdrawn (see below)"
             if any(i["issue"] == "Certified status withdrawn" for i in issues)
             else "- **Published workbook:** not modified by this run"),
            f"- **OpenStreetMap publishing:** {'enabled' if settings.get('osm_publishing_accepted') else 'off (candidates used as leads only)'}",
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
                   "`approved` or `rejected`, then run the `apply` action.")
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
