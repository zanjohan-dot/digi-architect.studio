"""Build reviewable and publishable data for Malaysia and Japan.

Reads   _directory-sync/research/osm-<CC>.json.gz      OpenStreetMap extract (research_osm.py)
        _directory-sync/research/records-<cc>.csv      desk-researched establishments, one row each,
                                                       with evidence kept by source type
        _directory-sync/research/chain-evidence-my.csv operator / JAKIM statements about chains
        _directory-sync/research/jakim-outlets-my.csv  chain outlets looked up on the JAKIM premises register
        _directory-sync/publication.json               which evidence tiers may go live (owner-approved)
Writes  _directory-sync/state/candidates-<cc>.csv      every OSM candidate, graded
        _directory-sync/state/prepared-<cc>.csv        every record, its evidence tier and readiness
        _directory-sync/research/coverage-<cc>.csv     per state / prefecture research log
        data/community-listings-<cc>.xlsx              OSM-derived listings allowed by publication.json (ODbL)
        data/directory-<cc>.xlsx                       researched listings allowed by publication.json
                                                       (with --write-data)

Evidence tiers, never merged into one "verified" flag:
  certified               certification confirmed with the certifying body / official register
  certification_reported  certification claimed by the establishment, its operator, a tourism body or the press
  self_declared           the establishment's own published declaration, or a tourism-body listing
                          based on information the establishment supplied
  community               OpenStreetMap community report only
An OpenStreetMap halal tag is never treated as certification, ownership or a declaration;
a chain's statement is never treated as confirmation for an individual outlet.
"""
import argparse
import csv
import datetime as dt
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dsync.intl import (COUNTRIES, SCOPE, TownIndex, address_for, dedupe_intl,  # noqa: E402
                        has_cjk, names_for, norm_postal_intl)
from dsync.quality import DINING_AMENITIES, DINING_SHOPS, FRESH_YEARS, SURVEY_FRESH_YEARS, is_venue  # noqa: E402
from dsync.sources import AMENITY_TO_TYPE, SHOP_TO_TYPE, lifecycle  # noqa: E402

ROOT = HERE.parent
RESEARCH = HERE / "research"
STATE = HERE / "state"

CAND_FIELDS = ["source_id", "country", "state", "city", "city_basis", "name", "local_name", "address",
               "local_address", "address_basis",
               "postal_code", "latitude", "longitude", "establishment_type", "cuisine", "halal_claim",
               "halal_scope", "certification_claim", "website", "opening_hours", "osm_last_edit",
               "check_date", "lifecycle", "place_kind", "duplicate_of", "quality_tier", "quality_notes",
               "source_url", "review_status", "review_note"]

NEW_COLUMNS = ["Local Name", "Local Address", "State / Prefecture", "City", "Halal Scope", "Muslim-Owned",
               "Opening Hours", "Source URL", "Last Verified", "Verification Notes",
               "Listed By", "Certification Claimed By", "Establishment Declaration", "Certifier Confirmation",
               "Tourism Listing", "OpenStreetMap Report", "Not Yet Verified", "Evidence Sources",
               "Pork Served On Premises", "Cooking Alcohol In Halal Items", "Advance Reservation Required"]
PUBLICATION = HERE / "publication.json"
PREP_FIELDS = ["id", "source", "country", "state", "city", "name", "local_name", "address", "tier",
               "public_label", "readiness", "blocking_issues", "certification_status", "establishment_declaration",
               "tourism_listing", "listed_by", "certifier", "latest_evidence_date", "date_checked",
               "unresolved", "evidence_sources", "notes"]

NOT_OPEN = re.compile(r"opening soon|coming soon|under construction|temporarily closed|\btutup\b|akan dibuka|閉店|休業|準備中|近日オープン", re.I)

PORK_HINT = re.compile(r"\bpork\b|\bbabi\b|bak ?kut ?teh|char ?siew|char ?siu|siu ?yuk|\bbacon\b|\bham\b|tonkatsu|\bbuta\b|豚|とんかつ|トンカツ|豬|猪肉|叉烧|叉燒|肉骨茶", re.I)

COMMUNITY_DECLARATION = "No declaration has been submitted. Contact the establishment directly."


def years_since(text, today):
    try:
        return (today - dt.date.fromisoformat(str(text)[:10])).days / 365.25
    except ValueError:
        return None


GEOCODE = HERE / "research" / "geocode-cache.json"


