# AGENTS.md — weather-forecast

## Project summary

Claude Code Skill that answers weather-forecast questions for places in
Japan from the Japan Meteorological Agency (JMA) `bosai` JSON: today to the
day after tomorrow, the 7-day forecast, and the written overview. Invoked as
`/weather-forecast <place>` or by asking about the weather. A bundled
stdlib-only Python script resolves the place name, fetches the forecast and
normalizes it; the model reads only the script's JSON (ADR-0001). Warnings
and advisories are deliberately out of scope.

## Key commands

| Command | Purpose |
|---------|---------|
| `make check` (= `make test`) | Structural validation + script behaviour tests (offline, fixtures) |
| `make install` | Build the zip and unpack it into `~/.claude/skills/weather-forecast` |
| `make install DEST=<path>` | Install into a custom skills directory |
| `make uninstall` | Remove the installed copy |
| `make package` | Build `dist/weather-forecast-vX.Y.Z.zip` (zip root = skill folder) |
| `make check-upstream` | Online: re-verify shared files, shape, freshness, telop names, temperature points for all 58 regions |
| `make sync-telops` | Online: diff the bundled telop table against JMA's forecast page (`--write` via `python3 tools/sync_telops.py --write`) |
| `make clean` | Remove `dist/` |

## Directory structure

```
weather-forecast/
├── weather-forecast/            The skill — the only thing that ships
│   ├── SKILL.md                 Frontmatter + resolve → forecast → answer rules
│   └── scripts/
│       ├── jma_forecast.py      resolve / forecast; stdlib-only (3.9+)
│       └── telops.json          Telop number → weather name (JMA's documented table + page table)
├── tools/                       Online maintenance; never shipped, never in check
│   ├── check_upstream.py
│   └── sync_telops.py
├── tests/
│   ├── validate-skill.sh        Vendored byte-identical from .github/templates (ADR-006)
│   ├── run-script-tests.py      unittest suite, offline
│   └── fixtures/<release>/bosai/  Recorded JMA responses, same paths as the live URLs
├── docs/{en,ja}/adr/            ADR-0001
├── Makefile
├── README.md / README.ja.md
├── CHANGELOG.md
├── CLAUDE.md / AGENTS.md
└── LICENSE
```

## Gotchas

- **Read the documents first.** The bosai JSON has no API documentation of
  its own, but its content is defined by JMA's Disaster-Prevention XML
  explanatory documents (解説資料セット on xml.kishou.go.jp/tec_material.html):
  temperature slots, telop numbers, warning names. ADR-0001 separates what
  the documents say from what was observed. Before changing a rule, read the
  document, then observe the live data (`make check-upstream`, the official
  page in a browser). An early draft claimed tables were unpublished that
  were in fact in those documents.
- **Offline tests keep passing when JMA changes.** They pin the rules to the
  fixtures. `make check-upstream` is how a change is noticed; run it before a
  release.
- **Fixtures are served through the real fetch path**: tests pass
  `--base-url file://…/tests/fixtures/<release>/bosai/`. Keep the fixture
  tree's paths identical to the live URL paths. `--base-url` and `--now` are
  hidden test flags, not user features.
- **Area codes are unique only within a level**: `014030` is both an office
  and a class10. That is why `forecast` takes `--office` and `--area`
  separately — never collapse them into one argument.
- **Two offices share a neighbour's file** (`014030` → `014100`,
  `460040` → `460100`, `SHARED_FILE`). Their own URL answers 404.
- **`week_area.json` is a candidate list, not a mapping.** Most
  subdivisions have no weekly row of their own; the script lists the
  office's rows and marks `matched` only when a candidate is present. Do not
  "fix" this by guessing a row.
- **telops.json has two parts**: `official` (66 entries from the appendix
  workbook, refreshed with `tools/sync_telops.py --appendix <xlsx> --write`)
  wins over `page` (the forecast page's TELOPS, 118 entries). The page
  table's third field is an icon class, not the leading digit (102 晴一時雨
  is class 300). An unknown telop gets `weather: null`, never a name derived
  from its digits, and never the number itself in the answer.
- **Dates are relabelled against the current JST time**; past days and
  ended 6-hour slots are dropped (`end <= now`). JMA's own page keeps
  labelling by release time — the script deliberately differs.
- **Detailed temperatures follow the documented slots** (`temp_slot`):
  09:00 is the daytime high; 00:00 is the morning low only on a day after the
  release day. A 00:00 on the release day (05:00/11:00 releases) is today's
  24-hour maximum — reading it as a low is the trap.
- **Release times vary** (20:00 releases occur; detailed, weekly and overview
  carry separate times). Freshness is judged on the detailed release only.
- **Any failed fetch fails the whole call** — never return a partial result
  the model would read as "no such information".
- **Never show a code or an excuse in the answer** (weather-lens was
  withdrawn for exactly that). Implementation constraints belong in
  comments and ADRs.
- After editing SKILL.md or scripts, run `make install` to refresh the
  deployed copy, and remove `~/.claude/skills/weather-forecast` when done if
  the skill is registered through the desktop app (double registration).
- **Before every release run `make check-upstream` and `make sync-telops`**
  (online; offline tests cannot notice JMA changing). Both must exit 0.
- Releases follow the org checklist with `make package` in place of a binary
  build; before uploading, unzip the artifact and confirm
  `weather-forecast/SKILL.md` sits directly under the zip root and
  `tools/`/`tests/` are absent.

## Module path

Repository: `github.com/nlink-jp/weather-forecast`
