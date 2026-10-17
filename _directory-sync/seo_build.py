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

It also generates one landing page per additional country
(muslim-friendly-directory-malaysia.html, muslim-friendly-directory-japan.html)
from the Singapore page, with its own title, description, canonical URL,
structured data and crawlable list grouped by state or prefecture. The pages
share all code with the Singapore page and open with that country selected.

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


COUNTRY_PAGES = {
    "Malaysia": {
        "file": "muslim-friendly-directory-malaysia.html", "data": "community-listings-my.xlsx", "iso": "MY",
        "lang": "en-MY", "region_word": "state",
        "title": "Muslim-Friendly &amp; Halal Restaurants Malaysia | Dining Directory by State",
        "description": "Find Muslim-friendly and halal places to eat across Malaysia, from Kuala Lumpur and Johor Bahru to Penang, Sabah and Sarawak. Each listing states what has and has not been verified.",
        "certifier": "a certification body such as JAKIM or a state Islamic religious authority",
        "about": ["Muslim-friendly dining in Malaysia", "Halal food in Malaysia"],
    },
    "Japan": {
        "file": "muslim-friendly-directory-japan.html", "data": "community-listings-jp.xlsx", "iso": "JP",
        "lang": "en", "region_word": "prefecture",
        "title": "Halal &amp; Muslim-Friendly Restaurants Japan | Dining Directory by Prefecture",
        "description": "Find halal and Muslim-friendly places to eat across Japan, from Tokyo, Osaka and Kyoto to Hokkaido and Okinawa. Each listing shows whether the whole menu or only selected dishes are reported halal, and what is not verified.",
        "certifier": "a Japanese halal certification body (standards and recognition differ between bodies)",
        "about": ["Muslim-friendly dining in Japan", "Halal food in Japan"],
    },
}
SG_TITLE = "Muslim-Friendly Dining Directory Singapore | Halal &amp; Muslim-Friendly Food"
SG_DESC = ("Find Muslim-friendly places to eat in Singapore. Every listing shows its status: "
           "halal-certified, self-declared or community-suggested.")


def country_static_list(rows, region_word):
    groups = {}
    for r in rows:
        groups.setdefault(str(r.get("State / Prefecture") or "Other"), []).append(r)
    parts = []
    for region in sorted(groups):
        items = []
        for r in groups[region]:
            status = STATUS_LABEL.get(str(r.get("Listing Status", "")).strip().lower(), r.get("Listing Status") or "")
            scope = r.get("Halal Scope") or ""
            local = f' <span lang="{"ja" if r.get("Country") == "Japan" else "ms"}">({html.escape(str(r["Local Name"]))})</span>' if r.get("Local Name") else ""
            meta = " · ".join(str(x) for x in (r.get("City"), r.get("Establishment Type"), r.get("Cuisine")) if x)
            note = "; ".join(x for x in (status, scope) if x)
            items.append(f'<li><strong>{html.escape(str(r["Name"]))}</strong>{local}<br>{html.escape(meta)}'
                         f'<br><em>{html.escape(note)}</em></li>')
        parts.append(f'<h3 class="static-region">{html.escape(region)} ({len(items)})</h3><ul class="static-listings">{"".join(items)}</ul>')
    return (f'<div aria-label="Published listings by {region_word}">{"".join(parts)}</div>' if parts else "")


def country_item_list(rows, country, iso, url):
    elements = []
    for i, r in enumerate(rows, start=1):
        item = {"@type": SCHEMA_TYPE.get(r.get("Establishment Type"), "FoodEstablishment"), "name": str(r["Name"])}
        if r.get("Local Name"):
            item["alternateName"] = str(r["Local Name"])
        addr = {"@type": "PostalAddress", "addressCountry": iso}
        if r.get("Address"):
            addr["streetAddress"] = str(r["Address"])
        if r.get("Postal Code"):
            addr["postalCode"] = str(r["Postal Code"])
        if r.get("City"):
            addr["addressLocality"] = str(r["City"])
        if r.get("State / Prefecture"):
            addr["addressRegion"] = str(r["State / Prefecture"])
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
            "name": f"Muslim-Friendly Dining Directory, {country}", "url": url,
            "numberOfItems": len(elements), "itemListElement": elements}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/ld+json" id="directory-itemlist">{payload}</script>' if elements else ""


