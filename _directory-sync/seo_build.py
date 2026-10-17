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
as a search-engine landing page: title, description, canonical URL, structured
data, coverage by state or prefecture and a crawlable list of the same published
records. The landing pages are not directories; every link opens the one unified
directory (muslim-friendly-directory) with that country, and optionally that
state or prefecture, selected. Without published records a page is noindex and
is left out of the sitemap.

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
        "file": "muslim-friendly-directory-malaysia.html", "data": ["directory-my.xlsx", "community-listings-my.xlsx"], "iso": "MY",
        "lang": "en-MY", "region_word": "state",
        "title": "Muslim-Friendly &amp; Halal Restaurants Malaysia | Dining Directory by State",
        "description": "Find Muslim-friendly and halal places to eat across Malaysia, from Kuala Lumpur and Johor Bahru to Penang, Sabah and Sarawak. Each listing states what has and has not been verified.",
        "certifier": "JAKIM (Department of Islamic Development Malaysia) or a state Islamic religious authority",
        "headline": "Muslim-friendly places to eat across <em>Malaysia</em>.",
        "intro": "Search halal-certified, self-declared and Muslim-friendly restaurants, cafés and food courts by state and city, from Kuala Lumpur and Selangor to Penang, Johor, Sabah and Sarawak. Every listing states what has been verified, by whom and when.",
        "about": ["Muslim-friendly dining in Malaysia", "Halal food in Malaysia"],
    },
    "Japan": {
        "file": "muslim-friendly-directory-japan.html", "data": ["directory-jp.xlsx", "community-listings-jp.xlsx"], "iso": "JP",
        "lang": "en", "region_word": "prefecture",
        "title": "Halal &amp; Muslim-Friendly Restaurants Japan | Dining Directory by Prefecture",
        "description": "Find halal and Muslim-friendly places to eat across Japan, from Tokyo, Osaka and Kyoto to Hokkaido and Okinawa. Each listing shows whether the whole menu or only selected dishes are reported halal, and what is not verified.",
        "certifier": "a Japanese halal certification body (standards and recognition differ between bodies)",
        "headline": "Halal and Muslim-friendly dining across <em>Japan</em>.",
        "intro": "Search restaurants by prefecture and city, from Tokyo, Osaka and Kyoto to Hokkaido, Fukuoka and Okinawa. Many Japanese restaurants offer a halal menu rather than a fully halal kitchen, so each listing shows the scope of the halal offer, alcohol and pork on the premises, and whether a reservation is needed, where the source states it.",
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


LANDING_CSS = """
html,body{height:auto;overflow:auto;}
.landing{padding-top:var(--hdr-h);}
.l-hero{background:var(--ink);color:#fff;padding:56px 24px 48px;}
.l-wrap{max-width:1040px;margin:0 auto;}
.l-hero h1.eyebrow{margin-bottom:18px;}
.l-hero .l-title{font-family:Georgia,'Times New Roman',serif;font-size:clamp(30px,4.6vw,52px);line-height:1.08;letter-spacing:-0.02em;color:#fff;max-width:20ch;margin-bottom:18px;}
.l-hero .l-title em{font-style:normal;color:var(--gold-l);}
.l-hero p{color:rgba(255,255,255,0.72);max-width:62ch;line-height:1.75;font-size:15px;margin-bottom:26px;}
.l-btns{display:flex;flex-wrap:wrap;gap:12px;}
.l-btns .btn{min-height:46px;}
.l-note{margin-top:26px;border-left:2px solid var(--gold-l);padding:4px 0 4px 14px;font-size:13px;color:rgba(255,255,255,0.7);max-width:70ch;}
.l-sec{padding:40px 24px;border-bottom:1px solid var(--line);}
.l-sec h2{font-size:clamp(20px,2.6vw,28px);margin-bottom:10px;}
.l-sec > .l-wrap > p{max-width:70ch;line-height:1.7;font-size:14px;margin-bottom:18px;}
.l-chips{display:flex;flex-wrap:wrap;gap:8px;list-style:none;}
.l-chips a{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);background:var(--white);padding:8px 12px;font-size:13px;border-radius:2px;min-height:40px;}
.l-chips a:hover{border-color:var(--gold);color:var(--gold);}
.l-chips b{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);font-weight:600;}
.l-key{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}
.l-key div{background:var(--white);border:1px solid var(--line);padding:14px;font-size:13px;line-height:1.55;color:var(--muted);}
.l-key strong{display:block;color:var(--ink);font-size:13px;margin-bottom:4px;}
.l-list details{border-bottom:1px solid var(--line);}
.l-list summary{cursor:pointer;padding:12px 0;font-size:14px;font-weight:600;min-height:44px;}
.l-list ul{list-style:none;padding:0 0 12px;}
.l-list li{padding:8px 0;font-size:13px;line-height:1.5;border-top:1px solid var(--line);color:var(--muted);}
.l-list li strong{color:var(--ink);}
.l-foot{padding:28px 24px 40px;font-size:12px;color:var(--muted);}
.l-foot a{text-decoration:underline;}
@media(max-width:640px){.l-hero{padding:40px 16px 36px;}.l-sec{padding:32px 16px;}.l-foot{padding:24px 16px 36px;}}
"""

KEY = [("Halal-certified", "Certification confirmed with the certifying body or its official register, with the date checked."),
       ("Certification reported", "The establishment, a tourism body or the press reports certification; not yet confirmed with the certifier."),
       ("Self-declared", "The establishment publicly states its own practices (for example a halal menu, no pork, no alcohol)."),
       ("Selected halal menu", "Only some dishes or a special menu are offered as halal; the rest of the menu may not be."),
       ("Muslim-owned", "Shown only where a credible source states it. It is not a halal certification."),
       ("Community-suggested", "Reported by the public (for example OpenStreetMap); not verified.")]


def deep_link(country, region=None):
    from urllib.parse import quote
    q = f"?country={country.lower()}" + (f"&region={quote(region)}" if region else "")
    return f"/muslim-friendly-directory{q}#directory"


def country_page(sg_page, country, cfg, rows):
    """SEO landing page: introduces the country and links into the one unified directory.

    It is not a directory: no search, filters, map or data loading. It shares the
    directory's head, header styles and analytics, and lists the same published
    records (grouped by state or prefecture) so search engines can read them.
    With no published records it is marked noindex and kept out of the sitemap."""
    url = "https://digi-architect.studio/" + cfg["file"][:-5]
    head = sg_page[:sg_page.index("</style>")]
    for a, b in [(f"<title>{SG_TITLE}</title>", f"<title>{cfg['title']}</title>"),
                 (f'<meta name="description" content="{SG_DESC}">', f'<meta name="description" content="{cfg["description"]}">'),
                 (f'<meta property="og:title" content="{SG_TITLE}">', f'<meta property="og:title" content="{cfg["title"]}">'),
                 (f'<meta property="og:description" content="{SG_DESC}">', f'<meta property="og:description" content="{cfg["description"]}">'),
                 ('<link rel="canonical" href="https://digi-architect.studio/muslim-friendly-directory">', f'<link rel="canonical" href="{url}">'),
                 ('<meta property="og:url" content="https://digi-architect.studio/muslim-friendly-directory">', f'<meta property="og:url" content="{url}">'),
                 ('<html lang="en">', f'<html lang="{cfg["lang"]}">')]:
        if a not in head:
            raise SystemExit(f"{cfg['file']}: template text not found: {a[:70]}")
        head = head.replace(a, b, 1)
    if not rows:
        head = head.replace('<meta name="robots" content="index, follow">', '<meta name="robots" content="noindex, follow">', 1)
    head = re.sub(r'<link rel="stylesheet" href="https://unpkg.com/leaflet[^>]*>\n?', "", head)
    m = re.search(r'<noscript><iframe src="https://www.googletagmanager.com[^\n]*</noscript>', sg_page)
    gtm = m.group(0) if m else ""
    header = sg_page[sg_page.index('<header class="site-header">'):sg_page.index("</header>") + 9]
    header = re.sub(r'<button class="hdr-cta"[^>]*>[^<]*</button>', f'<a class="hdr-cta" href="{deep_link(country)}">Search the Directory</a>', header)
    header = re.sub(r'\s*<button class="nav-toggle".*?</button>', "", header, flags=re.S)
    groups = {}
    for r in rows:
        groups.setdefault(str(r.get("State / Prefecture") or "Other"), []).append(r)
    chips = "".join(f'<li><a href="{html.escape(deep_link(country, g))}">{html.escape(g)} <b>{len(v)}</b></a></li>'
                    for g, v in sorted(groups.items()))
    lists = []
    for g, v in sorted(groups.items()):
        items = []
        for r in v:
            local = (f' <span lang="{"ja" if country == "Japan" else "ms"}">({html.escape(str(r["Local Name"]))})</span>'
                     if r.get("Local Name") else "")
            meta = " · ".join(str(x) for x in (r.get("City"), r.get("Establishment Type"), r.get("Cuisine")) if x)
            status = STATUS_LABEL.get(str(r.get("Listing Status", "")).strip().lower(), r.get("Listing Status") or "")
            note = "; ".join(str(x) for x in (status, r.get("Halal Scope")) if x)
            items.append(f"<li><strong>{html.escape(str(r['Name']))}</strong>{local}<br>{html.escape(meta)}<br><em>{html.escape(note)}</em></li>")
        lists.append(f"<details><summary>{html.escape(g)} ({len(v)})</summary><ul>{''.join(items)}</ul></details>")
    region_title = cfg["region_word"].capitalize() + ("s" if cfg["region_word"] != "state" else "s and federal territories")
    if rows:
        coverage = (f'<section class="l-sec"><div class="l-wrap"><h2>Browse by {cfg["region_word"]}</h2>'
                    f'<p>{len(rows)} published listings in {len(groups)} {region_title.lower()}. Each link opens the directory with {country} and that {cfg["region_word"]} selected.</p>'
                    f'<ul class="l-chips">{chips}</ul></div></section>')
        listing = (f'<section class="l-sec l-list"><div class="l-wrap"><h2>Published listings</h2>'
                   f'<p>The same records as the directory, grouped by {cfg["region_word"]}. Open the directory for full details, filters and the map.</p>'
                   f'{"".join(lists)}</div></section>')
    else:
        coverage = (f'<section class="l-sec"><div class="l-wrap"><h2>Coverage in preparation</h2>'
                    f'<p>Listings for {country} are being researched and verified. They will appear in the directory, and here, once each record has been checked.</p></div></section>')
        listing = ""
    key = "".join(f"<div><strong>{html.escape(a)}</strong>{html.escape(b)}</div>" for a, b in KEY)
    body = f"""
{LANDING_CSS}</style>
{country_item_list(rows, country, cfg["iso"], url)}
</head>
<body>
{gtm}
<div class="page-bg" aria-hidden="true"></div>
{header}
<main class="landing">
<section class="l-hero"><div class="l-wrap">
<h1 class="eyebrow light">Muslim-Friendly Dining Directory, {country}</h1>
<p class="l-title">{cfg["headline"]}</p>
<p>{cfg["intro"]}</p>
<div class="l-btns"><a class="btn btn-primary" href="{deep_link(country)}">Search {country} in the directory</a><a class="btn btn-ghost-light" href="/muslim-friendly-directory#directory">All countries</a></div>
<p class="l-note">Halal certification is issued by {cfg["certifier"]}. A self-declared, community-suggested or Muslim-owned listing is not the same as halal-certified. Check with the establishment before visiting.</p>
</div></section>
{coverage}
<section class="l-sec"><div class="l-wrap"><h2>How listings are classified</h2><p>These labels can apply together. Each listing shows its sources and the date it was last checked.</p><div class="l-key">{key}</div></div></section>
{listing}
<footer class="l-foot"><div class="l-wrap">Part of the <a href="/muslim-friendly-directory">Muslim-Friendly Dining Directory</a> by The Digital Systems Architect, covering Singapore, Malaysia and Japan. &copy; 2026 Zan J Private Limited.</div></footer>
</main>
</body>
</html>
"""
    return head + body


def country_rows(cfg):
    from dsync.workbook import read_directory
    rows = []
    for name in cfg["data"]:
        path = REPO / "data" / name
        if path.exists():
            rows += read_directory(path)[1]
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
        path = REPO / cfg["file"]
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        new = country_page(new_page, country, cfg, crow)
        others[path] = (old, new, len(crow))
        loc = "https://digi-architect.studio/" + cfg["file"][:-5]
        if not crow:
            new_sitemap = re.sub(rf"  <url>\n    <loc>{re.escape(loc)}</loc>.*?</url>\n\n", "", new_sitemap, flags=re.S)
        elif f"<loc>{loc}</loc>" not in new_sitemap:
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
