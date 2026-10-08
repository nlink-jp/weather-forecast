# ADR-0001: weather-forecast Skill — a Deterministic Script Normalizes the JMA Forecast; the Model Only Reads It

| Field | Value |
|-------|-------|
| Status | **Accepted** |
| Date | 2026-10-09 |
| Binds | weather-forecast |
| Decision makers | nlink-jp maintainers |
| Triggered by | A request for a skill that looks up weather forecasts. The earlier weather-lens (a JMA-sourced menu-bar app) was withdrawn on 2026-08-13 for poor UX |

## Context

We want to ask about the weather in Japan from inside a conversation. The
requirements were settled with the user:

- The **only data source is the Japan Meteorological Agency (JMA)** — Japan
  only, official, no API key
- Answers cover **today to the day after tomorrow**, the **7-day forecast**,
  and the **overview** (the observatory's written explanation)
- **Warnings and advisories are out of scope**; when asked, point to JMA's
  warnings page

The JSON under `www.jma.go.jp/bosai/` is what JMA's own site reads, and has
no API documentation of its own. Its content, however, is the same forecast
JMA publishes as Disaster-Prevention XML, whose **explanatory documents**
(the 解説資料セット on https://xml.kishou.go.jp/tec_material.html) define
what each element means. The design rests on those documents; the JSON
shape the documents do not cover was settled by observing live data
(CONVENTIONS "Design from the documentation"). That the bosai JSON maps onto
the XML is inferred — for instance, the temperature times of the 17:00
release match the documented slots — not guaranteed by any document.

### Facts from the documents

From the 2026-08-26 document set: 府県天気予報，地域時系列予報（Ｒ１）_解説資料,
府県週間天気予報_解説資料 and 府県天気予報・府県週間天気予報_解説資料付録.xlsx.

1. **Temperature has at most four slots**: 今日日中 (today 09:00, daytime
   maximum), 今日 (today 00:00 for 24 h, maximum), 明日朝 (tomorrow 00:00,
   morning minimum), 明日日中 (tomorrow 09:00, daytime maximum). Depending on
   the release time 今日 and 今日日中 are omitted. **There is no slot for this
   morning's minimum.**
2. **The telop-number table is official** (appendix sheet 天気予報用テロップ番号,
   66 entries, written like the detailed forecast's text: 晴れ時々くもり).
3. **The weekly forecast does not issue reliability for tomorrow and the day
   after**; tomorrow's precipitation chance and temperature belong to the
   prefectural forecast. A blank means "not issued in this product", not
   "missing".
4. **The warning/advisory type names are official too** (code management
   table, sheet 警報等情報要素コード管理表, updated 2024-10-31 for R06; it
   lists the codes weather-lens took to be unpublished).

### Facts observed (early 2026-10-09, all 58 forecast regions, one 17:00 release)

1. **Two of the 58 regions have no file of their own.** 十勝地方 `014030`
   and 奄美地方 `460040` answer 404 at `forecast/data/forecast/{code}.json`
   and live inside `014100` (Kushiro/Nemuro) and `460100` (Kagoshima)
   respectively. The overview behaves the same, and the host's overview
   covers both regions.
2. **Every forecast JSON has the same layout**: element 0 is the detailed
   forecast to the day after tomorrow (weather/wind/waves; 6-hour
   precipitation; temperature), element 1 the 7-day forecast. Region counts
   differ, and the eight landlocked prefectures carry no `waves`.
3. **The weekly forecast has telop numbers but no weather text.** The
   official forecast page inlines a `TELOPS` table (118 entries) that
   contains all 66 official ones, in abbreviated notation (晴時々曇). Its third
   field is an icon class, which differs from the code's leading digit in 65
   entries (102 晴一時雨 is in the rain class).
4. **Release times are not fixed.** The detailed forecast is normally issued
   at 05, 11 and 17, but Miyagi and Fukushima carried 20:00. Detailed and
   weekly forecasts record separate times, and the overview yet another
   (to the minute).
5. **"Today" shifts after midnight.** At 03:00 on 10/9 the latest release
   is 17:00 on 10/8, whose detailed forecast starts on the evening of 10/8.
   The official page keeps labelling relative to the release ("今夜 08日").
6. **Blanks arrive as empty strings** (temperature, reliability and
   precipitation on the first one or two weekly days).
7. **Weekly rows are per office.** The official `week_area.json` is a
   **candidate list** per subdivision; only candidates present in the
   current data count. 64 of 142 subdivisions hit one. Of the 78 that do
   not, 72 sit in offices with a single weekly row and are trivial; only six
   cannot be decided (伊豆諸島北部, 下北, 沿岸南部, 浜通り, 大隅,
   種子島・屋久島). The official page does not map subdivisions either: it
   lists all of the office's rows with their area names.
8. **Weekly temperature rows are in the same order as the weather rows**
   (all 63 rows, consistent with the pairs in `week_area.json`).
9. **Detailed temperature points** are listed per subdivision in
   `forecast_area.json` as candidates, including points absent from the
   current data (`63576`, `73136`).

## Decision

**Add the `weather-forecast` skill to skills-series. A bundled Python
script (stdlib only) does the fetching, place lookup and normalization
deterministically; the model writes the answer from the normalized JSON
and nothing else.**

### 1. The model never reads the raw data

The reading layer is thick: numeric codes, two parallel systems of areas
and points, empty strings, candidate lists, release-relative dates,
temperature slots with different meanings. Every misreading passes without
an error and comes back as plausible weather. The reading rules live in the
script and are pinned by tests. The model's judgement is limited to asking
back when a place name has several candidates, choosing the period to
answer, and wording the answer.

### 2. Script surface

One script, `scripts/jma_forecast.py`, with two subcommands.

- `resolve <place>` — searches the names at all four levels of `area.json`
  (offices, primary subdivisions, secondary groups, 1,805 municipalities)
  and returns each candidate as an (office, primary subdivision) pair.
  Candidates rank exact over prefix over contained; once any name matches
  exactly or by prefix, contained-only candidates are dropped (「京都」 does
  not offer 東京都). Several candidates are all returned and the model
  chooses (by asking the user). An office with a single subdivision is that
  subdivision.
- `forecast --office <code> [--area <code>]` — area codes repeat across
  levels (`014030` is both an office and a subdivision), so the two arrive
  as separate arguments. Either one not present in `area.json` is refused
  before any URL is built.

At run time it fetches five JMA files: `area.json`, `forecast_area.json`,
`week_area.json`, the forecast and the overview. Nothing is cached. **If
any one of them fails, the whole call fails** (`fetch_failed`, exit 2): a
partial result would let the model read a missing section as "there is no
such information".

### 3. Dates are relabelled against the current JST time

Each slot carries its date and a label relative to the current JST time
(今日 / 明日 / 明後日). Past days and 6-hour slots that have ended (end at
or before now) are dropped. `--now` overrides the clock for tests.

### 4. Temperatures are read by the documented slots

A 09:00 value is the daytime maximum; a 00:00 value **on a day after the
release day** is the morning minimum. A 00:00 value on the release day
(今日, the 24-hour maximum) is not read as a minimum. The point used is the
first of `forecast_area.json`'s candidates present in the current data.

### 5. The weekly forecast lists every row of the office by name

Like the official page, the output lists all weekly rows of the office with
their area names, and marks a row `matched: true` only when a
`week_area.json` candidate for the requested subdivision is present. Where
it cannot be decided the model names the row's own area when citing it — it
never picks one row by guesswork. Temperatures come from the row in the same
position. For offices sharing a file, only rows listed for the office in
`week_area.json` are shown (Kagoshima does not show Amami's row).

### 6. Telop names: the official table first, the page's table as fallback

`scripts/telops.json` holds copies of the official table (66 entries, with
the document and sheet name) and the forecast page's `TELOPS` table (118
entries), each with its retrieval date. Lookups prefer the official table and
fall back to the page's for numbers the document no longer lists.
`make sync-telops` compares against the forecast page; the official part is
refreshed with `--appendix` when a new document set appears.

**A number in neither table gets a `null` name — no guess.** The leading
digit only names the first weather (1xx starts with 晴), so 晴一時雨 would be
answered as 晴. The answer then gives that day's precipitation chance and
temperatures without a weather word. **Neither the number nor an
explanation of why a name is missing ever reaches the answer.** weather-lens
filled names absent upstream with "code + why we can't show it", let the
implementation's constraints dominate the UI, and was withdrawn for it. The
output JSON's weekly section carries no telop numbers either.

### 7. Shared files are an explicit table

`014030 → 014100` and `460040 → 460100` are a table in the script. Looking
for the host after a 404 at run time is rejected: the failure path would
become the normal path, and the number of requests would stop being
predictable.

### 8. Freshness is judged on the detailed forecast's release time

`stale: true` is set when the detailed forecast's release time is more than
**15 hours** old. The longest regular gap between detailed releases is 12
hours (17:00 → 05:00), and every update observed landed before the nominal
time. The weekly release interval is not stated in the documents and is
unverified (if it is longer, mornings would be judged stale by mistake), so
it is not used. The detailed, weekly and overview release times are all in
the output, and an answer cites the time of the part it answers from. A
retired endpoint once kept serving stale data with HTTP 200 (the old warning
path, frozen on 2026-05-28), so freshness is judged on the data, not on
reachability.

### 9. Warnings and advisories are not covered

A scope decision agreed with the user; when asked, the answer gives JMA's
warnings page URL. When it was agreed, the type-name table was described as
unpublished — that was wrong (document fact 4). The table is published, so
warnings can enter scope in a later version, on condition that the skill
keeps its own copy of the names with a maintenance command (the same shape
as the telop table).

### 10. Every answer carries the source and the processing note

JMA website content is reusable under the Public Data License (version 1.0),
which requires the source and, for edited or processed content, a statement
that it was processed. The script's output carries the attribution (with the
forecast page URL), and SKILL.md has the model end every answer with it as
given: 「出典：気象庁ホームページ（URL）を加工して作成」.

## Consequences

- The skill runs wherever it can execute `python3` and reach
  `www.jma.go.jp`. Claude Code (the desktop app's Code tab and the CLI)
  qualifies. A skill registered in the desktop app can also be invoked from
  chat; whether chat's execution environment reaches JMA is **unmeasured**.
- Tests ship recorded responses as fixtures and run offline under
  `make check` through the production fetch path (the base URL swapped for a
  `file://` one).
- The fixtures start from a single 17:00 release. 05:00 and 11:00 releases
  and rainy or snowy days are added as they become available; until then the
  temperature rule is pinned by the documented slots and unit tests.
- If JMA changes the structure or the tables, the offline tests keep
  passing. Changes are noticed by `make check-upstream` (shared files,
  layout, freshness, telop names and temperature points for every region)
  and `make sync-telops`, which **run before every release** (AGENTS.md
  release steps).
- Accepted residual risk: no response-size cap (the source is JMA; the
  timeout is 20 s). The overview's free text is passed to the model as the
  observatory wrote it.

## Alternatives considered

- **Let the model read the JSON with `WebFetch` or similar.** SKILL.md
  instructions would suffice, but the model would have to infer the whole
  reading layer every time, and misreadings would never be caught by a test.
- **Open-Meteo, alongside or alone.** It answers for places abroad, but even
  in Japan its values come from numerical models, not JMA's official
  forecast. Out of the agreed scope.
- **Extract the telop table from the official page at run time.** Always
  current, but a regex over minified JavaScript would run on every question
  and break with any page rewrite. A copy plus a maintenance command fails
  visibly.
- **Name unknown numbers from their leading digit.** The first draft. The
  leading digit names only the main weather and would answer weather with
  precipitation as 晴; rejected.
- **Pin one weekly row per subdivision.** Guesswork for the six undecidable
  subdivisions; the official page does not do it either.
- **Answer from whatever fetched successfully.** The model would read a
  missing section as "no such information"; rejected.
- **Current AMeDAS observations.** Adds missing-value and quality-flag
  handling. Out of the agreed scope.

## References

- JMA Disaster-Prevention XML technical documents (explanatory document set,
  code management table): https://xml.kishou.go.jp/tec_material.html
- JMA forecast page (source of the `TELOPS` table and the area tables):
  https://www.jma.go.jp/bosai/forecast/
- About the JMA website (Public Data License 1.0; requires the source and,
  for processed content, a statement saying so):
  https://www.jma.go.jp/jma/kishou/info/coment.html
