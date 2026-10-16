#!/usr/bin/env python3
"""Add administrator-approved candidates to the published directory workbook.

1. In _directory-sync/state/candidates.csv set review_status to `approved`
   for each record you have checked (add a note in review_note if useful).
2. Run:  python _directory-sync/promote.py            (preview only)
         python _directory-sync/promote.py --apply    (writes the workbook)

How records are listed:
* OpenStreetMap records become "Community suggested — not verified" with no
  certification claim. OSM halal tags are never treated as certification.
* Records from a permitted dataset with a certificate number become
  "Halal certified", Certifying Body as supplied, with the certificate
  expiry where provided.
* possible_duplicate rows are refused; resolve them first (reject, or
  record the directory ID they belong to in state/xref.csv).
"""
import argparse
import csv
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dsync import SGT_TZ  # noqa: E402
from dsync.workbook import append_records  # noqa: E402
from sync import CAND_FIELDS, STATE, WORKBOOK, read_csv, write_csv  # noqa: E402

COMMUNITY_DECLARATION = "No declaration has been submitted. Contact the establishment directly."


def to_row(c, today):
    certified = bool(c.get("certificate_number")) and c["source"].startswith("permitted")
    row = {
        "Name": c["name"],
        "Country": "Singapore",
        "Address": c["address"] or "",
        "Postal Code": c["postal_code"] or None,
        "Cuisine": c.get("cuisine") or None,
        "Establishment Type": c.get("establishment_type") or "Other",
        "Latitude": float(c["latitude"]) if c.get("latitude") else None,
        "Longitude": float(c["longitude"]) if c.get("longitude") else None,
        "Website URL": c.get("website") or None,
        "Last Updated": today,
        "Is Demo": "FALSE",
    }
    if certified:
        row.update({
            "Listing Status": "Halal certified",
            "Basis of Listing": f"Halal certificate {c['certificate_number']} verified against {c['source'].split(':', 1)[1]} "
                                f"on {today}.",
            "Halal Certified": "TRUE",
            "Certification Status": f"Halal-certified ({c.get('certifying_body') or 'Muis (Singapore)'})",
            "Certifying Body": c.get("certifying_body") or "Muis (Singapore)",
            "Certificate Expiry": c.get("certificate_expiry") or None,
            "Declaration Text": "Halal-certified establishment. Verify the displayed certificate before dining.",
        })
    else:
        row.update({
            "Listing Status": "Community suggested — not verified",
            "Basis of Listing": "Community-sourced listing (OpenStreetMap). Declaration not yet submitted.",
            "Certification Status": "Certification status not stated",
            "Declaration Text Override": COMMUNITY_DECLARATION,
            "Declaration Text": COMMUNITY_DECLARATION,
            "Additional Notes": "Location data © OpenStreetMap contributors (ODbL). Pending declaration.",
        })
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="write the workbook (default: preview)")
    p.add_argument("--workbook", default=str(WORKBOOK))
    args = p.parse_args()
    today = dt.datetime.now(ZoneInfo(SGT_TZ)).date().isoformat()
    rows = read_csv(STATE / "candidates.csv")
    approved = [r for r in rows if r.get("review_status") == "approved"]
    refused = [r for r in approved if r.get("match_status") in ("listed", "possible_duplicate") or r.get("duplicate_of")]
    ready = [r for r in approved if r not in refused and r.get("name")]
    for r in refused:
        print(f"REFUSED  {r['source_id']}  {r['name']}: {r['match_status']} {r.get('duplicate_of', '')} - resolve first")
    for r in ready:
        print(f"READY    {r['source_id']}  {r['name']} ({r.get('postal_code') or 'no postal code'})")
    if not ready:
        print("Nothing approved to add.")
        return 0
    if not args.apply:
        print(f"\nPreview only. Re-run with --apply to add {len(ready)} listing(s).")
        return 0
    ids = append_records(args.workbook, args.workbook, [to_row(r, today) for r in ready])
    xref = read_csv(STATE / "xref.csv")
    for r, new_id in zip(ready, ids):
        r.update(review_status="promoted", directory_id=new_id, match_status="listed",
                 review_note=(r.get("review_note") + " " if r.get("review_note") else "") + f"listed {today} as {new_id}")
        xref.append({"source_id": r["source_id"], "directory_id": new_id, "linked_on": today})
    write_csv(STATE / "candidates.csv", CAND_FIELDS, rows)
    write_csv(STATE / "xref.csv", ["source_id", "directory_id", "linked_on"], xref)
    print(f"Added {len(ids)} listing(s): {', '.join(ids)}. Commit data/ and _directory-sync/state/ to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
