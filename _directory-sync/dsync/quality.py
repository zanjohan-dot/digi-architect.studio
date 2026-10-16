"""Grade candidate records before anyone considers publishing them.

Tiers (first match wins):
  rejected        - no name, not a dining establishment, or marked closed in OSM
  needs_location  - no street address and no postal code (a diner could not find it)
  needs_check     - not edited or surveyed in OSM for a long time; may have closed
  publishable     - named dining establishment with a findable address, recently maintained

Grading only describes the data. It never says anything about halal status:
community records stay "Community suggested — not verified" whatever their tier.
"""
import datetime as dt
import re

DINING_AMENITIES = {"restaurant", "cafe", "fast_food", "food_court", "ice_cream", "canteen"}
DINING_SHOPS = {"bakery", "pastry", "confectionery"}
SG_BOUNDS = (1.15, 1.48, 103.60, 104.10)   # lat min/max, lon min/max
VALID_POSTAL_PREFIXES = {f"{i:02d}" for i in range(1, 83)} - {"74"}
VENUE = re.compile(r"hawker|food ?court|food ?centre|food ?center|kopitiam|coffee ?shop|kedai kopi|canteen|food ?street|food ?fair", re.I)
FRESH_YEARS = 4          # last edit within 4 years counts as maintained
SURVEY_FRESH_YEARS = 2   # or an explicit check/survey date within 2 years


def _years_since(date_text, today):
    try:
        d = dt.date.fromisoformat(str(date_text)[:10])
    except ValueError:
        return None
    return (today - d).days / 365.25


def grade(rec, today):
    """Return (tier, notes)."""
    notes = []
    if not (rec.get("name") or "").strip():
        return "rejected", "no name"
    kind = rec.get("place_kind") or ""
    if kind:
        key, _, value = kind.partition("=")
        dining = (key == "amenity" and value in DINING_AMENITIES) or (key == "shop" and value in DINING_SHOPS)
        if not dining:
            return "rejected", f"not a dining establishment ({kind})"
    if rec.get("lifecycle"):
        return "rejected", f"reported closed ({rec['lifecycle']})"
    try:
        lat, lon = float(rec.get("latitude")), float(rec.get("longitude"))
        if not (SG_BOUNDS[0] <= lat <= SG_BOUNDS[1] and SG_BOUNDS[2] <= lon <= SG_BOUNDS[3]):
            return "rejected", "coordinates outside Singapore"
    except (TypeError, ValueError):
        notes.append("no coordinates")
    postal = rec.get("postal_code") or ""
    if postal and postal[:2] not in VALID_POSTAL_PREFIXES:
        return "needs_check", f"postal code {postal} is not a valid Singapore postal code"
    street = re.sub(r"#\S+", "", rec.get("address") or "")
    if not re.search(r"[A-Za-z]{3,}", street) and not postal:
        return "needs_location", "no street address or postal code"
    if rec.get("duplicate_of"):
        return "needs_check", f"possible duplicate of {rec['duplicate_of']}"
    if not postal:
        notes.append("no postal code")
    age = _years_since(rec.get("osm_last_edit"), today)
    survey = _years_since(rec.get("check_date"), today)
    fresh = (age is not None and age <= FRESH_YEARS) or (survey is not None and survey <= SURVEY_FRESH_YEARS)
    if not fresh:
        when = rec.get("osm_last_edit") or "unknown"
        return "needs_check", "; ".join(notes + [f"not updated in OSM since {when}"])
    return "publishable", "; ".join(notes)


def is_venue(rec):
    """Hawker centres, food courts and coffee shops: halal tags describe some stalls, not the venue."""
    return (rec.get("place_kind") == "amenity=food_court" or rec.get("establishment_type") == "Food Court"
            or bool(VENUE.search(rec.get("name") or "")))
