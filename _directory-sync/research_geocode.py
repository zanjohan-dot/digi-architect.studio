"""Fill in readable addresses for Malaysia / Japan candidates from OpenStreetMap.

Uses OpenStreetMap's own reverse geocoder (Nominatim), politely: one request
per 1.1 seconds, a descriptive User-Agent, and a committed cache so each place
is looked up once. Results are OpenStreetMap data (ODbL), like the rest of the
community listings.

Japan: one English and one Japanese lookup per place (readable English address
plus the official-language address). Malaysia: English.

Writes _directory-sync/research/geocode-cache.json
"""
import gzip
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsync.quality import DINING_AMENITIES, DINING_SHOPS  # noqa: E402
from dsync.sources import USER_AGENT  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / "research" / "geocode-cache.json"
URL = "https://nominatim.openstreetmap.org/reverse"
KEEP = ("house_number", "road", "neighbourhood", "quarter", "suburb", "city_district", "village", "town",
        "city", "municipality", "county", "state", "province", "postcode")


def dining(tags):
    return tags.get("amenity") in DINING_AMENITIES or tags.get("shop") in DINING_SHOPS


def lookup(session, lat, lon, lang):
    r = session.get(URL, params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18,
                                 "addressdetails": 1, "accept-language": lang},
                    headers={"User-Agent": USER_AGENT}, timeout=30)
    time.sleep(1.1)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    a = r.json().get("address") or {}
    return {k: a[k] for k in KEEP if a.get(k)}


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    s = requests.Session()
    done = failed = 0
    for cc, langs in (("MY", ["en"]), ("JP", ["en", "ja"])):
        data = json.load(gzip.open(HERE / "research" / f"osm-{cc}.json.gz", "rt", encoding="utf-8"))
        for area in data["areas"].values():
            for el in area["elements"]:
                tags = el.get("tags") or {}
                if not tags.get("name") or not dining(tags):
                    continue
                lat = el.get("lat", (el.get("center") or {}).get("lat"))
                lon = el.get("lon", (el.get("center") or {}).get("lon"))
                if lat is None:
                    continue
                sid = f"osm:{el['type']}/{el['id']}"
                entry = cache.setdefault(sid, {})
                for lang in langs:
                    if lang in entry:
                        continue
                    try:
                        entry[lang] = lookup(s, lat, lon, lang)
                        done += 1
                    except (requests.RequestException, RuntimeError, ValueError) as exc:
                        failed += 1
                        print(f"{sid} {lang}: {exc}", flush=True)
                        if failed > 25:
                            break
                if done and done % 100 == 0:
                    print(f"{done} lookups", flush=True)
                    CACHE.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"Done: {done} lookups, {failed} failed, {len(cache)} places cached", flush=True)
    return 0 if failed <= 25 else 1


if __name__ == "__main__":
    sys.exit(main())
