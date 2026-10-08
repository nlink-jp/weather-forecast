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
  `<office.name>・<area.name>` (or `<office.name>（全域）` when `area` is
  `null`) with one `matched_names` example, and wait. A region name such as
  東北 or 九州 returns its prefectures: ask which one. An `exact: true`
  candidate is the likeliest but does not settle it alone.
- **None** → if the user used a popular name, resolve once more with the
  official municipality name (伊豆大島 → 大島町, 屋久島 → 屋久島町,
  軽井沢 → 軽井沢町). Still none → ask for the nearest city or town name.
  A place outside Japan is out of scope: say so.

## 2. Get the forecast

```bash
python3 SKILL_DIR/scripts/jma_forecast.py forecast --office <office.code> [--area <area.code>]
```

Pass `--area` whenever the candidate has one. Exit status 2 prints
`{"error": ..., "message": ...}`:

- `fetch_failed` / `bad_response` → the forecast could not be retrieved
  or read. Tell the user it could not be retrieved right now and to try
  again; do not substitute anything, and do not show the message.
- `unknown_office` / `unknown_area` → go back to step 1.
- `bad_query` (from `resolve`) → ask the user for the place name.

## 3. Answer

Pick from the output what the question asks:

| Question | Read |
|---|---|
| today / tomorrow / the day after (今日・明日・明後日), rain, umbrella, temperature | `detailed[].days` (the one matching `area`; all of them for a whole office) |
| a weekday, the weekend, next week, a date 3+ days out | `weekly.rows[].days` |
| how the weather develops, why | `overview` |

A date present in `detailed` is answered from `detailed` whatever the
wording (a weekend that falls on 明日 included); `weekly` fills the dates and
values `detailed` lacks. Every day carries `weekday` (月…日) — use it to find
"the weekend" or "next Tuesday"; never work out weekdays yourself. When the
period asked runs past the last weekly date, answer the dates there are and
say up to which date the forecast goes (「予報は15日（木）まで」).

Rules for the answer:

- **Open with the place and the release**: the area name and the release
  time of the part you answer from — `report_datetime` for `detailed`,
  `weekly.report_datetime` for `weekly`, both when they differ and you use
  both — as 「◯月◯日◯時 気象庁発表」. Use the `label` (今日/明日/明後日),
  `date` and `weekday` the script gives; never recompute dates. Name the
  area of the part you answer from: `detailed[].area.name`, or the weekly
  row's `area.name`.
- **Precipitation**: `pops` are the remaining 6-hour slots of the release
  (`from`–`to`, `percent`). A day with no `pops` takes the
  weekly row's daily `pop` for that date. For "do I need an umbrella",
  take the highest of those for the period asked: 50% or more → take one;
  30–40% → a folding umbrella is worth carrying; 20% or less → probably not
  needed.
- **Temperature**: `temp_min` is the morning low, `temp_max` the daytime
  high. Always name the point they are for (「最高24℃（札幌）」): the
  detailed `temp_point`, or the weekly row's `temp_point` for values taken
  from `weekly` — the two can differ (十勝: 帯広 / 釧路). A `null` in `detailed` for a date means
  the detailed forecast issues none (JMA gives no low for the current
  morning, for example): take that date's value from the weekly row
  (below) if it has one, otherwise leave it out — and say nothing about
  the gap.
- **Weekly row**: use the row with `matched: true`; if none is matched and
  there is one row, use it; otherwise use the row whose area name covers
  the user's place (伊豆諸島北部 → 伊豆諸島) and always name that row's area
  and its `temp_point` (「伊豆諸島の週間予報（気温は八丈島）では…」) — never
  present its values as the user's town. The same naming applies when such
  a row fills a gap in `detailed`.
  Show ranges as 「26℃（24〜28℃）」 when the user asks about uncertainty or
  plans around a temperature. Reliability: A = 確度が高い, B = やや高い,
  C = やや低い; mention it wherever the day has one.
- **A field that is `null` is left out.** If a weekly `weather` is `null`,
  give that day's precipitation chance and temperatures without a weather
  word. Never show a code number, never explain why something is missing.
- **Wind and waves**: give `wind` for the day; give `wave` when the
  question touches the sea, islands, boats or the coast.
- **Overview**: summarize only what the text says; add no causes, places or
  numbers of your own. Quote the `headline` if present.
- **`stale: true`**: say the latest available release is from
  `report_datetime` and may be out of date, and give `source_url`.
- **Warnings and advisories (警報・注意報) are not covered.** If asked, say
  so and give `https://www.jma.go.jp/bosai/warning/#area_type=offices&area_code=<office.code>`
  (resolve the place for the code; candidates sharing one office need no
  question).
- **End every answer that shows forecast content with the `attribution`
  line exactly as given.** JMA's terms require the source and a note that
  the content was processed.

Keep it short: a few lines for a one-day question, a compact day-per-line
list for a week. Answer in the user's language; place and weather names
stay as JMA writes them when the user writes Japanese.
