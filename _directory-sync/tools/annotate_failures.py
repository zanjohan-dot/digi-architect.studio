"""Turn unittest failures in a log file into GitHub Actions error annotations.

Annotations appear on the pull request and in the API, so failures are
readable without downloading the job log.
Usage: python annotate_failures.py test.log
"""
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = re.split(r"\n={50,}\n", text)
count = 0
for block in blocks[1:]:
    head, _, body = block.partition("\n" + "-" * 70 + "\n")
    body = body.split("\n" + "-" * 70 + "\n")[0]
    lines = [l for l in body.strip().splitlines() if l.strip()]
    tail = "\n".join(lines[-12:])
    msg = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={head.strip()[:200]}::{msg[:3500]}")
    count += 1
summary = re.search(r"^(Ran \d+ tests.*|OK.*|FAILED.*)$", text, re.M)
print(f"{count} failure annotation(s). {summary.group(0) if summary else ''}")
