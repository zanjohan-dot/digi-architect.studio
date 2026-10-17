"""Official halal status checks for Malaysian candidates (GitHub Actions only).

Uses JAKIM's public Halal Status Verification search (MYeHALAL), one query per
candidate establishment we are considering listing - targeted verification,
not a copy of the register. Polite: descriptive User-Agent, 3 s between queries.

Reads  _directory-sync/research/jakim-request.json
       {"queries": [{"key", "negeri" (01-16 or ""), "cari", "category": "PE"}], "probe": false}
Writes _directory-sync/research/jakim-checks.json
       {key: {"query", "checked", "status", "results": [result text, ...]}}
Only the text of matching result entries is kept (name, address, certificate
details as shown by the portal). With "probe": true the visible text of the
results area is kept instead, to confirm how results are laid out.
"""
import datetime as dt
import html as htmllib
import json
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REQ = HERE / "research" / "jakim-request.json"
OUT = HERE / "research" / "jakim-checks.json"
UA = "digi-architect.studio directory research (admin@digi-architect.studio)"
URL = "https://myehalal.halal.gov.my/portal-halal/v1/index.php?data=ZGlyZWN0b3J5L2luZGV4X2RpcmVjdG9yeTs7Ozs="


def visible_lines(page):
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|td|th|h\d)>", "\n", page)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", page))
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def results_area(lines):
    """Lines after the search form (the portal prints results below it)."""
    for i, ln in enumerate(lines):
        if ln.lower().startswith("hotel & resort") or "premis makanan" in ln.lower():
            return lines[i:]
    return lines


def main():
    req = json.loads(REQ.read_text(encoding="utf-8"))
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    s = requests.Session()
    s.headers["User-Agent"] = UA
    today = dt.date.today().isoformat()
    n = 0
    for q in req.get("queries", []):
        if q["key"] in done and not req.get("recheck"):
            continue
        try:
            r = s.post(URL, data={"negeri": q.get("negeri", ""), "category": q.get("category", "PE"), "cari": q["cari"]}, timeout=60)
            lines = results_area(visible_lines(r.text))
            if req.get("probe"):
                kept = lines[:150]
            else:
                term = q["cari"].lower()
                kept = [ln for ln in lines if term in ln.lower()][:40]
            done[q["key"]] = {"query": q, "checked": today, "status": r.status_code, "results": kept}
        except requests.RequestException as exc:
            done[q["key"]] = {"query": q, "checked": today, "error": str(exc)[:200]}
        n += 1
        time.sleep(3)
        if n % 50 == 0:
            OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{n} queries; {len(done)} checks stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
