---
name: weather-forecast
description: Answer weather-forecast questions for places in Japan from the Japan Meteorological Agency's latest official forecast — today to the day after tomorrow (weather, 6-hour precipitation chance, min/max temperature, wind), the 7-day forecast (with reliability and temperature ranges), and the forecaster's written overview. Use whenever the user asks about the weather in Japan, 天気予報, 今日・明日・明後日の天気, 週間予報, 週末の天気, 雨が降るか, 傘が要るか, 気温, 天気概況 — for a city, ward, town or prefecture name. Not for places outside Japan, weather warnings/advisories (警報・注意報), current observations, or rain radar.
argument-hint: "<place in Japan> [today|tomorrow|week]"
allowed-tools: Bash(python3 *)
---

# weather-forecast — JMA forecast for a place in Japan

The bundled script fetches the JMA forecast and does all of the reading:
place-name lookup, dates relative to now, blank values, the weekly telop
names. **Never fetch or read JMA's JSON yourself, and never answer weather
from memory** — every number in the answer comes from the script's output.

Below, `SKILL_DIR` is the directory containing this file.

## 1. Find the forecast region

```bash
python3 SKILL_DIR/scripts/jma_forecast.py resolve "<place name>"
```

Pass the place name in Japanese as the user would write it in Japan: turn
romaji or English into kanji/kana yourself (Sapporo → 札幌, Mt. Fuji area →
富士吉田 or 富士宮 — ask if unsure). A municipality, ward, region or
prefecture name all work.

The output lists `candidates`, each with `office` (forecast region) and
`area` (primary subdivision; `null` means the whole office).

- **One candidate** → use it.
- **Several** → if the user's words settle it (「東京都の府中」), take that
  one; otherwise ask which they mean, listing each as
  `<office.name>・<area.name>` with a `matched_names` example, and wait.
  An `exact: true` candidate is the likeliest but does not settle it alone.
- **None** → the place is not a Japanese place name JMA knows. Ask for the
  nearest city or town name. A place outside Japan is out of scope: say so.

## 2. Get the forecast

```bash
python3 SKILL_DIR/scripts/jma_forecast.py forecast --office <office.code> [--area <area.code>]
```

Pass `--area` whenever the candidate has one. Exit status 2 prints
`{"error": ..., "message": ...}`:

- `fetch_failed` / `bad_response` → JMA could not be reached. Tell the user
  the forecast could not be retrieved right now and to try again; do not
  substitute anything.
- `unknown_office` / `unknown_area` → go back to step 1.

## 3. Answer

Pick from the output what the question asks:

| Question | Read |
|---|---|
| today / tomorrow / the day after (今日・明日・明後日), rain, umbrella, temperature | `detailed[].days` (the one matching `area`; all of them for a whole office) |
| a weekday, the weekend, next week, a date 3+ days out | `weekly.rows[].days` |
| how the weather develops, why | `overview` |

Rules for the answer:

- **Open with the place and the release**: the area name and the release
  time of the part you answer from — `report_datetime` for `detailed`,
  `weekly.report_datetime` for `weekly` — as 「◯月◯日◯時 気象庁発表」. Use
  the `label` (今日/明日/明後日) and `date` the script gives; never
  recompute dates.
- **Precipitation**: `pops` are 6-hour slots still ahead (`from`–`to`,
  `percent`). For "do I need an umbrella", answer from the highest
  remaining percentage in the period asked.
- **Temperature**: `temp_min` is the morning low, `temp_max` the daytime
  high, at the named `temp_point`. A `null` in `detailed` for a date means
  the detailed forecast issues none (JMA gives no low for the current
  morning, for example): take that date's value from the weekly row
  (below) if it has one, otherwise leave it out — and say nothing about
  the gap.
- **Weekly row**: use the row with `matched: true`; if none is matched and
  there is one row, use it; otherwise name the row's own area when citing
  it (「伊豆諸島の週間予報では…」) — never present it as the user's town.
  Show ranges as 「26℃（24〜28℃）」 when the user asks about uncertainty or
  plans around a temperature. Reliability: A = 確度が高い, B = やや高い,
  C = やや低い; mention it for days 3+ out.
- **A field that is `null` is left out.** If a weekly `weather` is `null`,
  give that day's precipitation chance and temperatures without a weather
  word. Never show a code number, never explain why something is missing.
- **Overview**: summarize only what the text says; add no causes, places or
  numbers of your own. Quote the `headline` if present.
- **`stale: true`**: say the latest available release is from
  `report_datetime` and may be out of date, and give `source_url`.
- **Warnings and advisories (警報・注意報) are not covered.** If asked, say
  so and give `https://www.jma.go.jp/bosai/warning/#area_type=offices&area_code=<office.code>`.
- **End every answer with the `attribution` line exactly as given.** JMA's
  terms require the source and a note that the content was processed.

Keep it short: a few lines for a one-day question, a compact day-per-line
list for a week. Answer in the user's language; place and weather names
stay as JMA writes them when the user writes Japanese.
