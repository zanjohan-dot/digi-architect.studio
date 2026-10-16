"""Matching, de-duplication and directory health checks."""
import datetime as dt

from .normalise import brand_key, metres_between, norm_name, norm_postal, similarity, unit_from

TRUEISH = {"true", "yes", "1"}


def _directory_key(rec):
    return norm_name(rec.get("Name")), norm_postal(rec.get("Postal Code"))


def match_candidate(cand, directory, xref):
    """Classify one source record against the directory.

    Returns (status, directory_id, note). Status is one of:
      listed             - already in the directory (exact key or cross-reference)
      possible_duplicate - close enough that an administrator must decide
      new_branch         - same brand, different location (kept separate)
      new                - not in the directory
    """
    sid = cand["source_id"]
    if sid in xref:
        return "listed", xref[sid], "matched by saved cross-reference"
    cname, cpostal = norm_name(cand["name"]), cand.get("postal_code", "")
    cunit = cand.get("unit", "")
    best = None
    for rec in directory:
        dname, dpostal = _directory_key(rec)
        dunit = unit_from(rec.get("Address"))
        if cpostal and dpostal == cpostal and dname == cname:
            if not (cunit and dunit and cunit != dunit):
                return "listed", rec.get("ID"), "same name and postal code"
        sim = similarity(cand["name"], rec.get("Name"))
        dist = metres_between(cand.get("latitude"), cand.get("longitude"),
                              rec.get("Latitude"), rec.get("Longitude"))
        same_place = (cpostal and cpostal == dpostal) or (dist is not None and dist <= 30)
        if same_place and sim >= 0.75:
            score = sim + (0.1 if cpostal == dpostal else 0)
            if not best or score > best[0]:
                best = (score, rec.get("ID"), f"similar name ({sim:.2f}) at the same location")
    if best:
        return "possible_duplicate", best[1], best[2]
    bk = brand_key(cand["name"])
    if bk and len(bk) >= 4:
        for rec in directory:
            if brand_key(rec.get("Name")) == bk:
                return "new_branch", rec.get("ID"), f"other branch of {rec.get('Name')} already listed"
    return "new", "", ""


def dedupe_sources(cands):
    """Flag candidate records that describe the same outlet in two sources.

    Records from different sources at the same postal code (+unit) with very
    similar names are linked; the one with a certificate number wins.
    Branches (same brand, different postal codes) are never merged.
    """
    groups = {}
    for c in cands:
        key = (c.get("postal_code") or f"{c.get('latitude')},{c.get('longitude')}", c.get("unit") or "")
        groups.setdefault(key, []).append(c)
    dupes = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda c: (not c.get("certificate_number"), c["source"]))
        lead = members[0]
        for other in members[1:]:
            if similarity(lead["name"], other["name"]) >= 0.85:
                other["duplicate_of"] = lead["source_id"]
                dupes += 1
    # Same name within 50 m (e.g. a node and a building outline for one outlet).
    by_name = {}
    for c in cands:
        if not c.get("duplicate_of"):
            by_name.setdefault(norm_name(c["name"]), []).append(c)
    for name, members in by_name.items():
        if not name or len(members) < 2:
            continue
        members.sort(key=lambda c: (not c.get("postal_code"), not c.get("address"), c["source_id"]))
        for i, lead in enumerate(members):
            if lead.get("duplicate_of"):
                continue
            for other in members[i + 1:]:
                if other.get("duplicate_of"):
                    continue
                d = metres_between(lead.get("latitude"), lead.get("longitude"),
                                   other.get("latitude"), other.get("longitude"))
                if d is not None and d <= 50:
                    other["duplicate_of"] = lead["source_id"]
                    dupes += 1
    return dupes


def _date(value):
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(str(value).strip()[:11], fmt).date()
        except ValueError:
            continue
    return None


def directory_checks(directory, today, reverify_days=31, expiry_warning_days=30):
    """Issues an administrator must look at. Nothing is changed automatically."""
    issues = []

    def add(rec, kind, detail):
        issues.append({"directory_id": rec.get("ID"), "name": rec.get("Name"), "issue": kind, "detail": detail})

    seen = {}
    for rec in directory:
        if str(rec.get("Is Demo", "")).lower() in TRUEISH:
            continue
        name, postal = _directory_key(rec)
        # Without a postal code, compare name + address so separate branches are not flagged.
        key = (name, postal or "addr:" + norm_name(rec.get("Address")))
        if name and key in seen:
            add(rec, "Duplicate record", f"Same name and postal code as {seen[key]}")
        seen.setdefault(key, rec.get("ID"))

        completeness = rec.get("Data Completeness")
        if completeness and completeness != "Complete":
            add(rec, "Incomplete record", completeness)
        if rec.get("Country") == "Singapore" and not norm_postal(rec.get("Postal Code")):
            add(rec, "Incomplete record", "Missing or invalid Singapore postal code")

        certified = str(rec.get("Halal Certified", "")).lower() in TRUEISH or \
            str(rec.get("Listing Status", "")).lower() == "halal certified"
        if not certified:
            continue
        if not rec.get("Certifying Body"):
            add(rec, "Certification evidence missing", "Shown as halal certified but no certifying body recorded")
        expiry = _date(rec.get("Certificate Expiry"))
        if not expiry:
            add(rec, "Certification evidence missing", "No certificate expiry recorded")
        elif expiry < today:
            add(rec, "Certificate expired", f"Expired {expiry.isoformat()} - suspend the certified status until renewal is verified")
        elif (expiry - today).days <= expiry_warning_days:
            add(rec, "Certificate expiring", f"Expires {expiry.isoformat()} - obtain renewed certificate")
        updated = _date(rec.get("Last Updated"))
        if not updated or (today - updated).days > reverify_days:
            add(rec, "Re-verification due",
                f"Certified listing last verified {updated.isoformat() if updated else 'never'}; re-check against the establishment's certificate")
    return issues
