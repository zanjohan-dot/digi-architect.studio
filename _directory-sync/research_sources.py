"""Read-only retrieval of public research sources (GitHub Actions only).

Reads _directory-sync/research/sources-request.json and saves everything under
./sources-out/, which the workflow uploads as a short-lived Actions artifact.
Nothing retrieved here is committed to the repository: official guides and
pages stay with their publishers; only facts derived from them, with source
URLs, go into the research datasets.

Request keys:
  download: [{"key", "url"}]                         save the file as-is
  crawl:    [{"key", "url", "match": "regex", "limit": n}]
            save the page, then same-site links whose URL or text matches
  jakim:    [{"key", "negeri", "cari", "category": "PE"}]
            JAKIM Halal Status Verification search (public form), one query each
Polite: descriptive User-Agent, at least 1.5 s between requests.
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

HERE = Path(__file__).resolve().parent
OUT = Path("sources-out")
UA = "digi-architect.studio directory research (admin@digi-architect.studio)"
JAKIM = "https://myehalal.halal.gov.my/portal-halal/v1/index.php?data=ZGlyZWN0b3J5L2luZGV4X2RpcmVjdG9yeTs7Ozs="
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en,ja;q=0.8,ms;q=0.6"})
INDEX = {}


def get(url, **kw):
    try:
        return S.request(kw.pop("method", "GET"), url, timeout=60, **kw)
    finally:
        time.sleep(1.5)


def save(key, r, url):
    ext = ".pdf" if "pdf" in r.headers.get("content-type", "") or url.lower().endswith(".pdf") else ".html"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:120] + ext
    (OUT / name).write_bytes(r.content)
    INDEX[key] = {"url": url, "final_url": r.url, "status": r.status_code, "file": name, "bytes": len(r.content),
                  "content_type": r.headers.get("content-type", "")}


def fetch(key, url, **kw):
    try:
        r = get(url, **kw)
        save(key, r, url)
        return r
    except requests.RequestException as exc:
        INDEX[key] = {"url": url, "error": str(exc)[:300]}
        return None


def crawl(item):
    r = fetch(item["key"], item["url"])
    if r is None or "html" not in r.headers.get("content-type", "html"):
        return
    host = urlparse(r.url).netloc
    pat = re.compile(item.get("match", "."), re.I)
    seen = set()
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', r.text, re.I | re.S):
        link = urljoin(r.url, m.group(1))
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        if link in seen or (urlparse(link).netloc != host and not link.lower().endswith(".pdf")):
            continue
        if pat.search(link) or pat.search(text):
            seen.add(link)
            fetch(f"{item['key']}--{len(seen):03d}", link)
            if len(seen) >= item.get("limit", 40):
                break


def main():
    req = json.loads((HERE / "research" / "sources-request.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    for it in req.get("download", []):
        fetch(it["key"], it["url"])
    for it in req.get("crawl", []):
        crawl(it)
    for it in req.get("jakim", []):
        fetch(it["key"], JAKIM, method="POST",
              data={"negeri": it.get("negeri", ""), "category": it.get("category", "PE"), "cari": it["cari"]})
    (OUT / "index.json").write_text(json.dumps(INDEX, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for v in INDEX.values() if v.get("status") == 200)
    print(f"{ok} of {len(INDEX)} retrieved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
