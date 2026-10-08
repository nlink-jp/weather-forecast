#!/usr/bin/env python3
"""Fetch and normalize a Japan Meteorological Agency forecast (stdlib only).

The JMA ``bosai`` JSON has no published API documentation; every reading rule
below was established by observing the live data and the official forecast
page (docs/*/adr/0001). The model never reads the raw JSON — it reads only
what this script prints.

Usage:
  jma_forecast.py resolve <place name>
  jma_forecast.py forecast --office <code> [--area <code>]

Both print one JSON document on stdout. Exit status is 0 on success and 2 on
an error, in which case the JSON carries ``error`` and ``message``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

JST = dt.timezone(dt.timedelta(hours=9), "JST")
BASE_URL = "https://www.jma.go.jp/bosai/"
PAGE_URL = "https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={office}"
_TELOP_TABLES = json.loads((Path(__file__).with_name("telops.json")).read_text(encoding="utf-8"))
# The documented table wins; the forecast page's table names the numbers the
# documented one no longer lists (ADR-0001 §5).
TELOPS = {**_TELOP_TABLES["page"]["telops"], **_TELOP_TABLES["official"]["telops"]}

# Two forecast regions have no file of their own: their forecast and overview
# are published inside a neighbour's file (observed 2026-10-09: the own URL
# answers 404). tools/check_upstream.py re-verifies this against all regions.
SHARED_FILE = {
    "014030": "014100",  # 十勝地方 -> 釧路・根室地方
    "460040": "460100",  # 奄美地方 -> 鹿児島県（奄美地方除く）
}

# Releases come at 05, 11 and 17 JST; the longest regular gap is 12 hours.
STALE_AFTER = dt.timedelta(hours=15)

RELATIVE_LABELS = {0: "今日", 1: "明日", 2: "明後日"}

Fetch = Callable[[str], Any]


class ForecastError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


# --------------------------------------------------------------------------
# Fetching


def http_fetcher(base_url: str) -> Fetch:
    """Return fetch(path) -> parsed JSON, reading under base_url.

    base_url may be a file:// URL — the tests point it at recorded responses.
    """

    def fetch(path: str) -> Any:
        url = base_url + path
        req = urllib.request.Request(url, headers={"User-Agent": "weather-forecast-skill"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ForecastError("fetch_failed", f"{url}: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ForecastError("fetch_failed", f"{url}: {e}") from e
        except json.JSONDecodeError as e:
            raise ForecastError("bad_response", f"{url}: not JSON") from e

    return fetch


# --------------------------------------------------------------------------
# Small readers


def parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).astimezone(JST)


def blank_to_none(v: Any) -> Any:
    # JMA writes "no value" as an empty string (first days of the weekly
    # forecast, past 6-hour slots).
    return None if v in ("", None) else v


def to_int(v: Any) -> int | None:
    v = blank_to_none(v)
    return None if v is None else int(v)


def tidy(text: str | None) -> str | None:
    """Collapse JMA's ideographic-space word separators to single spaces."""
    if text is None:
        return None
    return " ".join(text.replace("　", " ").split())


def telop_name(code: str | None) -> str | None:
    # An unknown number gets no name rather than a guess: the leading digit
    # names only the first weather (1xx starts with 晴) and would turn
    # "晴一時雨" into "晴". The number itself never reaches the answer.
    return TELOPS.get(code) if code else None


def relative_label(day: dt.date, today: dt.date) -> str | None:
    return RELATIVE_LABELS.get((day - today).days)


