"""Optional coordinates from OneMap (Singapore Land Authority) by postal code.

Used only to place verified listings on the directory map. If OneMap is
unreachable, or requires a token that is not configured (ONEMAP_TOKEN), the
listing is still added and flagged "Missing coordinates" for manual entry.
"""
import os

import requests

SEARCH = "https://www.onemap.gov.sg/api/common/elastic/search"


def by_postal(postal_code, session=None, timeout=20):
    if not postal_code:
        return None
    session = session or requests.Session()
    headers = {}
    if os.environ.get("ONEMAP_TOKEN"):
        headers["Authorization"] = os.environ["ONEMAP_TOKEN"]
    try:
        resp = session.get(SEARCH, params={"searchVal": postal_code, "returnGeom": "Y",
                                           "getAddrDetails": "Y", "pageNum": 1},
                           headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        for hit in resp.json().get("results", []):
            if hit.get("POSTAL") == postal_code:
                return float(hit["LATITUDE"]), float(hit["LONGITUDE"])
    except (requests.RequestException, ValueError, KeyError):
        return None
    return None
