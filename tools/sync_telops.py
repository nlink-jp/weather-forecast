#!/usr/bin/env python3
"""Compare the bundled telop table with the one JMA's forecast page embeds.

The weekly forecast carries only telop numbers (e.g. "101"); the number ->
name table exists nowhere in JMA's published documents, only inline in the
forecast page's JavaScript as ``TELOPS={100:[...],...}`` (ADR-0001 §5). This
tool extracts it, diffs it against weather-forecast/scripts/telops.json and,
with --write, replaces the bundled copy.

Maintenance only: it is online, never runs under ``make check``, and never
ships in the skill zip.

Usage:
  python3 tools/sync_telops.py               # diff; exit 1 on a difference
  python3 tools/sync_telops.py --write       # update the bundled table
  python3 tools/sync_telops.py --from-file page.html [--write]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

PAGE_URL = "https://www.jma.go.jp/bosai/forecast/"
REPO = Path(__file__).resolve().parent.parent
BUNDLED = REPO / "weather-forecast" / "scripts" / "telops.json"

# One entry: 100:["100.svg","500.svg","100","晴","CLEAR"]
# fields: day icon, night icon, icon class, Japanese name, English name.
# Only the Japanese name is kept. The icon class is not the leading digit of
# the code (102 "晴一時雨" is class 300, rain) and nothing here needs it.
ENTRY = re.compile(
    r'(\d{3}):\["[^"]*","[^"]*","\d{3}","((?:[^"\\]|\\.)*)","(?:[^"\\]|\\.)*"\]'
)


def extract(page: str) -> dict[str, str]:
    start = page.find("TELOPS={")
    if start < 0:
        raise SystemExit("TELOPS table not found in the page")
    end = page.find("}", start)
    body = page[start:end]
    table = {}
    for code, name in ENTRY.findall(body):
        # The page escapes non-ASCII as \uXXXX; decode via JSON string rules.
        table[code] = json.loads(f'"{name}"')
    if not table:
        raise SystemExit("TELOPS table found but no entries parsed")
    return table


def fetch_page() -> str:
    req = urllib.request.Request(PAGE_URL, headers={"User-Agent": "weather-forecast-maintenance"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-file", type=Path, help="read a saved copy of the page instead of fetching")
    ap.add_argument("--write", action="store_true", help="replace the bundled table")
    args = ap.parse_args()

    page = args.from_file.read_text(encoding="utf-8") if args.from_file else fetch_page()
    live = extract(page)

    bundled = {}
    if BUNDLED.exists():
        bundled = json.loads(BUNDLED.read_text(encoding="utf-8"))["telops"]

    added = sorted(set(live) - set(bundled))
    removed = sorted(set(bundled) - set(live))
    changed = sorted(c for c in set(live) & set(bundled) if live[c] != bundled[c])
    for c in added:
        print(f"+ {c} {live[c]}")
    for c in removed:
        print(f"- {c} {bundled[c]}")
    for c in changed:
        print(f"~ {c} {bundled[c]} -> {live[c]}")
    print(f"live: {len(live)} entries, bundled: {len(bundled)} entries")

    if args.write:
        doc = {
            "source": PAGE_URL,
            "retrieved": dt.date.today().isoformat(),
            "telops": dict(sorted(live.items())),
        }
        BUNDLED.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {BUNDLED.relative_to(REPO)}")
        return 0
    return 1 if (added or removed or changed) else 0


if __name__ == "__main__":
    sys.exit(main())
