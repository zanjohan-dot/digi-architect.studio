"""OneMap (Singapore Land Authority) lookups.

* by_postal(): coordinates for a postal code (used for verified listings).
* postal_for_address(): a postal code for a street address, accepted only when
  OneMap returns the same block number and road, within 200 m of the listing's
  own coordinates, and all matching results agree on one postal code.

OneMap data is provided under the Singapore Open Data Licence v1.0, which
requires attribution (see ONEMAP_ATTRIBUTION). If ONEMAP_TOKEN is set it is
sent; the search endpoint currently works without one.
"""
import os
import re
import time

import requests

from .normalise import metres_between

SEARCH = "https://www.onemap.gov.sg/api/common/elastic/search"
ONEMAP_ATTRIBUTION = ("Postal code from OneMap, Singapore Land Authority, "
                      "under the Singapore Open Data Licence v1.0")
MAX_DISTANCE_M = 200

_ABBREV = {
    "AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "DRIVE": "DR", "CRESCENT": "CRES", "CENTRAL": "CTRL",
    "NORTH": "NTH", "SOUTH": "STH", "CLOSE": "CL", "PLACE": "PL", "TERRACE": "TER", "BOULEVARD": "BLVD",
    "LANE": "LN", "PARK": "PK", "INDUSTRIAL": "IND", "JALAN": "JLN", "LORONG": "LOR", "BUKIT": "BT",
    "TANJONG": "TG", "UPPER": "UPP", "LOWER": "LWR", "EXPRESSWAY": "EXPWY", "HEIGHTS": "HTS",
    "GARDENS": "GDNS", "SQUARE": "SQ", "WALK": "WK", "VIEW": "VW", "GROVE": "GR", "LINK": "LK",
    "MOUNT": "MT", "SAINT": "ST", "COMMONWEALTH": "C'WEALTH", "KAMPONG": "KG",
}


def _search(query, session, timeout=20):
    headers = {}
    if os.environ.get("ONEMAP_TOKEN"):
        headers["Authorization"] = os.environ["ONEMAP_TOKEN"]
    resp = session.get(SEARCH, params={"searchVal": query, "returnGeom": "Y",
                                       "getAddrDetails": "Y", "pageNum": 1},
                       headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("results", [])


def by_postal(postal_code, session=None, timeout=20):
    if not postal_code:
        return None
    try:
        for hit in _search(postal_code, session or requests.Session(), timeout):
            if hit.get("POSTAL") == postal_code:
                return float(hit["LATITUDE"]), float(hit["LONGITUDE"])
    except (requests.RequestException, ValueError, KeyError):
        return None
    return None


def road_key(road):
    words = re.sub(r"[^A-Z0-9' ]+", " ", str(road or "").upper()).split()
    return " ".join(_ABBREV.get(w, w) for w in words)


def split_address(address):
    """'601 Balestier Road, #01-02' -> ('601', 'BALESTIER RD'); None if no block + road."""
    first = re.split(r",", str(address or ""))[0]
    first = re.sub(r"#\S+", " ", first).strip()
    m = re.match(r"^(?:BLK\s+|BLOCK\s+)?(\d{1,4}[A-Z]?)\s+(.*[A-Za-z]{3,}.*)$", first, re.I)
    if not m:
        return None
    return m.group(1).upper(), road_key(m.group(2))


def address_key(address):
    parts = split_address(address)
    return f"{parts[0]} {parts[1]}" if parts else ""


def postal_for_address(address, lat, lon, session=None):
    """Return (postal_code or '', outcome) where outcome is matched / no_match / ambiguous / error / unparseable."""
    parts = split_address(address)
    if not parts:
        return "", "unparseable"
    blk, road = parts
    first = re.sub(r"#\S+", " ", re.split(r",", str(address))[0]).strip()
    first = re.sub(r"^(BLK|BLOCK)\s+", "", first, flags=re.I)
    try:
        hits = _search(first, session or requests.Session())  # search with the original wording
    except (requests.RequestException, ValueError):
        return "", "error"
    postals = set()
    for h in hits:
        if str(h.get("BLK_NO", "")).upper() != blk or road_key(h.get("ROAD_NAME")) != road:
            continue
        d = metres_between(lat, lon, h.get("LATITUDE"), h.get("LONGITUDE"))
        if d is None or d > MAX_DISTANCE_M:
            continue
        if re.fullmatch(r"\d{6}", str(h.get("POSTAL", ""))):
            postals.add(h["POSTAL"])
    if len(postals) == 1:
        return postals.pop(), "matched"
    return "", "ambiguous" if postals else "no_match"


def throttle(seconds=0.25):
    time.sleep(seconds)
