"""Systematic OpenStreetMap research extract for new countries (Malaysia, Japan).

One Overpass query per state / prefecture (ISO 3166-2 area), so coverage can be
reported area by area. For each area it records:
  * every place tagged diet:halal=yes|only|limited or cuisine=halal
  * the number of eating places OSM knows in that area (context for coverage)
plus, per country, city/town nodes used to assign a nearest town.

Output (committed, ODbL): _directory-sync/research/osm-<CC>.json.gz
This script only reads OpenStreetMap. It never touches the live workbooks.
"""
import datetime as dt
import gzip
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsync.sources import OVERPASS_ENDPOINTS, USER_AGENT  # noqa: E402

OUT = Path(__file__).resolve().parent / "research"

AREAS = {
    "MY": {f"MY-{i:02d}": n for i, n in enumerate([
        "Johor", "Kedah", "Kelantan", "Melaka", "Negeri Sembilan", "Pahang", "Pulau Pinang", "Perak",
        "Perlis", "Selangor", "Terengganu", "Sabah", "Sarawak", "Kuala Lumpur", "Labuan", "Putrajaya"], start=1)},
    "JP": {f"JP-{i:02d}": n for i, n in enumerate([
        "Hokkaido", "Aomori", "Iwate", "Miyagi", "Akita", "Yamagata", "Fukushima", "Ibaraki", "Tochigi",
        "Gunma", "Saitama", "Chiba", "Tokyo", "Kanagawa", "Niigata", "Toyama", "Ishikawa", "Fukui",
        "Yamanashi", "Nagano", "Gifu", "Shizuoka", "Aichi", "Mie", "Shiga", "Kyoto", "Osaka", "Hyogo",
        "Nara", "Wakayama", "Tottori", "Shimane", "Okayama", "Hiroshima", "Yamaguchi", "Tokushima",
        "Kagawa", "Ehime", "Kochi", "Fukuoka", "Saga", "Nagasaki", "Kumamoto", "Oita", "Miyazaki",
        "Kagoshima", "Okinawa"], start=1)},
}

AREA_QUERY = """
[out:json][timeout:180];
area["ISO3166-2"="{code}"]->.a;
(
  nwr["diet:halal"~"^(yes|only|limited)$"](area.a);
  nwr["cuisine"~"(^|;)halal(;|$)"](area.a);
);
out tags center meta;
nwr["amenity"~"^(restaurant|cafe|fast_food|food_court)$"](area.a);
out count;
"""

PLACES_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="{cc}"][admin_level=2]->.c;
node["place"~"^(city|town)$"](area.c);
out tags;
"""


def overpass(query, session):
    last = None
    for attempt in range(3):
        for url in OVERPASS_ENDPOINTS:
            try:
                r = session.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=240)
                if r.status_code == 200:
                    payload = r.json()
                    if "elements" in payload and not ("error" in (payload.get("remark") or "").lower()):
                        return payload
                    last = f"{url}: {payload.get('remark', 'no elements')[:150]}"
                else:
                    last = f"{url}: HTTP {r.status_code}"
            except (requests.RequestException, ValueError) as exc:
                last = f"{url}: {type(exc).__name__}"
            print("  retry:", last, flush=True)
            time.sleep(5)
        time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"Overpass failed: {last}")


def main(countries):
    OUT.mkdir(exist_ok=True)
    s = requests.Session()
    for cc in countries:
        result = {"country": cc, "retrieved": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                  "licence": "ODbL-1.0 (c) OpenStreetMap contributors", "areas": {}, "places": []}
        for code, name in AREAS[cc].items():
            payload = overpass(AREA_QUERY.format(code=code), s)
            els = [e for e in payload["elements"] if e.get("type") != "count"]
            counts = [e for e in payload["elements"] if e.get("type") == "count"]
            eating = int(counts[0]["tags"]["total"]) if counts else None
            result["areas"][code] = {"name": name, "halal_tagged": len(els), "eating_places": eating,
                                     "elements": els}
            print(f"{code} {name}: {len(els)} halal-tagged of {eating} eating places", flush=True)
            time.sleep(3)
        places = overpass(PLACES_QUERY.format(cc=cc), s)["elements"]
        result["places"] = [{"id": p["id"], "lat": p["lat"], "lon": p["lon"],
                             "name": p["tags"].get("name:en") or p["tags"].get("name"),
                             "name_local": p["tags"].get("name"), "place": p["tags"].get("place")}
                            for p in places if p.get("tags")]
        print(f"{cc}: {len(result['places'])} city/town nodes", flush=True)
        with gzip.open(OUT / f"osm-{cc}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1:] or ["MY", "JP"])