def load_geocode():
    return json.loads(GEOCODE.read_text(encoding="utf-8")) if GEOCODE.exists() else {}


COUNCIL = re.compile(r"^(Majlis (Bandaraya|Perbandaran|Daerah) )|\s+(City|Municipal|District|Town) Council$|^(Dewan Bandaraya) ", re.I)


def _town(a):
    t = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    return COUNCIL.sub("", t).strip()


def _compose(a, cc):
    """Readable address from a reverse-geocoder result (no state, no postcode)."""
    if cc == "JP":
        parts = [a.get("neighbourhood"), a.get("quarter"), a.get("suburb"), a.get("city_district"), _town(a)]
    else:
        street = " ".join(x for x in (a.get("house_number"), a.get("road")) if x)
        parts = [street, a.get("neighbourhood") or a.get("suburb"), _town(a)]
    out = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return ", ".join(out)


def record(el, cc, state, towns, geo=None):
    tags = el.get("tags") or {}
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    name, local = names_for(tags, cc)
    g = (geo or {}).get(f"osm:{el['type']}/{el['id']}", {})
    en, ja = g.get("en") or {}, g.get("ja") or {}
    city, basis = tags.get("addr:city") or "", "address"
    if city and cc == "JP" and has_cjk(city) and _town(en):
        city, basis = _town(en), "map position"          # keep town names in English
    if not city and _town(en):
        city, basis = _town(en), "map position"
    if not city:
        t = towns.nearest(lat, lon)
        city, basis = (t["name"], "nearest town") if t else ("", "")
    address, address_basis = address_for(tags, cc), "OpenStreetMap address tags"
    if cc == "JP" and has_cjk(address) and _compose(en, cc):
        address, address_basis = _compose(en, cc), "map position (OpenStreetMap reverse geocoding)"
    if not address and _compose(en, cc):
        address, address_basis = _compose(en, cc), "map position (OpenStreetMap reverse geocoding)"
    local_address = ""
    if cc == "JP":
        local_address = tags.get("addr:full") if has_cjk(tags.get("addr:full") or "") else ""
        if not local_address and ja:
            local_address = "".join(x for x in (ja.get("province"), _town(ja), ja.get("city_district"), ja.get("suburb"),
                                                 ja.get("quarter"), ja.get("neighbourhood")) if x)
    postal = norm_postal_intl(tags.get("addr:postcode"), cc) or norm_postal_intl(en.get("postcode"), cc)
    claim = tags.get("diet:halal") or ("cuisine" if "halal" in (tags.get("cuisine") or "") else "")
    cert = " ".join(f"{k}={v}" for k, v in tags.items()
                    if "halal" in k and ("cert" in k or "operator" in k or "authority" in k))
    kind = (f"amenity={tags['amenity']}" if tags.get("amenity") else
            f"shop={tags['shop']}" if tags.get("shop") else "")
    return {
        "source_id": f"osm:{el['type']}/{el['id']}", "country": COUNTRIES[cc]["name"], "state": state,
        "city": city, "city_basis": basis, "name": name, "local_name": local,
        "address": address, "local_address": local_address, "address_basis": address_basis,
        "postal_code": postal,
        "latitude": lat, "longitude": lon,
        "establishment_type": AMENITY_TO_TYPE.get(tags.get("amenity")) or SHOP_TO_TYPE.get(tags.get("shop")) or "Other",
        "cuisine": ", ".join(c.replace("_", " ").title() for c in (tags.get("cuisine") or "").split(";")
                             if c and c != "halal"),
        "halal_claim": claim, "halal_scope": SCOPE.get(claim, ""), "certification_claim": cert,
        "website": tags.get("website") or tags.get("contact:website") or "",
        "opening_hours": tags.get("opening_hours") or "",
        "osm_last_edit": (el.get("timestamp") or "")[:10],
        "check_date": (tags.get("check_date") or tags.get("survey:date") or "")[:10],
        "lifecycle": lifecycle(tags), "place_kind": kind, "duplicate_of": "",
        "conflict": "diet:non-halal=" + tags["diet:non-halal"]
                    if claim and tags.get("diet:non-halal") in ("yes", "only") else "",
        "source_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
    }


