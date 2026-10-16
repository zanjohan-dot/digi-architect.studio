"""Candidate sources.

Only sources whose terms permit reuse are fetched automatically:

* OpenStreetMap (Open Database Licence 1.0). Places tagged diet:halal=yes/only
  or cuisine=halal inside Singapore. These tags are community contributions
  and are NOT evidence of Muis certification.
* Permitted datasets dropped into inbox/permitted/ (for example a dataset
  Muis has licensed to you, or a commercially licensed equivalent). The
  loader refuses to read a file unless a provenance record states the
  permission it was obtained under.

The Muis halal portal itself is never queried by this package.
"""
import csv
import json
import time
from pathlib import Path

import requests

from .normalise import norm_postal, unit_from

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "digi-architect.studio directory maintenance (admin@digi-architect.studio)"

OSM_QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="SG"][admin_level=2]->.sg;
(
  nwr["diet:halal"~"^(yes|only)$"](area.sg);
  nwr["cuisine"~"(^|;)halal(;|$)"](area.sg);
);
out tags center;
"""

AMENITY_TO_TYPE = {
    "restaurant": "Restaurant",
    "cafe": "Café",
    "fast_food": "Restaurant",
    "food_court": "Food Court",
    "bar": "Bar & Grill",
    "pub": "Bar & Grill",
    "ice_cream": "Café",
}
SHOP_TO_TYPE = {"bakery": "Bakery", "pastry": "Bakery", "confectionery": "Bakery"}


class SourceError(RuntimeError):
    pass


def fetch_osm(retries=3, backoff=20, session=None):
    """Return a list of normalised candidate dicts from OpenStreetMap."""
    session = session or requests.Session()
    last = None
    for attempt in range(retries):
        for url in OVERPASS_ENDPOINTS:
            try:
                resp = session.post(
                    url,
                    data={"data": OSM_QUERY},
                    headers={"User-Agent": USER_AGENT},
                    timeout=180,
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    if "elements" not in payload:
                        raise SourceError("Overpass response had no elements key")
                    if payload.get("remark") and "error" in payload["remark"].lower():
                        raise SourceError("Overpass reported: " + payload["remark"][:200])
                    return [osm_record(e) for e in payload["elements"]]
                last = f"{url} HTTP {resp.status_code}"
            except (requests.RequestException, ValueError, SourceError) as exc:
                last = f"{url}: {exc}"
        time.sleep(backoff * (attempt + 1))
    raise SourceError(f"OpenStreetMap fetch failed after {retries} attempts ({last})")


def osm_record(el):
    tags = el.get("tags", {}) or {}
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    unit = tags.get("addr:unit") or tags.get("addr:door") or ""
    building = tags.get("addr:place") or tags.get("addr:housename") or ""
    postal = norm_postal(tags.get("addr:postcode"))
    parts = [street, f"#{unit}" if unit and not unit.startswith("#") else unit, building]
    address = ", ".join(p for p in parts if p)
    etype = AMENITY_TO_TYPE.get(tags.get("amenity")) or SHOP_TO_TYPE.get(tags.get("shop")) or "Other"
    cuisine = ", ".join(
        c.replace("_", " ").title() for c in (tags.get("cuisine") or "").split(";") if c and c != "halal"
    )
    return {
        "source": "osm",
        "source_id": f"osm:{el.get('type')}/{el.get('id')}",
        "name": tags.get("name:en") or tags.get("name") or "",
        "address": address,
        "postal_code": postal,
        "unit": unit_from(unit) or unit_from(address),
        "latitude": lat,
        "longitude": lon,
        "establishment_type": etype,
        "cuisine": cuisine,
        "website": tags.get("website") or tags.get("contact:website") or "",
        "halal_claim": tags.get("diet:halal") or ("cuisine" if "halal" in (tags.get("cuisine") or "") else ""),
        "certificate_number": "",
        "certifying_body": "",
        "certificate_expiry": "",
        "source_url": f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
        "licence": "ODbL-1.0 (© OpenStreetMap contributors)",
        "raw": json.dumps(tags, ensure_ascii=False, sort_keys=True),
    }


# ---------------------------------------------------------------------------
# Permitted datasets
# ---------------------------------------------------------------------------

PERMITTED_COLUMNS = {
    # canonical field   : accepted column headers (case-insensitive)
    "name": ["establishment_name", "name", "establishment name"],
    "establishment_type": ["establishment_type", "type", "scheme", "category"],
    "certificate_number": ["certificate_number", "cert_no", "certificate no", "certificate number"],
    "address": ["address", "full_address"],
    "postal_code": ["postal_code", "postal code", "postcode"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon"],
    "certificate_expiry": ["certificate_expiry", "expiry", "expiry_date", "valid_until"],
    "certifying_body": ["certifying_body", "certifying body"],
    "source_url": ["source_url", "url"],
}

# Muis establishment types seen on the public portal mapped to the
# directory's Establishment Type list.
MUIS_TYPE_MAP = {
    "restaurant": "Restaurant",
    "hawker": "Hawker",
    "snack bar": "Café",
    "bakery": "Bakery",
    "food court": "Food Court",
    "caterer": "Caterer",
    "catering": "Caterer",
    "canteen": "Food Court",
}


def _provenance(folder):
    prov = folder / "PROVENANCE.md"
    if not prov.exists():
        return None
    text = prov.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.lower().startswith("permission:") and line.split(":", 1)[1].strip():
            return line.split(":", 1)[1].strip()
    return None


def load_permitted(folder):
    """Load every CSV in inbox/permitted/. Returns (records, notes)."""
    folder = Path(folder)
    files = sorted(folder.glob("*.csv"))
    if not files:
        return [], ["No permitted dataset supplied this month."]
    permission = _provenance(folder)
    if not permission:
        return [], [
            f"{len(files)} file(s) in inbox/permitted/ were NOT read: PROVENANCE.md with a "
            "'Permission:' line is required before any third-party dataset is imported."
        ]
    records, notes = [], [f"Permitted datasets read under: {permission}"]
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            lookup = {h.strip().lower(): h for h in reader.fieldnames or []}
            colmap = {}
            for field, options in PERMITTED_COLUMNS.items():
                for opt in options:
                    if opt in lookup:
                        colmap[field] = lookup[opt]
                        break
            if "name" not in colmap or "postal_code" not in colmap:
                notes.append(f"{path.name}: skipped, needs at least name and postal code columns.")
                continue
            n = 0
            for i, row in enumerate(reader, start=2):
                get = lambda f: (row.get(colmap[f]) or "").strip() if f in colmap else ""
                if not get("name"):
                    continue
                etype_raw = get("establishment_type")
                body = get("certifying_body") or ("Muis (Singapore)" if get("certificate_number") else "")
                records.append({
                    "source": f"permitted:{path.stem}",
                    "source_id": f"permitted:{path.stem}:{get('certificate_number') or i}",
                    "name": get("name"),
                    "address": get("address"),
                    "postal_code": norm_postal(get("postal_code")),
                    "unit": unit_from(get("address")),
                    "latitude": get("latitude") or None,
                    "longitude": get("longitude") or None,
                    "establishment_type": MUIS_TYPE_MAP.get(etype_raw.lower(), etype_raw or "Other"),
                    "cuisine": "",
                    "website": "",
                    "halal_claim": "certificate" if get("certificate_number") else "",
                    "certificate_number": get("certificate_number"),
                    "certifying_body": body,
                    "certificate_expiry": get("certificate_expiry"),
                    "source_url": get("source_url"),
                    "licence": permission,
                    "raw": json.dumps(row, ensure_ascii=False, sort_keys=True),
                })
                n += 1
            notes.append(f"{path.name}: {n} records loaded.")
    return records, notes
