#!/usr/bin/env python3
"""Check the skill's reading rules against what JMA serves today.

The offline tests pin the rules to recorded responses; they keep passing when
JMA changes. This tool is how a change is noticed (ADR-0001 §5-§7). For every
forecast region it checks that

- a region in SHARED_FILE still has no file of its own, and its subdivisions
  are still inside the neighbour's file; every other region has its own file;
- the forecast still has the two-report shape the script reads;
- the release is fresh (not older than the script's stale threshold);
- every telop number in the data has a name in the bundled table;
- every primary subdivision still finds a temperature point.

Maintenance only: online (about 120 requests, paced), never part of
``make check``, never shipped. Exit 1 on any finding.

Usage: python3 tools/check_upstream.py
"""

from __future__ import annotations

import datetime as dt
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "weather-forecast" / "scripts"))
import jma_forecast as jf  # noqa: E402

PACE = 0.3  # seconds between requests


def status(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "weather-forecast-maintenance"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    fetch = jf.http_fetcher(jf.BASE_URL)
    now = dt.datetime.now(jf.JST)
    area = fetch("common/const/area.json")
    forecast_area = fetch("forecast/const/forecast_area.json")
    findings: list[str] = []

    for office in sorted(area["offices"]):
        time.sleep(PACE)
        own = status(f"{jf.BASE_URL}forecast/data/forecast/{office}.json")
        if office in jf.SHARED_FILE and own != 404:
            findings.append(f"{office}: listed as shared but its own file answers {own}")
        if office not in jf.SHARED_FILE and own != 200:
            findings.append(f"{office}: own file answers {own}; add it to SHARED_FILE?")
            continue

        file_code = jf.SHARED_FILE.get(office, office)
        time.sleep(PACE)
        data = fetch(f"forecast/data/forecast/{file_code}.json")
        if len(data) < 2 or len(data[0]["timeSeries"]) < 3 or len(data[1]["timeSeries"]) < 2:
            findings.append(f"{office}: forecast shape changed")
            continue

        published = jf.parse_time(data[0]["reportDatetime"])
        if now - published > jf.STALE_AFTER:
            findings.append(f"{office}: release {data[0]['reportDatetime']} is stale")

        detailed = {a["area"]["code"] for a in data[0]["timeSeries"][0]["areas"]}
        missing = set(area["offices"][office]["children"]) - detailed
        if missing:
            findings.append(f"{office}: subdivisions {sorted(missing)} not in {file_code}.json")

        for ts in (data[0]["timeSeries"][0], data[1]["timeSeries"][0]):
            for a in ts["areas"]:
                for code in a.get("weatherCodes", []):
                    if code and code not in jf.TELOPS:
                        findings.append(f"{office}: telop {code} has no name; run make sync-telops")

        temp_points = {a["area"]["code"] for a in data[0]["timeSeries"][2]["areas"]}
        for e in forecast_area.get(office, []):
            if not any(p in temp_points for p in e["amedas"]):
                findings.append(f"{office}/{e['class10']}: no temperature point present")

    for f in sorted(set(findings)):
        print(f)
    print(f"checked {len(area['offices'])} regions: {len(set(findings))} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
