# CLAUDE.md — conventions for AI coding sessions in this repo

Wingman is a self-hosted, local-first job-search copilot for Linux.
Authoritative docs: `PLAN.md` (what to build and why), `docs/EXECUTION.md`
(the milestone you are building and its session prompt). Read both before
writing code. Build only the current milestone.

## Hard rules

- **Local-first, private:** no cloud services, no telemetry, no accounts.
  PII lives only in the vault tables and `~/.local/share/wingman/`.
- **No API keys for AI.** AI goes through installed CLIs (`claude -p`,
  `codex exec`) using the user's subscriptions. Every AI feature must work
  (degraded) when no provider is available — this is tested behavior, not
  an aspiration.
- **No scraping or automating LinkedIn/Indeed/Glassdoor.** Ever. The
  capture flow (paste/share a URL) is the supported path for those.
- **Never auto-submit** an application with unmatched required fields, on a
  CAPTCHA, over the daily cap, or when the per-ATS toggle is off.
- **Reliability over features:** one failing source/adapter/provider must
  never take down the daemon or other components.

## Tech conventions

- Python 3.11+, managed by `uv`; run everything via `make dev` / `make test`.
- FastAPI + Jinja2 + HTMX; no JS build step, no npm. One CSS file.
- SQLite in WAL mode; schema changes = new numbered SQL file in
  `migrations/`, applied by the built-in runner. Never edit old migrations.
- Tests: pytest; adapters/fillers/parsers are tested against recorded
  fixtures in `tests/fixtures/` — tests must never perform live HTTP.
- Lint: ruff (format + check) — keep it green.
- Type hints on public functions; pydantic models at API and adapter
  boundaries.
- Logging: structured, to stderr (journald captures it); user-meaningful
  happenings also go to the `events` table.

## Workflow

- Branch: work stays on the designated `claude/…` branch; push with
  `git push -u origin <branch>`.
- Commits: small, imperative, milestone-tagged (`M2: add boolean keyword
  engine`).
- Each milestone ends with: acceptance criteria met, `make test` green,
  `docs/DEMO.md` updated with how to demo it.
- If reality contradicts `PLAN.md`, fix the plan in the same commit.
