# CLAUDE.md — weather-forecast

**Organization rules (mandatory): https://github.com/nlink-jp/.github/blob/main/CONVENTIONS.md**

See [`AGENTS.md`](AGENTS.md) for commands, structure, and gotchas.

## Non-negotiable rules

- **Docs in sync** — update `README.md` and `README.ja.md` in the same commit as behaviour changes.
- **Small, typed commits** — `feat:`, `fix:`, `docs:`, `test:`, `chore:`
- **`make check` before committing** — structural validation + script tests are this repo's test suite.
- **The `weather-forecast/` subdirectory is the distribution boundary** — only
  skill content goes inside it; `make package` ships exactly that directory
  (ADR-004). Maintenance tools live in `tools/` and never ship.
- **Bundled scripts are stdlib-only Python** — no third-party dependencies,
  ever; they must run on any host the skill is installed on.
- **Never show a raw code to the user** — a telop number, an area code or an
  explanation of why a name is missing must not reach the answer
  (ADR-0001 §5). Implementation constraints go in comments and ADRs.

## Communication Language

All communication between contributors and Claude Code is conducted in **Japanese**.