def grade(rec, cc, today):
    """Same tiers and freshness rules as Singapore (dsync.quality), with country bounds/postcodes."""
    notes = []
    if not rec["name"].strip():
        return "rejected", "no name"
    kind = rec["place_kind"]
    if kind:
        key, _, value = kind.partition("=")
        if not ((key == "amenity" and value in DINING_AMENITIES) or (key == "shop" and value in DINING_SHOPS)):
            return "rejected", f"not a dining establishment ({kind})"
    if rec["lifecycle"]:
        return "rejected", f"reported closed ({rec['lifecycle']})"
    pork = PORK_HINT.search(f"{rec['name']} {rec.get('local_name') or ''} {rec.get('cuisine') or ''}")
    if pork:
        return "needs_check", f"name or cuisine suggests pork ({pork.group(0).strip()}); check before listing"
    if rec.get("conflict"):
        return "needs_check", f"contradictory tags ({rec['conflict']} alongside a halal tag); check before listing"
    status_word = NOT_OPEN.search(f"{rec['name']} {rec.get('local_name') or ''}")
    if status_word:
        return "needs_check", f"name suggests it is not open ({status_word.group(0).strip()})"
    b = COUNTRIES[cc]["bounds"]
    if rec["latitude"] is None or not (b[0] <= rec["latitude"] <= b[1] and b[2] <= rec["longitude"] <= b[3]):
        return "rejected", "no coordinates or outside the country"
    if rec["duplicate_of"]:
        return "needs_check", f"possible duplicate of {rec['duplicate_of']}"
    if not rec["address"] and not rec["postal_code"]:
        notes.append("no address; located by map position only")
    elif rec.get("address_basis", "").startswith("map position"):
        notes.append("address derived from map position")
    if not rec["postal_code"]:
        notes.append("no postcode")
    if rec["halal_claim"] == "limited":
        notes.append("only selected dishes reported halal")
    age, survey = years_since(rec["osm_last_edit"], today), years_since(rec["check_date"], today)
    fresh = (age is not None and age <= FRESH_YEARS) or (survey is not None and survey <= SURVEY_FRESH_YEARS)
    if not fresh:
        return "needs_check", "; ".join(notes + [f"not updated in OpenStreetMap since {rec['osm_last_edit'] or 'unknown'}"])
    return "publishable", "; ".join(notes)


def load_chains():
    path = RESEARCH / "chain-evidence-my.csv"
    if not path.exists():
        return []
    return [dict(r, _re=re.compile(r["pattern"], re.I)) for r in csv.DictReader(path.open(encoding="utf-8"))]


def chain_for(c, chains):
    for ch in chains:
        if ch["_re"].search(c["name"]):
            return ch
    return None


def apply_chain(c, chains):
    """Chain statements: 'reported' adds an operator claim (outlet not confirmed);
    'contradicted' / 'not_certified' hold the halal tag back for checking."""
    ch = chain_for(c, chains)
    c["chain"] = ch
    if not ch or c["quality_tier"] == "rejected":
        return
    if ch["status"] in ("contradicted", "not_certified"):
        c["quality_tier"] = "needs_check"
        c["quality_notes"] = "; ".join(x for x in (c["quality_notes"], f"{ch['chain']}: {ch['statement']}") if x)


RESEARCH_FIELDS = None


def load_research(cc):
    path = RESEARCH / f"records-{cc.lower()}.csv"
    if not path.exists():
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def supersede(cands, research):
    """An OSM candidate already covered by a researched record is not listed twice."""
    from dsync.intl import name_key
    from dsync.normalise import metres_between
    by_osm = {r["osm_source_id"]: r for r in research if r.get("osm_source_id")}
    n = 0
    for c in cands:
        r = by_osm.get(c["source_id"])
        if r is None:
            for x in research:
                same = name_key(x["name"]) and name_key(x["name"]) in (name_key(c["name"]), name_key(c.get("local_name")))
                if not same or x["state"] != c["state"]:
                    continue
                try:
                    near = metres_between(float(x["latitude"]), float(x["longitude"]), c["latitude"], c["longitude"]) <= 150
                except (TypeError, ValueError):
                    near = x["city"] and x["city"] == c["city"]
                if near:
                    r = x
                    break
        if r is not None:
            c["superseded_by"] = r["id"]
            n += 1
    return n


def load_publication():
    if PUBLICATION.exists():
        return json.loads(PUBLICATION.read_text(encoding="utf-8"))
    return {}