def country_page(sg_page, country, cfg, rows):
    url = "https://digi-architect.studio/" + cfg["file"][:-5]
    p = sg_page
    swaps = [
        (f"<title>{SG_TITLE}</title>", f"<title>{cfg['title']}</title>"),
        (f'<meta name="description" content="{SG_DESC}">', f'<meta name="description" content="{cfg["description"]}">'),
        (f'<meta property="og:title" content="{SG_TITLE}">', f'<meta property="og:title" content="{cfg["title"]}">'),
        (f'<meta property="og:description" content="{SG_DESC}">', f'<meta property="og:description" content="{cfg["description"]}">'),
        ('<link rel="canonical" href="https://digi-architect.studio/muslim-friendly-directory">', f'<link rel="canonical" href="{url}">'),
        ('<meta property="og:url" content="https://digi-architect.studio/muslim-friendly-directory">', f'<meta property="og:url" content="{url}">'),
        ('"name": "Muslim-Friendly Dining Directory, Singapore",\n  "url": "https://digi-architect.studio/muslim-friendly-directory",\n  "inLanguage": "en-SG",',
         f'"name": "Muslim-Friendly Dining Directory, {country}",\n  "url": "{url}",\n  "inLanguage": "{cfg["lang"]}",'),
        ('"description": "Directory of Muslim-friendly places to eat in Singapore. Each listing states whether it is halal-certified (certificate verified), self-declared by the establishment, or community-suggested and not verified.",',
         f'"description": {json.dumps(html.unescape(cfg["description"]))},'),
        ('"about": [\n    "Muslim-friendly dining",\n    "Halal food in Singapore"\n  ],',
         '"about": [\n    ' + ",\n    ".join(json.dumps(a) for a in cfg["about"]) + "\n  ],"),
        ('"spatialCoverage": {\n    "@type": "Place",\n    "name": "Singapore"\n  },',
         f'"spatialCoverage": {{\n    "@type": "Country",\n    "name": "{country}"\n  }},'),
        ('<h1 class="eyebrow light">Muslim-Friendly Dining Directory, Singapore</h1>',
         f'<h1 class="eyebrow light">Muslim-Friendly Dining Directory, {country}</h1>'),
        ("issued by a certification body such as Muis.", f"issued by {cfg['certifier']}."),
        ('<html lang="en">', f'<html lang="{cfg["lang"]}">'),
        ("</head>", f"<script>window.DIRECTORY_COUNTRY = {json.dumps(country)};</script>\n</head>"),
    ]
    for old, new in swaps:
        if old not in p:
            if old == '<html lang="en">':
                continue
            raise SystemExit(f"{cfg['file']}: template text not found: {old[:70]}")
        p = p.replace(old, new, 1)
    p = replace_between(p, "STATIC-LISTINGS", country_static_list(rows, cfg["region_word"]))
    p = replace_between(p, "DIRECTORY-ITEMLIST", country_item_list(rows, country, cfg["iso"], url))
    return p


def country_rows(cfg):
    from dsync.workbook import read_directory
    path = REPO / "data" / cfg["data"]
    if not path.exists():
        return []
    _, rows = read_directory(path)
    return sorted((r for r in rows if str(r.get("Is Demo", "")).lower() not in TRUEISH),
                  key=lambda r: (str(r.get("State / Prefecture") or ""), str(r.get("City") or ""), str(r["Name"]).lower()))


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
    today = dt.datetime.now(ZoneInfo(SGT_TZ)).date().isoformat()
    if new_page != page:
        new_sitemap = re.sub(r"(<loc>https://digi-architect\.studio/muslim-friendly-directory</loc>\s*<lastmod>)[^<]*",
                             rf"\g<1>{today}", new_sitemap, count=1)
    others = {}
    for country, cfg in COUNTRY_PAGES.items():
        crow = country_rows(cfg)
        if not crow:
            continue
        path = REPO / cfg["file"]
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        new = country_page(new_page, country, cfg, crow)
        others[path] = (old, new, len(crow))
        loc = "https://digi-architect.studio/" + cfg["file"][:-5]
        if f"<loc>{loc}</loc>" not in new_sitemap:
            entry = (f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{today}</lastmod>\n"
                     f"    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>\n\n")
            new_sitemap = new_sitemap.replace("  <url>\n    <loc>https://digi-architect.studio/workflow-automation-singapore/</loc>",
                                              entry + "  <url>\n    <loc>https://digi-architect.studio/workflow-automation-singapore/</loc>", 1)
        elif old != new:
            new_sitemap = re.sub(rf"(<loc>{re.escape(loc)}</loc>\s*<lastmod>)[^<]*", rf"\g<1>{today}", new_sitemap, count=1)
    return rows, page, new_page, sitemap, new_sitemap, others


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="fail if the page is out of date")
    p.add_argument("--workbook", default=str(WORKBOOK))
    args = p.parse_args()
    rows, page, new_page, sitemap, new_sitemap, others = build(args.workbook)
    stale = [p.name for p, (old, new, _) in others.items() if old != new]
    if args.check:
        if new_page != page or stale:
            print(f"Directory pages are out of date ({len(rows)} Singapore listings; stale: {stale or 'Singapore page'}). Run seo_build.py.")
            return 1
        print(f"Directory pages are up to date ({len(rows)} Singapore listings; "
              + ", ".join(f"{p.name}: {n}" for p, (_, _, n) in others.items()) + ").")
        return 0
    if new_page != page:
        PAGE.write_text(new_page, encoding="utf-8")
        print(f"Updated: {len(rows)} listings in page and structured data.")
    for p, (old, new, n) in others.items():
        if old != new:
            p.write_text(new, encoding="utf-8")
            print(f"Updated {p.name}: {n} listings.")
    if new_sitemap != sitemap:
        SITEMAP.write_text(new_sitemap, encoding="utf-8")
        print("Sitemap updated.")
    if new_page == page and not stale and new_sitemap == sitemap:
        print(f"No change ({len(rows)} Singapore listings).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
