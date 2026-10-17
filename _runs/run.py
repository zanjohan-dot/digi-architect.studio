"""Read-only research helper run by GitHub Actions (this branch only; never merged).

Reads _runs/request.json and writes results under _runs/out/.
Jobs:
  osm_changesets: [ids]            -> OSM API changeset metadata (comment, source tags)
  fetch: [{"key","url"}]           -> raw page (HTML/text), status code
  geocode: [{"id","cc","q"}]       -> Nominatim search (MY) or GSI address search (JP)
All requests are polite: descriptive User-Agent, >= 1.1 s apart.
"""
import json, sys, time
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
UA = "digi-architect.studio directory research (admin@digi-architect.studio)"
S = requests.Session(); S.headers["User-Agent"] = UA


def polite(fn, *a, **k):
    try:
        return fn(*a, timeout=40, **k)
    finally:
        time.sleep(1.1)


def changesets(ids):
    res = {}
    for i in range(0, len(ids), 100):
        chunk = ",".join(str(x) for x in ids[i:i + 100])
        r = polite(S.get, "https://api.openstreetmap.org/api/0.6/changesets.json", params={"changesets": chunk, "closed": "true"})
        if r.status_code != 200:
            print("changesets", r.status_code, r.text[:200]); continue
        for c in r.json().get("changesets", []):
            res[c["id"]] = {"created_at": c.get("created_at"), "tags": c.get("tags", {}), "changes": c.get("changes_count")}
    return res


def fetch(items):
    d = OUT / "fetch"; d.mkdir(parents=True, exist_ok=True)
    idx = {}
    for it in items:
        try:
            r = polite(S.request, it.get("method", "GET"), it["url"], data=it.get("data"), headers=it.get("headers"))
            (d / f"{it['key']}.html").write_bytes(r.content)
            idx[it["key"]] = {"url": it["url"], "status": r.status_code, "final_url": r.url, "bytes": len(r.content)}
        except requests.RequestException as e:
            idx[it["key"]] = {"url": it["url"], "error": str(e)[:300]}
    return idx


def geocode(items):
    res = {}
    for it in items:
        try:
            if it["cc"] == "JP":
                r = polite(S.get, "https://msearch.gsi.go.jp/address-search/AddressSearch", params={"q": it["q"]})
                js = r.json() if r.status_code == 200 else []
                res[it["id"]] = [{"lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
                                  "title": f["properties"].get("title")} for f in js[:3]]
            else:
                r = polite(S.get, "https://nominatim.openstreetmap.org/search",
                           params={"q": it["q"], "format": "jsonv2", "limit": 3, "countrycodes": it["cc"].lower(), "addressdetails": 1})
                js = r.json() if r.status_code == 200 else []
                res[it["id"]] = [{"lat": float(x["lat"]), "lon": float(x["lon"]), "type": x.get("type"),
                                  "display": x.get("display_name")} for x in js[:3]]
        except (requests.RequestException, ValueError) as e:
            res[it["id"]] = {"error": str(e)[:200]}
    return res


def main():
    req = json.loads((HERE / "request.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    tag = req.get("tag", "run")
    if req.get("osm_changesets"):
        (OUT / f"{tag}-changesets.json").write_text(json.dumps(changesets(req["osm_changesets"]), ensure_ascii=False, indent=0), encoding="utf-8")
    if req.get("fetch"):
        (OUT / f"{tag}-fetch-index.json").write_text(json.dumps(fetch(req["fetch"]), ensure_ascii=False, indent=1), encoding="utf-8")
    if req.get("geocode"):
        (OUT / f"{tag}-geocode.json").write_text(json.dumps(geocode(req["geocode"]), ensure_ascii=False, indent=0), encoding="utf-8")
    print("done", tag)


if __name__ == "__main__":
    sys.exit(main())