def listing_row(c, today, community_id):
    venue = is_venue({"place_kind": c["place_kind"], "establishment_type": c["establishment_type"], "name": c["name"]})
    if venue:
        claim = ("OpenStreetMap contributors report that halal food is available at this food court or "
                 "food centre. This does not mean every stall is halal: check each stall's own certificate "
                 "or declaration")
    else:
        claim = {"only": "OpenStreetMap contributors report that this place serves only halal food",
                 "yes": "OpenStreetMap contributors report that halal food is available here",
                 "limited": "OpenStreetMap contributors report that some dishes here are halal; the rest of "
                            "the menu and the kitchen may not be",
                 "cuisine": "OpenStreetMap contributors list this place's cuisine as halal"}.get(
            c["halal_claim"], "Listed from OpenStreetMap community data")
    area = c["city"] if c["city"] else c["state"]
    notes = [f"Source: OpenStreetMap (© OpenStreetMap contributors, ODbL). OSM record last updated "
             f"{c['osm_last_edit'] or 'unknown'}."]
    if c["city_basis"] == "nearest town":
        notes.append(f"Town shown is the nearest town on the map ({c['city']}).")
    if c.get("address_basis", "").startswith("map position"):
        notes.append("Address derived from the map position; confirm before visiting.")
    if c["certification_claim"]:
        notes.append("OpenStreetMap also carries a certification note that has not been checked.")
    return {
        "ID": community_id(c["source_id"]), "Name": c["name"], "Country": c["country"],
        "Address": c["address"] or f"{c['city']}, {c['state']}".strip(", "),
        "Postal Code": c["postal_code"] or None,
        "Area / Prefecture Override": f"{area}, {c['state']}" if area != c["state"] else c["state"],
        "Area / Prefecture": f"{area}, {c['state']}" if area != c["state"] else c["state"],
        "Cuisine": c["cuisine"] or None, "Establishment Type": c["establishment_type"],
        "Latitude": float(c["latitude"]), "Longitude": float(c["longitude"]),
        "Listing Status": "Community suggested — not verified",
        "Basis of Listing": f"{claim}. This has not been verified, the establishment has not made a declaration, "
                            "and it is not evidence of halal certification.",
        "Certification Status": "Not verified — community-suggested",
        "Declaration Text Override": COMMUNITY_DECLARATION, "Declaration Text": COMMUNITY_DECLARATION,
        "Additional Notes": " ".join(notes), "Website URL": c["website"] or None,
        "Last Updated": today.isoformat(), "Is Demo": "FALSE",
        "Local Name": c["local_name"] or None, "Local Address": c.get("local_address") or None,
        "State / Prefecture": c["state"], "City": c["city"] or None,
        "Halal Scope": c["halal_scope"] or None, "Muslim-Owned": "Unknown",
        "Opening Hours": c["opening_hours"] or None, "Source URL": c["source_url"],
        "Last Verified": None,
        "Verification Notes": "Halal status, certification, ownership and alcohol use not verified. " + (c["quality_notes"] or ""),
        "OpenStreetMap Report": f"{claim} (OpenStreetMap, last edited {c['osm_last_edit'] or 'unknown'}).",
        "Not Yet Verified": "Halal status, certification, ownership, pork and alcohol policy",
        "Evidence Sources": c["source_url"],
    }


def chain_row(row, ch):
    """Outlet of a chain whose operator states JAKIM certification: reported, not confirmed for this outlet."""
    row.update({
        "Listing Status": "Certification reported — not confirmed",
        "Certification Status": f"Reported by the operator ({ch['certifier']}, chain-level); this outlet is not confirmed with {ch['certifier']}",
        "Certification Claimed By": f"{ch['certifier']} (chain-level statement by {ch['chain']})",
        "Establishment Declaration": ch["statement"],
        "Not Yet Verified": f"This outlet's own {ch['certifier']} certificate; ownership; alcohol policy",
        "Evidence Sources": " | ".join(x for x in (ch["source_url"], row["Source URL"]) if x),
        "Basis of Listing": (f"{ch['chain']} states that the chain is halal-certified by {ch['certifier']}. This outlet "
                             f"has not been confirmed individually with {ch['certifier']}. Also reported on OpenStreetMap."),
        "Last Verified": ch["checked"],
    })
    return row


JAKIM_REGISTER = "https://myehalal.halal.gov.my/portal-halal/v1/index.php?data=ZGlyZWN0b3J5L2luZGV4X2RpcmVjdG9yeTs7Ozs="


