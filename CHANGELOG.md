# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-09

### Added

- Initial release: weather-forecast answers for places in Japan from the
  Japan Meteorological Agency's latest forecast — today to the day after
  tomorrow, the 7-day forecast and the written overview — with the area, the
  release time and the source attribution in every answer
  ([ADR-0001](docs/en/adr/0001-jma-forecast-skill.md)).
- `scripts/jma_forecast.py` (stdlib only): `resolve` finds forecast regions
  by place, municipality or region name; `forecast` prints the normalized
  forecast as JSON — dates and weekdays relative to the current Japan time,
  temperatures read by JMA's documented slots, weekly rows named by area,
  weather names from JMA's documented telop table.
- Maintenance commands `make check-upstream` and `make sync-telops` for
  checking the reading rules and the weather-name table against JMA.

### Not included

- Weather warnings and advisories; the answer points to JMA's warnings page.
