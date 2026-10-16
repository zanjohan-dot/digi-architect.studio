#!/usr/bin/env python3
"""Make published listings visible to search engines without JavaScript.

Writes into muslim-friendly-directory.html, between marker comments:
  * STATIC-LISTINGS  - a plain HTML list of every published listing inside the
                       results container (the interactive directory replaces it
                       on load, so visitors see no change)
  * DIRECTORY-ITEMLIST - schema.org ItemList of the listed food establishments
and refreshes the directory's <lastmod> in sitemap.xml when the list changes.

Only published, non-demo listings are included. Nothing is invented: no
ratings, opening hours, or halal claims; each item carries only name, address,
type and coordinates, and the visible list states each listing's status.

  python _directory-sync/seo_build.py          # update files
  python _directory-sync/seo_build.py --check  # exit 1 if files are out of date
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dsync import SGT_TZ  # noqa: E402
from dsync.match import TRUEISH  # noqa: E402
from sync import WORKBOOK, read_all  # noqa: E402

REPO = HERE.parent
PAGE = REPO / "muslim-friendly-directory.html"
SITEMAP = REPO / "sitemap.xml"
PAGE_URL = "https://digi-architect.studio/muslim-friendly-directory"

SCHEMA_TYPE = {"Restaurant": "Restaurant", "Café": "CafeOrCoffeeShop", "Bakery": "Bakery",
               "Bar & Grill": "Restaurant", "Bistro": "Restaurant", "Casual Dining": "Restaurant",
               "Hotel Restaurant": "Restaurant"}
STATUS_LABEL = {"halal certified": "Halal-certified (certificate verified)",
                "self-declared muslim-friendly": "Self-declared Muslim-friendly",
                "community suggested — not verified": "Community-suggested, not verified",
                "pending verification": "Certification pending re-verification"}


def published(listings):
    return sorted((r for r in listings if r.get("Name") and str(r.get("Is Demo", "")).lower() not in TRUEISH),
                  key=lambda r: (str(r["Name"]).lower(), str(r.get("ID"))))


def location(r):
    parts = [r.get("Address"), r.get("Area / Prefecture"),
             f"Singapore {r['Postal Code']}" if r.get("Postal Code") else None]
    return ", ".join(str(p) for p in parts if p)


def static_list(rows):
    items = []
    for r in rows:
        status = STATUS_LABEL.get(str(r.get("Listing Status", "")).strip().lower(), r.get("Listing Status") or "")
        meta = " · ".join(str(x) for x in (location(r), r.get("Establishment Type"), r.get("Cuisine")) if x)
        items.append(f'<li><strong>{html.escape(str(r["Name"]))}</strong><br>{html.escape(meta)}'
                     f'<br><em>{html.escape(status)}</em></li>')
    return (f'<ul class="static-listings" aria-label="Published listings">{"".join(items)}</ul>' if items else "")


def item_list(rows):
    elements = []
    for i, r in enumerate(rows, start=1):
        item = {"@type": SCHEMA_TYPE.get(r.get("Establishment Type"), "FoodEstablishment"),
                "name": str(r["Name"])}
        addr = {"@type": "PostalAddress", "addressCountry": "SG"}
        if r.get("Address"):
            addr["streetAddress"] = str(r["Address"])
        if r.get("Postal Code"):
            addr["postalCode"] = str(r["Postal Code"])
        if r.get("Area / Prefecture"):
            addr["addressLocality"] = str(r["Area / Prefecture"])
        item["address"] = addr
        try:
            item["geo"] = {"@type": "GeoCoordinates", "latitude": round(float(r["Latitude"]), 6),
                           "longitude": round(float(r["Longitude"]), 6)}
        except (TypeError, ValueError, KeyError):
            pass
        if r.get("Cuisine"):
            item["servesCuisine"] = str(r["Cuisine"])
        elements.append({"@type": "ListItem", "position": i, "item": item})
    data = {"@context": "https://schema.org", "@type": "ItemList",
            "name": "Muslim-Friendly Dining Directory, Singapore", "url": PAGE_URL,
            "numberOfItems": len(elements), "itemListElement": elements}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/ld+json" id="directory-itemlist">{payload}</script>' if elements else ""


def replace_between(text, name, content):
    pattern = re.compile(rf"(<!-- {name}:START -->).*?(<!-- {name}:END -->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"Marker {name} missing from {PAGE.name}")
    return pattern.sub(lambda m: m.group(1) + content + m.group(2), text, count=1)


def build(workbook=WORKBOOK):
    rows = published(read_all(workbook))
    page = PAGE.read_text(encoding="utf-8")
    new_page = replace_between(page, "STATIC-LISTINGS", static_list(rows))
    new_page = replace_between(new_page, "DIRECTORY-ITEMLIST", item_list(rows))
    # Validate what we are about to publish.
    m = re.search(r'id="directory-itemlist">(.*?)</script>', new_page, re.S)
    if m:
        parsed = json.loads(m.group(1).replace("<\\/", "</"))
        assert parsed["numberOfItems"] == len(rows)
    sitemap = SITEMAP.read_text(encoding="utf-8")
    new_sitemap = sitemap
    if new_page != page:
        today = dt.datetime.now(ZoneInfo(SGT_TZ)).date().isoformat()
        new_sitemap = re.sub(r"(<loc>https://digi-architect\.studio/muslim-friendly-directory</loc>\s*<lastmod>)[^<]*",
                             rf"\g<1>{today}", sitemap, count=1)
    return rows, page, new_page, sitemap, new_sitemap


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="fail if the page is out of date")
    p.add_argument("--workbook", default=str(WORKBOOK))
    args = p.parse_args()
    rows, page, new_page, sitemap, new_sitemap = build(args.workbook)
    if args.check:
        if new_page != page:
            print(f"Directory page is out of date ({len(rows)} published listings). Run seo_build.py.")
            return 1
        print(f"Directory page is up to date ({len(rows)} published listings).")
        return 0
    if new_page != page:
        PAGE.write_text(new_page, encoding="utf-8")
        SITEMAP.write_text(new_sitemap, encoding="utf-8")
        print(f"Updated: {len(rows)} listings in page and structured data; sitemap lastmod refreshed.")
    else:
        print(f"No change ({len(rows)} published listings).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
