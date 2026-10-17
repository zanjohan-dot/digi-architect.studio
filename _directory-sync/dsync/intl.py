"""Country-aware helpers for listings outside Singapore (Malaysia, Japan).

Singapore code paths are untouched: everything here is used only for new
countries. Key differences from Singapore:
  * names may be Japanese (kanji / kana) or Malay, so name keys keep CJK text
  * postcodes are 5 digits (Malaysia) or 7 digits, NNN-NNNN (Japan)
  * there is no OneMap; the town comes from addr:city or the nearest
    OpenStreetMap city/town node
  * diet:halal=limited means only some dishes are halal ("selected items")
"""
import math
import re
import unicodedata

from .normalise import metres_between, similarity

COUNTRIES = {
    "MY": {"name": "Malaysia", "bounds": (0.8, 7.5, 99.5, 119.5), "postal": re.compile(r"^\d{5}$")},
    "JP": {"name": "Japan", "bounds": (24.0, 46.0, 122.5, 146.0), "postal": re.compile(r"^\d{3}-\d{4}$")},
}

# Halal scope reported by OpenStreetMap contributors. Never a certification.
SCOPE = {
    "only": "Entire menu reported halal (community report)",
    "yes": "Halal food reported available (community report)",
    "limited": "Selected halal items only (community report)",
    "cuisine": "Halal cuisine reported (community report)",
}

_CJK = r"぀-ヿ㐀-䶿一-鿿豈-﫿"


def name_key(value):
    """Matching key that keeps Japanese text (norm_name would drop it)."""
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).lower()
    s = re.sub(rf"[^a-z0-9{_CJK}]+", " ", s)
    s = re.sub(r"\b(halal|restaurant|restoran|cafe|kedai makan|sdn bhd|the)\b", " ", s)
    s = re.sub(r"(店|本店|ハラール|ハラル)$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def has_cjk(value):
    return bool(re.search(f"[{_CJK}]", value or ""))


def norm_postal_intl(value, cc):
    if not value:
        return ""
    digits = re.sub(r"\D", "", unicodedata.normalize("NFKC", str(value)))
    if cc == "MY" and len(digits) == 5:
        return digits
    if cc == "JP" and len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return ""


def address_for(tags, cc):
    """Readable street address from OSM addr:* tags (no postcode, no state)."""
    if tags.get("addr:full"):
        return tags["addr:full"].strip()
    if cc == "JP":
        parts = [tags.get("addr:city"), tags.get("addr:suburb"), tags.get("addr:quarter"),
                 tags.get("addr:neighbourhood"),
                 "-".join(x for x in (tags.get("addr:block_number"), tags.get("addr:housenumber")) if x)]
        building = tags.get("addr:housename") or tags.get("addr:place")
        s = " ".join(p for p in parts if p)
        return ", ".join(x for x in (s, building) if x)
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    unit = tags.get("addr:unit") or ""
    building = tags.get("addr:housename") or tags.get("addr:place") or ""
    return ", ".join(x for x in (f"No. {unit}" if unit else "", street, building, tags.get("addr:city") or "") if x)


def names_for(tags, cc):
    """(display name, local-language name)."""
    local = tags.get("name") or ""
    if cc == "JP":
        en = tags.get("name:en") or tags.get("name:ja-Latn") or tags.get("name:ja_rm") or ""
        ja = tags.get("name:ja") or (local if has_cjk(local) else "")
        display = en or local
        return display, (ja if ja and ja != display else "")
    en = tags.get("name:en") or ""
    ms = tags.get("name:ms") or ""          # only an explicitly tagged Malay name
    display = en or local
    return display, (ms if ms and ms != display else "")


class TownIndex:
    """Nearest city/town node lookup on a coarse grid."""

    def __init__(self, places, cell=0.5):
        self.cell = cell
        self.grid = {}
        for p in places:
            if p.get("name"):
                self.grid.setdefault(self._k(p["lat"], p["lon"]), []).append(p)

    def _k(self, lat, lon):
        return (math.floor(lat / self.cell), math.floor(lon / self.cell))

    def nearest(self, lat, lon, max_km=25):
        if lat is None or lon is None:
            return None
        ky, kx = self._k(lat, lon)
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for p in self.grid.get((ky + dy, kx + dx), []):
                    d = metres_between(lat, lon, p["lat"], p["lon"])
                    # a city outranks a town that is only slightly closer
                    score = d * (0.7 if p.get("place") == "city" else 1.0)
                    if d is not None and d <= max_km * 1000 and (best is None or score < best[0]):
                        best = (score, p)
        return best[1] if best else None


def dedupe_intl(cands):
    """Mark records that describe the same outlet (node + building, or two spellings).

    Same name key within 60 m, or very similar romanised names within 30 m.
    Different branches of a chain are kept apart because they are further apart.
    """
    dupes = 0
    by_cell = {}
    for c in cands:
        if c.get("latitude") is None:
            continue
        by_cell.setdefault((round(c["latitude"], 2), round(c["longitude"], 2)), []).append(c)
    for c in cands:
        if c.get("duplicate_of") or c.get("latitude") is None:
            continue
        keys = {k for k in (name_key(c["name"]), name_key(c.get("local_name"))) if k}
        cy, cx = round(c["latitude"], 2), round(c["longitude"], 2)
        for dy in (-0.01, 0, 0.01):
            for dx in (-0.01, 0, 0.01):
                for o in by_cell.get((round(cy + dy, 2), round(cx + dx, 2)), []):
                    if o is c or o.get("duplicate_of") or o["source_id"] > c["source_id"]:
                        continue
                    d = metres_between(c["latitude"], c["longitude"], o["latitude"], o["longitude"])
                    if d is None or d > 60:
                        continue
                    okeys = {k for k in (name_key(o["name"]), name_key(o.get("local_name"))) if k}
                    if keys & okeys or (d <= 30 and similarity(c["name"], o["name"]) >= 0.85):
                        c["duplicate_of"] = o["source_id"]
                        dupes += 1
                        break
                if c.get("duplicate_of"):
                    break
            if c.get("duplicate_of"):
                break
    return dupes