def load_jakim():
    """Outlet-level JAKIM register lookups. Only 'confirmed' rows (same chain, same postcode, one register
    premises, not shared with another mapped outlet) count as certification; 'review' and 'not_found' do not."""
    path = RESEARCH / "jakim-outlets-my.csv"
    if not path.exists():
        return {}
    return {r["community_id"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}


def certified_row(row, ch, j):
    """Chain outlet found on the JAKIM premises register with a valid expiry on the date checked."""
    row.update({
        "Listing Status": "Halal Certified", "Halal Certified": "TRUE", "Certifying Body": "JAKIM",
        "Certification Status": f"Certified by JAKIM (premises register, valid to {j['expiry']})",
        "Certifier Confirmation": (f"Listed on the JAKIM halal premises register as \"{j['register_premises']}\", "
                                   f"certificate valid to {j['expiry']} (checked {j['date_checked']}; matched by chain and postcode)"),
        "Certification Claimed By": None,
        "Establishment Declaration": ch["statement"],
        "Basis of Listing": (f"This outlet matches a {ch['chain']} premises on the JAKIM halal register "
                             f"(\"{j['register_premises']}\", valid to {j['expiry']}), checked {j['date_checked']}. "
                             "Location from OpenStreetMap."),
        "Not Yet Verified": "Ownership; whether the register premises and this map location are the same unit should be confirmed on site",
        "Evidence Sources": " | ".join(x for x in (JAKIM_REGISTER, ch["source_url"], row["Source URL"]) if x),
        "Last Verified": j["date_checked"],
    })
    return row


YESNO = {"Yes": "TRUE", "No": "FALSE"}
SCOPE_TEXT = {"entire": "Entire menu stated halal / Muslim-friendly",
              "selected": "Selected halal menu only (the rest of the menu may not be halal)",
              "muslim_friendly": "Muslim-friendly practices stated (no halal claim)",
              "muslim_friendly_no_halal_claim": "Muslim-friendly practices stated (no halal claim)"}


def research_tier(r):
    if r["cert_status"] == "confirmed":
        return "certified"
    if r["cert_status"] == "reported":
        return "certification_reported"
    if r["establishment_declaration"] or r["tourism_listing"]:
        return "self_declared"
    return "community" if r["openstreetmap_report"] else "unsupported"


# Publication criteria (see research/PUBLICATION-CRITERIA.md). A record is recommended only when all hold:
#  C1 identity and location: a street address from an official or primary source
#  C2 evidence of a halal / Muslim-friendly practice from the certifier, the establishment itself, or a
#     tourism body publishing information the establishment supplied
#  C3 currency: latest evidence no older than EVIDENCE_MAX_AGE_YEARS
#  C4 no unresolved contradiction, closure, or "no halal claim" finding
#  C5 the public label is derived from the strongest supported evidence only (see public_label)
EVIDENCE_MAX_AGE_YEARS = 3
CONTRADICTION = re.compile(r"conflict|contradict|buffet listed pork|no halal (claim|text|mention)|does not mention halal|"
                           r"marks .halal-certified meat. as not available|stated not certified", re.I)


def research_readiness(r, today):
    issues = []
    if not (r["address"] or r["local_address"]):
        issues.append("C1: no confirmed street address")
    if r["operating_status"] == "closed":
        issues.append("C4: reported closed")
    tier = research_tier(r)
    if tier == "unsupported":
        issues.append("C2: evidence is only a third-party mention (news, university or community guide)")
    d = (r["latest_source_date"] or "")[:7]
    try:
        y, m = int(d[:4]), int(d[5:7] or 6)
        age = (today.year - y) + (today.month - m) / 12
        if age > EVIDENCE_MAX_AGE_YEARS:
            issues.append(f"C3: latest evidence {r['latest_source_date']} is older than {EVIDENCE_MAX_AGE_YEARS} years")
    except ValueError:
        issues.append("C3: evidence date unknown")
    if CONTRADICTION.search(r["notes"] or ""):
        issues.append("C4: sources conflict or a source makes no halal claim; check before listing")
    if re.search(r"vegetarian|vegan", r["notes"] or "", re.I) and r["halal_scope"] in ("", "unknown"):
        issues.append("C4: vegetarian/vegan venue without a halal or Muslim-friendly claim")
    if not r.get("latitude"):
        issues.append("map position pending (not blocking)")
    blocking = [i for i in issues if not i.endswith("(not blocking)")]
    return ("ready" if not blocking else "needs_check"), issues


def public_label(r):
    """Public-facing classification, strongest supported evidence first; never 'certified' without confirmation."""
    tier = research_tier(r)
    parts = []
    if tier == "certified":
        parts.append(f"Halal-certified ({r['certifier']}, confirmed)")
    elif tier == "certification_reported":
        parts.append("Certification reported — not confirmed")
    elif tier == "self_declared":
        parts.append("Self-declared Muslim-friendly" if r["establishment_declaration"] else
                     f"Muslim-friendly — listed by {r['listed_by'] or 'a tourism body'} (establishment-reported)")
    else:
        parts.append("Community-suggested — not verified")
    if r["halal_scope"] == "selected":
        parts.append("selected halal menu only")
    elif r["halal_scope"] in ("muslim_friendly", "muslim_friendly_no_halal_claim"):
        parts.append("Muslim-friendly options, no halal claim")
    if r["muslim_owned"] == "Yes":
        parts.append("Muslim-owned (as reported)")
    return "; ".join(parts)


def research_row(r, today):
    tier = research_tier(r)
    status = {"certified": "Halal Certified", "certification_reported": "Certification reported — not confirmed",
              "self_declared": "Self-declared Muslim-friendly"}.get(tier, "Community suggested — not verified")
    scope = SCOPE_TEXT.get(r["halal_scope"], "")
    basis = []
    if r["certifier_confirmation"]:
        basis.append(r["certifier_confirmation"] + ".")
    if r["cert_status"] == "reported":
        basis.append(f"Certification is reported (claimed certifier: {r['certifier']}) but has not been confirmed with the certifying body.")
    if r["establishment_declaration"]:
        basis.append("The establishment states: " + r["establishment_declaration"].rstrip(".") + ".")
    if r["tourism_listing"]:
        basis.append(r["tourism_listing"])
    area = r["city"] or r["state"]
    try:
        lat, lon = float(r["latitude"]), float(r["longitude"])
    except (TypeError, ValueError):
        lat = lon = None
    return {
        "ID": r["id"], "Name": r["name"], "Country": r["country"],
        "Address": r["address"] or r["local_address"] or f"{r['city']}, {r['state']}".strip(", "),
        "Postal Code": r["postal_code"] or None,
        "Area / Prefecture Override": f"{area}, {r['state']}" if area != r["state"] else r["state"],
        "Area / Prefecture": f"{area}, {r['state']}" if area != r["state"] else r["state"],
        "Cuisine": r["cuisine"] or None, "Establishment Type": r["establishment_type"] or "Restaurant",
        "Latitude": lat, "Longitude": lon,
        "Listing Status": status, "Basis of Listing": " ".join(basis) or None,
        "Halal Certified": "TRUE" if tier == "certified" else None,
        "Certification Status": {"certified": f"Certified by {r['certifier']}",
                                 "certification_reported": "Reported — not confirmed with the certifying body"}.get(tier, "Not halal-certified (no certification found)"),
        "Certifying Body": r["certifier"] if tier == "certified" else None,
        "Alcohol Served": YESNO.get(r["alcohol_served"]),
        "Shared Kitchen": {"Yes": "FALSE", "No": "TRUE"}.get(r["separate_kitchen_or_utensils"]),
        "No Pork Declared": "TRUE" if r["pork_served_on_premises"] == "No" else None,
        "Prayer Space": YESNO.get(r["prayer_space"]),
        "Declaration Text Override": r["establishment_declaration"] or None,
        "Declaration Text": r["establishment_declaration"] or "No declaration has been submitted to this directory. Contact the establishment directly.",
        "Additional Notes": r["notes"] or None, "Website URL": r["website"] or None,
        "Last Updated": today.isoformat(), "Is Demo": "FALSE",
        "Local Name": r["local_name"] or None, "Local Address": r["local_address"] or None,
        "State / Prefecture": r["state"], "City": r["city"] or None, "Halal Scope": scope or None,
        "Muslim-Owned": "Yes (source cited)" if r["muslim_owned"] == "Yes" else "Unknown",
        "Source URL": (r["sources"].split(" | ") or [""])[0] or None, "Last Verified": r["last_checked"],
        "Verification Notes": ("Not yet verified: " + r["not_yet_verified"]) if r["not_yet_verified"] else None,
        "Listed By": r["listed_by"] or None,
        "Certification Claimed By": r["certifier"] if tier == "certification_reported" else None,
        "Establishment Declaration": r["establishment_declaration"] or None,
        "Certifier Confirmation": r["certifier_confirmation"] or None,
        "Tourism Listing": r["tourism_listing"] or None,
        "OpenStreetMap Report": r["openstreetmap_report"] or None,
        "Not Yet Verified": r["not_yet_verified"] or None,
        "Evidence Sources": r["sources"] or None,
        "Pork Served On Premises": YESNO.get(r["pork_served_on_premises"]),
        "Cooking Alcohol In Halal Items": YESNO.get(r["cooking_alcohol_in_halal_items"]),
        "Advance Reservation Required": YESNO.get(r["advance_reservation_required"]),
    }


RESEARCH_LICENCE = [["Licence and sources"],
                    ["Compiled by The Digital Systems Architect (Zan J Private Limited) from the public sources cited "
                     "in each record's Evidence Sources column. Each record states what was declared, by whom, and "
                     "what has not been verified."],
                    ["Map positions in Japan are from the Geospatial Information Authority of Japan address search "
                     "(出典：国土地理院) where shown."]]


def write_workbook(path, rows, template, licence=None):
    import openpyxl
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from dsync.workbook import ODBL_NOTICE
    src = openpyxl.load_workbook(template, read_only=True)
    header = [c.value for c in next(src.worksheets[0].iter_rows(max_row=1))] + NEW_COLUMNS
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Establishments"
    ws.append(header)
    for r in rows:
        ws.append([r.get(h) for h in header])
    last = openpyxl.utils.get_column_letter(len(header))
    t = Table(displayName="tblEstablishments", ref=f"A1:{last}{max(2, len(rows) + 1)}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)
    lic = wb.create_sheet("Licence")
    for row in (licence or ODBL_NOTICE):
        lic.append(row)
    lic.append(["Country", rows[0]["Country"] if rows else ""])
    wb.save(path)


def build(cc, today, write_data):
    from apply import community_id
    data = json.load(gzip.open(RESEARCH / f"osm-{cc}.json.gz", "rt", encoding="utf-8"))
    towns = TownIndex(data["places"])
    geo = load_geocode()
    cands, coverage = [], []
    for code, area in data["areas"].items():
        for el in area["elements"]:
            cands.append(dict(record(el, cc, area["name"], towns, geo), _area=code))
    dupes = dedupe_intl(cands)
    chains = load_chains() if cc == "MY" else []
    jakim = load_jakim() if cc == "MY" else {}
    for c in cands:
        c["quality_tier"], c["quality_notes"] = grade(c, cc, today)
        apply_chain(c, chains)
    research = load_research(cc)
    covered = supersede(cands, research)
    for code, area in data["areas"].items():
        mine = [c for c in cands if c["_area"] == code]
        tiers = {t: sum(1 for c in mine if c["quality_tier"] == t)
                 for t in ("publishable", "needs_check", "rejected")}
        coverage.append({
            "country": COUNTRIES[cc]["name"], "code": code, "state_or_prefecture": area["name"],
            "osm_eating_places": area["eating_places"], "halal_tagged_records": area["halal_tagged"],
            "duplicates": sum(1 for c in mine if c["duplicate_of"]),
            "closed_or_not_dining": sum(1 for c in mine if c["quality_tier"] == "rejected"),
            "selected_items_only": sum(1 for c in mine if c["halal_claim"] == "limited"),
            "entire_menu_reported": sum(1 for c in mine if c["halal_claim"] == "only"),
            "certification_note_in_osm": sum(1 for c in mine if c["certification_claim"]),
            "needs_check": tiers["needs_check"], "ready_for_publication": tiers["publishable"],
            "towns": len({c["city"] for c in mine if c["quality_tier"] == "publishable" and c["city"]}),
        })
    with open(STATE / f"candidates-{cc.lower()}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAND_FIELDS, extrasaction="ignore")
        w.writeheader()
        for c in sorted(cands, key=lambda c: (c["state"], c["city"], c["name"])):
            w.writerow({**c, "review_status": "approved" if c["quality_tier"] == "publishable" else ""})
    with open(RESEARCH / f"coverage-{cc.lower()}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(coverage[0]))
        w.writeheader()
        w.writerows(coverage)
    gate = load_publication().get(cc, {})
    prepared, rows, rrows = [], [], []
    for c in cands:
        if c["quality_tier"] == "rejected" or c.get("superseded_by"):
            continue
        row = listing_row(c, today, community_id)
        ch = c.get("chain")
        tier, label, cert, checked = "community", "Community-suggested — not verified", "none found", ""
        j = jakim.get(row["ID"]) if ch and ch["status"] == "reported" else None
        if j and j["register_status"] == "confirmed" and j["expiry"] >= today.isoformat():
            certified_row(row, ch, j)
            tier, label, checked = "certified", "Halal-certified (JAKIM, confirmed)", j["date_checked"]
            cert = f"confirmed on JAKIM register as {j['register_premises']}, valid to {j['expiry']}"
        elif ch and ch["status"] == "reported":
            chain_row(row, ch)
            tier, label, checked = "certification_reported", "Certification reported — not confirmed", ch["checked"]
            cert = f"chain-level claim ({ch['certifier']}); outlet " + (
                f"register lookup: {j['register_status']} ({j['note']})" if j else "not looked up")
        ready = c["quality_tier"] == "publishable"
        issues = [] if ready else [c["quality_notes"]]
        if tier == "community":
            issues.append("community report only (not verified)")
        if tier == "certification_reported":
            issues.append("C2: outlet not confirmed on the certifier's register")
        prepared.append({"id": row["ID"], "source": "openstreetmap", "country": c["country"], "state": c["state"],
                         "city": c["city"], "name": c["name"], "local_name": c["local_name"], "address": c["address"],
                         "tier": tier, "public_label": label,
                         "readiness": "ready" if ready and tier == "certified" else "needs_check",
                         "blocking_issues": "; ".join(i for i in issues if i), "certification_status": cert,
                         "establishment_declaration": ch["statement"] if ch and tier != "community" else "",
                         "tourism_listing": "", "listed_by": "",
                         "certifier": ch["certifier"] if ch and tier != "community" else "",
                         "latest_evidence_date": c["osm_last_edit"], "date_checked": checked,
                         "unresolved": row["Not Yet Verified"],
                         "evidence_sources": row["Evidence Sources"], "notes": c["quality_notes"]})
        if ready and tier != "community" and tier != "certification_reported" and gate.get(tier):
            rows.append(row)
        elif ready and tier == "community" and gate.get(tier):
            rows.append(row)
    for r in research:
        tier = research_tier(r)
        readiness, issues = research_readiness(r, today)
        prepared.append({"id": r["id"], "source": "desk research", "country": r["country"], "state": r["state"],
                         "city": r["city"], "name": r["name"], "local_name": r["local_name"],
                         "address": r["address"] or r["local_address"], "tier": tier, "public_label": public_label(r),
                         "readiness": readiness, "blocking_issues": "; ".join(issues),
                         "certification_status": {"certified": "confirmed with certifier",
                                                  "certification_reported": f"reported, not confirmed ({r['certifier']})"}.get(tier, "none found"),
                         "establishment_declaration": r["establishment_declaration"], "tourism_listing": r["tourism_listing"],
                         "listed_by": r["listed_by"], "certifier": r["certifier"],
                         "latest_evidence_date": r["latest_source_date"], "date_checked": r["last_checked"],
                         "unresolved": r["not_yet_verified"],
                         "evidence_sources": r["sources"], "notes": r["notes"][:400]})
        if readiness == "ready" and gate.get(tier):
            rrows.append(research_row(r, today))
    ids = [r["ID"] for r in rows + rrows]
    assert len(ids) == len(set(ids)), "duplicate IDs"
    with open(STATE / f"prepared-{cc.lower()}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PREP_FIELDS)
        w.writeheader()
        w.writerows(sorted(prepared, key=lambda p: (p["state"], p["city"], p["name"])))
    if write_data:
        key = lambda r: (r["State / Prefecture"], r["City"] or "", r["Name"])
        write_workbook(ROOT / "data" / f"community-listings-{cc.lower()}.xlsx", sorted(rows, key=key),
                       ROOT / "data" / "community-listings.xlsx")
        write_workbook(ROOT / "data" / f"directory-{cc.lower()}.xlsx", sorted(rrows, key=key),
                       ROOT / "data" / "community-listings.xlsx", licence=RESEARCH_LICENCE)
    from collections import Counter
    tiers = Counter((p["tier"], p["readiness"]) for p in prepared)
    print(f"{cc}: {len(cands)} OSM candidates ({dupes} duplicates, {covered} matched to researched records), "
          f"{len(research)} researched records; prepared by tier/readiness: {dict(sorted(tiers.items()))}; "
          f"published under publication.json: {len(rows)} community + {len(rrows)} researched")
    return cands, rows + rrows, coverage


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("countries", nargs="*", default=["MY", "JP"])
    ap.add_argument("--write-data", action="store_true")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    a = ap.parse_args()
    for cc in a.countries:
        build(cc, dt.date.fromisoformat(a.today), a.write_data)
