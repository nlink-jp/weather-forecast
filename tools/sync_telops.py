#!/usr/bin/env python3
"""Rebuild or check the bundled telop table (number -> weather name).

The weekly forecast carries only telop numbers (e.g. "101"). Two JMA sources
name them (ADR-0001 §5):

- official: the sheet 「府県天気予報・府県週間天気予報（天気予報用テロップ番号）」 in
  府県天気予報・府県週間天気予報_解説資料付録.xlsx, inside the 解説資料セット
  zip on https://xml.kishou.go.jp/tec_material.html — the documented table,
  written the way the detailed forecast writes weather (晴れ時々くもり);
- page: the TELOPS table inlined in the forecast page's JavaScript, a
  superset that also names numbers the documented table no longer lists.

The script looks a number up in "official" first, then in "page".

Maintenance only: online, never part of ``make check``, never shipped.

Usage:
  python3 tools/sync_telops.py                      # diff the page part; exit 1 on a difference
  python3 tools/sync_telops.py --write              # rewrite the page part
  python3 tools/sync_telops.py --appendix X.xlsx --write   # also rewrite the official part
  python3 tools/sync_telops.py --from-file page.html ...   # use a saved page
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

PAGE_URL = "https://www.jma.go.jp/bosai/forecast/"
DOC_URL = "https://xml.kishou.go.jp/tec_material.html"
SHEET = "府県天気予報・府県週間天気予報（天気予報用テロップ番号）"
REPO = Path(__file__).resolve().parent.parent
BUNDLED = REPO / "weather-forecast" / "scripts" / "telops.json"

# One page entry: 100:["100.svg","500.svg","100","晴","CLEAR"]
# fields: day icon, night icon, icon class, Japanese name, English name.
# Only the Japanese name is kept. The icon class is not the leading digit of
# the code (102 "晴一時雨" is class 300, rain) and nothing here needs it.
ENTRY = re.compile(
    r'(\d{3}):\["[^"]*","[^"]*","\d{3}","((?:[^"\\]|\\.)*)","(?:[^"\\]|\\.)*"\]'
)


def extract_page(page: str) -> dict[str, str]:
    start = page.find("TELOPS={")
    if start < 0:
        raise SystemExit("TELOPS table not found in the page")
    body = page[start:page.find("}", start)]
    # The page escapes non-ASCII as \uXXXX; decode via JSON string rules.
    table = {code: json.loads(f'"{name}"') for code, name in ENTRY.findall(body)}
    if not table:
        raise SystemExit("TELOPS table found but no entries parsed")
    return table


def extract_appendix(path: Path) -> dict[str, str]:
    """Read the telop sheet of the appendix workbook with the stdlib only."""
    z = zipfile.ZipFile(path)
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S):
            strings.append(html.unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", si))))
    names = re.findall(r'<sheet [^>]*name="([^"]+)"', z.read("xl/workbook.xml").decode())
    if SHEET not in names:
        raise SystemExit(f"sheet {SHEET} not found")
    sheet = z.read(f"xl/worksheets/sheet{names.index(SHEET) + 1}.xml").decode()
    table = {}
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells = []
        for attrs, body in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
            v = re.search(r"<v>([^<]*)</v>", body or "")
            if v and 't="s"' in attrs:
                cells.append(strings[int(v.group(1))])
            elif v:
                cells.append(v.group(1))
            else:
                cells.append(html.unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", body or ""))))
        if len(cells) >= 2 and re.fullmatch(r"\d{3}", cells[0]):
            table[cells[0]] = cells[1]
    if not table:
        raise SystemExit("telop sheet found but no entries parsed")
    return table


def fetch_page() -> str:
    req = urllib.request.Request(PAGE_URL, headers={"User-Agent": "weather-forecast-maintenance"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def diff(label: str, live: dict[str, str], bundled: dict[str, str]) -> bool:
    added = sorted(set(live) - set(bundled))
    removed = sorted(set(bundled) - set(live))
    changed = sorted(c for c in set(live) & set(bundled) if live[c] != bundled[c])
    for c in added:
        print(f"{label} + {c} {live[c]}")
    for c in removed:
        print(f"{label} - {c} {bundled[c]}")
    for c in changed:
        print(f"{label} ~ {c} {bundled[c]} -> {live[c]}")
    print(f"{label}: live {len(live)}, bundled {len(bundled)}")
    return bool(added or removed or changed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-file", type=Path, help="read a saved copy of the page instead of fetching")
    ap.add_argument("--appendix", type=Path, help="解説資料付録.xlsx to take the official table from")
    ap.add_argument("--write", action="store_true", help="rewrite the bundled table")
    args = ap.parse_args()

    current = json.loads(BUNDLED.read_text(encoding="utf-8")) if BUNDLED.exists() else {}
    page = extract_page(args.from_file.read_text(encoding="utf-8") if args.from_file else fetch_page())
    changed = diff("page", page, current.get("page", {}).get("telops", {}))

    official = current.get("official")
    if args.appendix:
        table = extract_appendix(args.appendix)
        changed |= diff("official", table, (official or {}).get("telops", {}))
        official = {
            "source": DOC_URL,
            "document": f"{args.appendix.name} — sheet {SHEET}",
            "retrieved": dt.date.today().isoformat(),
            "telops": dict(sorted(table.items())),
        }
    if official:
        missing = sorted(set(official["telops"]) - set(page))
        if missing:
            print(f"official numbers absent from the page: {missing}")

    if not args.write:
        return 1 if changed else 0
    if not official:
        raise SystemExit("no official table yet: pass --appendix")
    doc = {
        "official": official,
        "page": {
            "source": PAGE_URL,
            "retrieved": dt.date.today().isoformat(),
            "telops": dict(sorted(page.items())),
        },
    }
    BUNDLED.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {BUNDLED.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