def normalize(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


# --------------------------------------------------------------------------
# resolve


LEVELS = ("offices", "class10s", "class15s", "class20s")


def office_and_class10(area: dict, level: str, code: str) -> tuple[str, str | None]:
    """Walk parents up to (office, class10).

    class10 is None for an office with several subdivisions (the whole
    region). An office with exactly one subdivision is that subdivision, so
    "十勝" does not come back twice.
    """
    if level == "offices":
        children = area["offices"][code]["children"]
        return code, children[0] if len(children) == 1 else None
    if level == "class20s":
        code = area["class20s"][code]["parent"]
        level = "class15s"
    if level == "class15s":
        code = area["class15s"][code]["parent"]
    return area["class10s"][code]["parent"], code


def match_rank(q: str, name: str) -> int:
    """0 exact, 1 prefix, 2 contained."""
    n = normalize(name)
    return 0 if n == q else 1 if n.startswith(q) else 2


def resolve(area: dict, query: str, limit: int = 20) -> dict:
    q = normalize(query)
    if not q:
        raise ForecastError("bad_query", "empty place name")

    seen: dict[tuple[str, str | None], dict] = {}
    for level in LEVELS:
        for code, entry in area[level].items():
            name = entry["name"]
            if q not in normalize(name):
                continue
            office, class10 = office_and_class10(area, level, code)
            key = (office, class10)
            if key in seen:
                seen[key]["matched_names"].append(name)
                continue
            seen[key] = {
                "office": {"code": office, "name": area["offices"][office]["name"]},
                "area": None
                if class10 is None
                else {"code": class10, "name": area["class10s"][class10]["name"]},
                "matched_names": [name],
            }

    if not seen:
        # A region name such as "北海道" or "関東甲信" names a center, not a
        # forecast region: offer the forecast regions under it.
        for code, entry in area["centers"].items():
            if q in normalize(entry["name"]):
                for office in entry["children"]:
                    seen[(office, None)] = {
                        "office": {"code": office, "name": area["offices"][office]["name"]},
                        "area": None,
                        "matched_names": [entry["name"]],
                    }

    candidates = list(seen.values())
    for c in candidates:
        c["rank"] = min(match_rank(q, n) for n in c["matched_names"])
        c["exact"] = c["rank"] == 0
        c["matched_names"] = sorted(set(c["matched_names"]))[:5]
    # A name that merely contains the query ("京都" in 東京都, "大阪市" in
    # 東大阪市) is noise once some name starts with it.
    if any(c["rank"] < 2 for c in candidates):
        candidates = [c for c in candidates if c["rank"] < 2]
    # Exact, then prefix; ties keep area.json order (stable sort).
    candidates.sort(key=lambda c: c["rank"])
    for c in candidates:
        del c["rank"]
    return {
        "query": query,
        "total": len(candidates),
        "candidates": candidates[:limit],
    }


# --------------------------------------------------------------------------
# forecast


def first_present(candidates: list[str], present: set[str]) -> str | None:
    return next((c for c in candidates if c in present), None)


def temp_slot(t: dt.datetime, release_day: dt.date) -> str | None:
    """Which temperature a detailed-forecast time stands for.

    JMA's prefectural forecast defines up to four slots (解説資料, 府県天気予報
    ※2): 今日日中 = today 09:00 (日中の最高気温), 今日 = today 00:00 for 24 h
    (最高気温), 明日朝 = tomorrow 00:00 (朝の最低気温), 明日日中 = tomorrow
    09:00. There is no "this morning's low": a 00:00 on the release day is a
    maximum and must not be read as the minimum.
    """
    if t.hour == 9:
        return "temp_max"
    if t.hour == 0 and t.date() > release_day:
        return "temp_min"
    return None


def build_detailed(report: dict, office_area_codes: list[str], temp_points: dict[str, list[str]],
                   now: dt.datetime) -> list[dict]:
    """Today..day after tomorrow, one entry per primary subdivision."""
    today = now.date()
    release_day = parse_time(report["reportDatetime"]).date()
    weather_ts, pop_ts, temp_ts = report["timeSeries"][:3]

    weather_days = [parse_time(t).date() for t in weather_ts["timeDefines"]]
    pop_slots = [parse_time(t) for t in pop_ts["timeDefines"]]
    temp_times = [parse_time(t) for t in temp_ts["timeDefines"]]
    temps_by_point = {a["area"]["code"]: a for a in temp_ts["areas"]}
    pops_by_area = {a["area"]["code"]: a for a in pop_ts["areas"]}

    out = []
    for a in weather_ts["areas"]:
        code = a["area"]["code"]
        if code not in office_area_codes:
            continue
        days: dict[dt.date, dict] = {}
        for i, day in enumerate(weather_days):
            if day < today:
                continue
            days[day] = {
                "date": day.isoformat(),
                "label": relative_label(day, today),
                "weather": tidy(a["weathers"][i]) if "weathers" in a else None,
                "wind": tidy(a["winds"][i]) if "winds" in a else None,
                "wave": tidy(a["waves"][i]) if "waves" in a else None,
                "pops": [],
                "temp_min": None,
                "temp_max": None,
            }

        pops = pops_by_area.get(code, {}).get("pops", [])
        for i, start in enumerate(pop_slots):
            end = start + dt.timedelta(hours=6)
            # A slot that has ended by now is history, not forecast. The
            # comparison is <=: a slot ending exactly now is over.
            if end <= now or start.date() not in days:
                continue
            days[start.date()]["pops"].append({
                "from": start.strftime("%H:%M"),
                "to": end.strftime("%H:%M") if end.date() == start.date() else "24:00",
                "percent": to_int(pops[i]) if i < len(pops) else None,
            })

        point = first_present(temp_points.get(code, []), set(temps_by_point))
        if point is not None:
            temps = temps_by_point[point]["temps"]
            for i, t in enumerate(temp_times):
                key = temp_slot(t, release_day)
                if key and t.date() in days:
                    days[t.date()][key] = to_int(temps[i])

        out.append({
            "area": a["area"],
            "temp_point": temps_by_point[point]["area"]["name"] if point else None,
            "days": list(days.values()),
        })
    return out


def build_weekly(report: dict, office_week_codes: list[str], matched_code: str | None,
                 now: dt.datetime) -> dict:
    """Seven-day forecast rows of the office, as the official page lists them."""
    today = now.date()
    wx_ts, temp_ts = report["timeSeries"][:2]
    dates = [parse_time(t).date() for t in wx_ts["timeDefines"]]

    pairs = list(zip(wx_ts["areas"], temp_ts["areas"]))
    rows = [p for p in pairs if p[0]["area"]["code"] in office_week_codes] or pairs

    out = []
    for wx, temp in rows:
        days = []
        for i, day in enumerate(dates):
            if day < today:
                continue
            days.append({
                "date": day.isoformat(),
                "label": relative_label(day, today),
                "weather": telop_name(blank_to_none(wx["weatherCodes"][i])),
                "pop": to_int(wx["pops"][i]),
                "reliability": blank_to_none(wx["reliabilities"][i]),
                "temp_min": to_int(temp["tempsMin"][i]),
                "temp_min_range": range_or_none(temp["tempsMinLower"][i], temp["tempsMinUpper"][i]),
                "temp_max": to_int(temp["tempsMax"][i]),
                "temp_max_range": range_or_none(temp["tempsMaxLower"][i], temp["tempsMaxUpper"][i]),
            })
        out.append({
            "area": wx["area"],
            "matched": wx["area"]["code"] == matched_code,
            "temp_point": temp["area"]["name"],
            "days": days,
        })
    return {"report_datetime": report["reportDatetime"], "rows": out}


def range_or_none(lower: Any, upper: Any) -> list[int] | None:
    lo, hi = to_int(lower), to_int(upper)
    return None if lo is None or hi is None else [lo, hi]


def forecast(fetch: Fetch, office: str, area_code: str | None, now: dt.datetime) -> dict:
    area = fetch("common/const/area.json")
    if office not in area["offices"]:
        raise ForecastError("unknown_office", f"no forecast region {office}")
    office_entry = area["offices"][office]
    children = office_entry["children"]
    if area_code is not None and area_code not in children:
        raise ForecastError("unknown_area", f"{area_code} is not a subdivision of {office}")
    wanted = [area_code] if area_code else children

    forecast_area = fetch("forecast/const/forecast_area.json")
    week_area = fetch("forecast/const/week_area.json")
    file_code = SHARED_FILE.get(office, office)
    data = fetch(f"forecast/data/forecast/{file_code}.json")
    overview = fetch(f"forecast/data/overview_forecast/{file_code}.json")

    temp_points = {e["class10"]: e["amedas"] for e in forecast_area.get(office, [])}
    detailed = build_detailed(data[0], wanted, temp_points, now)

    week_entries = week_area.get(office, [])
    office_week_codes = [e["week"] for e in week_entries]
    present = {a["area"]["code"] for a in data[1]["timeSeries"][0]["areas"]}
    matched = None
    if area_code is not None:
        # week_area.json lists candidates per subdivision; only one present in
        # today's data counts. Most subdivisions have none (ADR-0001 §4).
        matched = first_present([e["week"] for e in week_entries if e["srf"] == area_code], present)
    weekly = build_weekly(data[1], office_week_codes, matched, now)

    report_time = parse_time(data[0]["reportDatetime"])
    page = PAGE_URL.format(office=office)
    return {
        "office": {"code": office, "name": office_entry["name"]},
        "area": None if area_code is None else {"code": area_code, "name": area["class10s"][area_code]["name"]},
        "now": now.isoformat(timespec="minutes"),
        "report_datetime": data[0]["reportDatetime"],
        "publishing_office": data[0]["publishingOffice"],
        "stale": now - report_time > STALE_AFTER,
        "detailed": detailed,
        "weekly": weekly,
        "overview": {
            "report_datetime": overview.get("reportDatetime"),
            "target_area": overview.get("targetArea"),
            "headline": blank_to_none(tidy(overview.get("headlineText"))),
            "text": (overview.get("text") or "").strip() or None,
        },
        "source_url": page,
        "attribution": f"出典：気象庁ホームページ（{page}）を加工して作成",
    }


# --------------------------------------------------------------------------
# CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="JMA forecast for the weather-forecast skill")
    ap.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    ap.add_argument("--now", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="find forecast regions by place name")
    r.add_argument("name")
    f = sub.add_parser("forecast", help="forecast for a region")
    f.add_argument("--office", required=True, help="forecast region code (from resolve)")
    f.add_argument("--area", help="primary subdivision code (from resolve)")
    args = ap.parse_args(argv)

    now = parse_time(args.now) if args.now else dt.datetime.now(JST)
    fetch = http_fetcher(args.base_url)
    try:
        if args.cmd == "resolve":
            result = resolve(fetch("common/const/area.json"), args.name)
        else:
            result = forecast(fetch, args.office, args.area, now)
    except ForecastError as e:
        print(json.dumps({"error": e.error, "message": e.message}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
