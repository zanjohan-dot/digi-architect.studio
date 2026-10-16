#!/usr/bin/env python3
"""Apply administrator-approved changes to the published directory workbook.

  python _directory-sync/apply.py            # preview: what would change, and what is refused
  python _directory-sync/apply.py --apply    # write the workbook (safe, verified write)

Two inputs, both in _directory-sync/state/:

verifications.csv  - certificate checks. A row with status `approved` that
                     passes every evidence rule either
                       * certifies an existing listing (target = listing ID, e.g. est-004),
                       * creates a certified listing from a candidate (target = source_id), or
                       * creates a certified listing from the certificate (target blank).
candidates.csv     - community suggestions with review_status `approved`
                     become "Community suggested — not verified" listings
                     (OpenStreetMap rows only if settings.json allows OSM publishing).

Nothing marked certified ever comes from OpenStreetMap tags.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dsync import SGT_TZ  # noqa: E402
from dsync.geocode import by_postal  # noqa: E402
from dsync.normalise import norm_name, norm_postal  # noqa: E402
from dsync.verification import VERIFICATION_FIELDS, certified_fields, validate  # noqa: E402
import hashlib  # noqa: E402

from dsync.workbook import (append_records, bump_data_version, create_community_workbook,  # noqa: E402
                            remove_records, update_records)
from sync import (CAND_FIELDS, STATE, WORKBOOK, community_path, load_settings, read_all,  # noqa: E402
                  read_csv, write_csv)

PAGE = HERE.parent / "muslim-friendly-directory.html"
COMMUNITY_DECLARATION = "No declaration has been submitted. Contact the establishment directly."
SCHEME_TYPES = {"restaurant": "Restaurant", "hawker": "Hawker", "snack bar": "Café", "bakery": "Bakery",
                "food court": "Food Court", "caterer": "Caterer", "catering": "Caterer"}


def community_id(source_id):
    """Stable ID for a community listing, independent of row position."""
    return "com-" + hashlib.sha1(source_id.encode()).hexdigest()[:8]


def community_row(c, today):
    claim = {"only": "OpenStreetMap contributors report that this place serves only halal food",
             "yes": "OpenStreetMap contributors report that halal food is available here"}.get(
        c.get("halal_claim"), "Listed from OpenStreetMap community data")
    return {
        "ID": community_id(c["source_id"]),
        "Name": c["name"], "Country": "Singapore", "Address": c["address"] or "",
        "Postal Code": c["postal_code"] or None, "Cuisine": c.get("cuisine") or None,
        "Establishment Type": c.get("establishment_type") or "Other",
        "Latitude": float(c["latitude"]) if c.get("latitude") else None,
        "Longitude": float(c["longitude"]) if c.get("longitude") else None,
        "Website URL": c.get("website") or None,
        "Listing Status": "Community suggested — not verified",
        "Basis of Listing": (f"{claim}. This has not been verified, the establishment has not made a declaration, "
                             "and it is not evidence of halal certification."),
        "Certification Status": "Not verified — community-suggested",
        "Declaration Text Override": COMMUNITY_DECLARATION, "Declaration Text": COMMUNITY_DECLARATION,
        "Additional Notes": ("Source: OpenStreetMap (© OpenStreetMap contributors, ODbL). "
                             f"OSM record last updated {c.get('osm_last_edit') or 'unknown'}."),
        "Last Updated": today, "Is Demo": "FALSE",
    }


def certified_row(v, settings):
    postal = norm_postal(v["postal_code"])
    row = {
        "Name": v["establishment_name"].strip(), "Country": "Singapore", "Address": v["address"].strip(),
        "Postal Code": postal,
        "Establishment Type": SCHEME_TYPES.get((v.get("scheme") or "").strip().lower(), "Restaurant"),
        "Declaration Text": "Halal-certified establishment. Check the certificate displayed at the premises before dining.",
        "Is Demo": "FALSE",
    }
    if settings.get("geocode_with_onemap"):
        coords = by_postal(postal)
        if coords:
            row["Latitude"], row["Longitude"] = coords
    row.update(certified_fields(v))
    return row


def plan(today, settings, directory, candidates, verifications):
    by_id = {r["ID"]: r for r in directory}
    by_key = {(norm_name(r["Name"]), norm_postal(r.get("Postal Code"))): r["ID"] for r in directory}
    cand_by_sid = {c["source_id"]: c for c in candidates}
    updates, new_rows, refused = {}, [], []
    for v in verifications:
        if v.get("status") != "approved":
            continue
        problems = validate(v, today, settings.get("reverify_days", 31))
        target = (v.get("target") or "").strip()
        if not problems and target and target not in by_id and target not in cand_by_sid:
            problems.append(f"target {target} is neither a listing ID nor a candidate source_id")
        if not problems and not target:
            existing = by_key.get((norm_name(v["establishment_name"]), norm_postal(v["postal_code"])))
            if existing:
                problems.append(f"already listed as {existing}; set target to {existing} to certify it")
        if problems:
            refused.append(("verification", v.get("verification_id"), v.get("establishment_name"), problems))
            v["notes"] = "; ".join(problems)
            continue
        if target in by_id and target.startswith("com-"):
            # A verified certificate moves a community listing into the main file.
            v["_move_from"] = target
            new_rows.append(("verification", v, certified_row(v, settings)))
        elif target in by_id:
            updates[target] = certified_fields(v)
            v["_apply"] = ("update", target)
        else:
            new_rows.append(("verification", v, certified_row(v, settings)))
    for c in candidates:
        if c.get("review_status") != "approved":
            continue
        problems = []
        if c.get("match_status") in ("listed", "possible_duplicate") or c.get("duplicate_of"):
            problems.append(f"{c['match_status']} {c.get('duplicate_of', '')} - resolve the duplicate first")
        tier = c.get("quality_tier") or ""
        if tier in ("rejected", "needs_location"):
            problems.append(f"quality check: {tier} ({c.get('quality_notes')})")
        elif tier == "needs_check" and "checked" not in (c.get("review_note") or "").lower():
            problems.append(f"quality check: {c.get('quality_notes')} - confirm it still operates, "
                            "then add 'checked' to review_note")
        if c["source"] == "osm" and not settings.get("osm_publishing_accepted"):
            problems.append("OpenStreetMap publishing is off (settings.json osm_publishing_accepted) - "
                            "decide on ODbL terms first, or invite the establishment to declare")
        if problems:
            refused.append(("candidate", c["source_id"], c["name"], problems))
            continue
        new_rows.append(("candidate", c, community_row(c, today)))
    return updates, new_rows, refused


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="write the workbook (default: preview)")
    p.add_argument("--workbook", default=str(WORKBOOK))
    p.add_argument("--today", help="override date (YYYY-MM-DD), for testing")
    args = p.parse_args()
    today_d = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(ZoneInfo(SGT_TZ)).date()
    today = today_d.isoformat()
    settings = load_settings()
    directory = read_all(args.workbook)
    candidates = read_csv(STATE / "candidates.csv")
    verifications = read_csv(STATE / "verifications.csv")
    updates, new_rows, refused = plan(today_d, settings, directory, candidates, verifications)

    for kind, ref, name, problems in refused:
        print(f"REFUSED  {kind:12} {ref}  {name}")
        for pr in problems:
            print(f"           - {pr}")
    for lid in updates:
        print(f"CERTIFY  {lid}  {next(r['Name'] for r in directory if r['ID'] == lid)}")
    for kind, src, row in new_rows:
        print(f"ADD      {row['Listing Status']:36} {row['Name']} ({row.get('Postal Code') or 'no postal code'})")
    if not args.apply:
        print("\nPreview only. Re-run with --apply to write the workbook.")
        return 0
    if not updates and not new_rows:
        print("Nothing approved to apply.")
        if refused:
            write_csv(STATE / "verifications.csv", VERIFICATION_FIELDS, verifications)
        return 1 if refused else 0

    main_rows = [(k, src, row) for k, src, row in new_rows if k == "verification"]
    comm_rows = [(k, src, row) for k, src, row in new_rows if k == "candidate"]
    comm_path = community_path(args.workbook)
    if updates:
        update_records(args.workbook, updates)
    main_ids = append_records(args.workbook, [row for _, _, row in main_rows]) if main_rows else []
    comm_ids = []
    if comm_rows:
        if not comm_path.exists():
            create_community_workbook(args.workbook, comm_path)
        comm_ids = append_records(comm_path, [dict(row) for _, _, row in comm_rows])
    moved = {src["_move_from"] for _, src, _ in main_rows if src.get("_move_from")}
    if moved:
        remove_records(comm_path, moved)
    ids = main_ids + comm_ids

    xref = read_csv(STATE / "xref.csv")
    for v in verifications:
        if v.get("_apply"):
            v.update(status="applied", applied_on=today, applied_to=v["_apply"][1])
    for (_, src, _), new_id in zip(main_rows, main_ids):
        src.update(status="applied", applied_on=today, applied_to=new_id)
        target = (src.get("target") or "").strip()
        if target and not target.startswith(("est-", "com-")):
            for c in candidates:
                if c["source_id"] == target:
                    c.update(review_status="promoted", directory_id=new_id, match_status="listed")
            xref.append({"source_id": target, "directory_id": new_id, "linked_on": today})
        if src.get("_move_from"):
            for c in candidates:
                if c.get("directory_id") == src["_move_from"]:
                    c["directory_id"] = new_id
            xref = [dict(x, directory_id=new_id) if x["directory_id"] == src["_move_from"] else x for x in xref]
    for (_, src, row), new_id in zip(comm_rows, comm_ids):
        src.update(review_status="promoted", directory_id=new_id, match_status="listed",
                   review_note=(src.get("review_note", "") + f" listed {today} as {new_id}").strip())
        xref.append({"source_id": src["source_id"], "directory_id": new_id, "linked_on": today})
    write_csv(STATE / "verifications.csv", VERIFICATION_FIELDS, verifications)
    write_csv(STATE / "candidates.csv", CAND_FIELDS, candidates)
    write_csv(STATE / "xref.csv", ["source_id", "directory_id", "linked_on"], xref)
    if Path(args.workbook).resolve() == WORKBOOK.resolve():
        bump_data_version(PAGE, today_d.strftime("%Y%m%d"))
    print(f"Applied: {len(updates) + len(main_ids)} certified, {len(comm_ids)} community listing(s) added, "
          f"{len(moved)} moved to certified; {len(refused)} refused.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
