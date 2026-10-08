# weather-forecast

Claude Code Skill that answers weather-forecast questions for places in Japan
from the Japan Meteorological Agency's (JMA) latest official forecast. Ask in
plain words — 「明日の札幌の天気は？」, "Will it rain in Kyoto this weekend?" —
or invoke it as `/weather-forecast <place>`.

It answers with:

- **Today to the day after tomorrow** — weather, precipitation chance per
  6-hour slot, morning low and daytime high, wind (and waves on the coast)
- **The 7-day forecast** — weather, precipitation chance, reliability (A/B/C)
  and temperature ranges
- **The forecaster's overview** — the regional observatory's written
  explanation of the situation

Every answer names the area and the release time, and ends with the source
attribution JMA's terms require. No API key or account is needed.

Not covered: places outside Japan, weather warnings and advisories (the answer
points to JMA's warnings page instead), current observations, and rain radar.

## Install

Download `weather-forecast-vX.Y.Z.zip` from
[Releases](https://github.com/nlink-jp/weather-forecast/releases), then register it:

- **In Claude Desktop** — add the zip from the skill settings
  (Customize → Skills). Prefer this route; it survives changes to where
  skills are stored on disk.
- **Claude Code** — `unzip weather-forecast-vX.Y.Z.zip -d ~/.claude/skills/`,
  or into a project's `.claude/skills/` for a project-scoped install.

From a checkout:

```bash
make install
```

That builds the release zip and unpacks *that*. `make install DEST=/path/to/skills`
installs elsewhere; `make uninstall` removes it.

Requirements: `python3` (3.9+, stdlib only) and internet access to
`www.jma.go.jp` from where the skill runs. That holds in Claude Code (the
desktop app's Code tab and the CLI). The code sandbox behind claude.ai chat
limits outbound connections and is not expected to reach JMA.

## Usage

```
/weather-forecast 札幌
/weather-forecast 那覇 week
明日の京都は雨が降りますか？
週末の伊豆大島の天気を教えて
```

When a name matches several places (「府中」 is in Tokyo and Hiroshima), the
skill asks which one you mean.

The bundled script can also be run directly; it prints JSON:

```bash
python3 ~/.claude/skills/weather-forecast/scripts/jma_forecast.py resolve 札幌
python3 ~/.claude/skills/weather-forecast/scripts/jma_forecast.py forecast --office 016000 --area 016010
```

## Development

| Command | Purpose |
|---------|---------|
| `make check` (= `make test`) | Structural validation + script behaviour tests (offline) |
| `make install` | Build the zip and unpack it into `~/.claude/skills/weather-forecast` |
| `make package` | Build `dist/weather-forecast-vX.Y.Z.zip` (zip root = skill folder) |
| `make check-upstream` | Check the script's reading rules against what JMA serves today (online) |
| `make sync-telops` | Compare the bundled weather-name table with JMA's forecast page (online) |

## Documentation

- [ADR-0001: JMA forecast through a deterministic script](docs/en/adr/0001-jma-forecast-skill.md)
- [日本語ドキュメント](README.ja.md)

## Source

Forecast data: [Japan Meteorological Agency](https://www.jma.go.jp/bosai/forecast/),
used under JMA's website terms (Public Data License, version 1.0). The skill
reformats and summarizes it; answers say so.

## License

MIT
