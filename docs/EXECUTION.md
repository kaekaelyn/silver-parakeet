# Execution guide — building Wingman with AI coding sessions

The plan (PLAN.md) was produced with a frontier model (Fable). Implementation
is designed to run as a series of **scoped sessions with less expensive
models** (Sonnet is the right default; Haiku only for mechanical chores).
This file is the playbook for those sessions.

## Why this split works

Planning is where deep judgment matters (architecture, ToS constraints,
failure modes). Execution succeeds or fails on **scope and specification** —
a mid-tier model with a tight brief, fixtures, and acceptance criteria will
beat a frontier model with a vague one. So: every milestone below is sized
to fit in one session, states its acceptance criteria, and names its files.

## Rules for every build session

1. **One milestone per session.** Don't let a session "get ahead" into the
   next milestone; stop at green acceptance criteria.
2. **Start every session the same way:** the model must read `CLAUDE.md`,
   `PLAN.md`, and this file's section for the current milestone before
   writing code.
3. **Tests are the contract.** Each milestone lands with pytest coverage of
   its logic (adapters and fillers get fixture-based tests with recorded
   sample payloads — never tests that hit live services).
4. **Demo script per milestone.** Each session ends by updating
   `docs/DEMO.md` with the exact commands/clicks to show the milestone
   working. This doubles as manual QA and as the script for showing Andy.
5. **Review between sessions.** After each milestone, run a review pass
   (`/code-review` in Claude Code, or a fresh session prompted only to
   review the diff against the milestone's acceptance criteria) before
   starting the next.
6. **Commit style:** small commits, imperative subject, milestone tag in
   subject, e.g. `M1: add Remotive source adapter`.
7. **When stuck or when reality contradicts the plan** (an API is dead, an
   assumption is wrong): update PLAN.md in the same commit as the change.
   The plan is a living document; drift between plan and code is a bug.
8. **Escalate model, not scope.** If a Sonnet session fails a milestone
   twice, don't expand the prompt with hacks — rerun the milestone with a
   stronger model. M5 (apply engine) is the one milestone where starting
   with a stronger model is worth the cost.

## Session prompts

Paste these verbatim to start each session (adjust only the milestone tag).
They assume the session runs inside this repo with the branch checked out.

### M0 — Skeleton

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M0. Implement milestone
> M0 exactly as specified in PLAN.md §11: uv-managed Python 3.11+ project
> named `wingman`, FastAPI app serving a placeholder dashboard at
> `http://127.0.0.1:8484`, SQLite schema from PLAN.md §8 created by a
> minimal SQL-file migration runner, config loading from
> `~/.config/wingman/env`, `install.sh` (uv sync, db init, playwright
> chromium install — auto-skipped until the M5 playwright dependency lands,
> systemd user unit install+enable), Makefile with
> `dev`/`test`/`lint`, pytest + ruff configured, GitHub Actions workflow
> running lint+test. Acceptance: fresh clone → `./install.sh` → service
> running → UI loads; `make test` green. Update docs/DEMO.md. Do not start
> M1.

### M1 — Ingestion

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M1. Implement milestone
> M1: `Source` adapter protocol (`fetch() -> list[RawPosting]`), adapters
> for Remotive (JSON API), RemoteOK (JSON API), We Work Remotely (RSS),
> Hacker News Who-is-hiring (Algolia API, parse top-level comments), and
> generic RSS. Normalization into `jobs`, dedupe via
> normalized-(company,title,location) fuzzy hash + canonical URL, APScheduler
> polling with per-source intervals and jitter, `events` log rows for every
> fetch, `/sources` admin page (enable/disable, last fetch, last error).
> Every adapter gets fixture tests from recorded sample payloads in
> `tests/fixtures/` (no live HTTP in tests). A raising adapter must not
> affect other sources (test this). Acceptance per PLAN.md §11 M1. Update
> docs/DEMO.md. Do not start M2.

### M2 — Criteria + scoring + feed

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M2. Implement milestone
> M2: criteria editor UI backed by `criteria` table; boolean keyword engine
> supporting `AND`/`OR`/`NOT` and parentheses over posting title+description;
> heuristic scorer per PLAN.md §4 producing 0–100 plus "why" chips stored in
> `scores`; ranked inbox at `/` (responsive: cards on narrow screens, rows on
> wide) showing score, chips, age, source; job detail page; actions:
> interested / hide / open original. Threshold setting hides low scores from
> inbox. Unit-test the boolean engine and scorer thoroughly (these are the
> product's brain). Acceptance per PLAN.md §11 M2 — this milestone is the
> live demo, so polish the inbox rendering. Update docs/DEMO.md. Do not
> start M3.

### M3 — Tracker + vault

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M3. Implement milestone
> M3: profile vault forms writing to `profile`/`documents`/`answers`
> (resume upload to a documents dir, multiple variants, one default);
> pipeline states on `applications` with transitions from job detail and
> inbox; notes; reminders (auto +7d on applied, manual add) surfaced on the
> dashboard; paste-a-URL capture endpoint that fetches the page, parses
> JSON-LD JobPosting (fallback: title/meta heuristics), and creates a job;
> `wingman backup` CLI producing a tarball of DB + documents. Fixture tests
> for JSON-LD parsing. Acceptance per PLAN.md §11 M3. Update docs/DEMO.md.
> Do not start M4.

### M4 — AI layer

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M4. Implement milestone
> M4: `AIProvider` interface (`complete(system, prompt, json_schema) ->
> dict | None`); `ClaudeCLIProvider` shelling to `claude -p --output-format
> json` with timeout; `CodexCLIProvider` shelling to `codex exec`; `NullProvider`.
> Provider chosen in settings with live health check page (CLI present?
> logged in? last call ok?). Batch scoring queue: unscored jobs above
> heuristic threshold get AI score+rationale+red-flags (schema-validated),
> cached in `scores` with scorer='ai'. Cover letter generation on job detail
> (AI when available, else template substitution from vault). Degradation
> tests: provider binary missing / non-zero exit / garbage output ⇒ feature
> silently falls back, one event logged, app healthy. Never store API keys;
> subscriptions auth via the CLIs' own login. Acceptance per PLAN.md §11 M4.
> Update docs/DEMO.md. Do not start M5.

### M5 — Apply engine (use a strong model for this one)

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M5. Implement milestone
> M5 per PLAN.md §5: Playwright with a persistent Chromium profile dir;
> ATS detection from job URL/page (`ats_kind`); form fillers for Greenhouse
> and Lever first (Ashby, Workable after): fill contact fields, upload
> default resume, insert cover letter, answer questions by fuzzy-matching
> question text against `answers` (unmatched required fields highlighted,
> never guessed); headed review-before-submit flow is the default; on
> submit-confirmation, record the application with exact document snapshots
> and schedule the follow-up reminder. Then opt-in auto-submit: per-ATS
> toggle, daily cap (default 5), per-company cooldown, abort to headed mode
> on CAPTCHA or any unmatched required field, screenshot every
> auto-submission. Fillers are per-ATS modules tested against saved HTML
> fixtures of real forms. Acceptance per PLAN.md §11 M5. Update
> docs/DEMO.md. Do not start M6.

### M6 — Polish + Android

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M6. Implement milestone
> M6: PWA manifest + minimal service worker + Android share-target routed to
> the capture endpoint; ntfy notifier (topic from config) for daily digest
> (counts + top matches) and due reminders, scheduled morning digest; metrics
> page (applications/week, response rate by source and score band); company
> watchlist adapters polling Greenhouse/Lever/Ashby public JSON boards from a
> user-entered company list; Adzuna and USAJOBS adapters (keys from config,
> hidden in UI when absent); README/docs refresh with Tailscale setup guide.
> Acceptance per PLAN.md §11 M6. Update docs/DEMO.md.

## Suggested cadence

M0+M1 can land in a day; demo after M2 (that's the reveal to Andy — see
docs/DEMO.md when it exists). M3+M4 next; M5 deserves unhurried attention
and live testing on real postings; M6 closes the loop. Andy will have
opinions from the moment he sees M2 — from then on, treat him as the product
owner and fold his requests into milestone prompts.

---

## Session log & handoff notes (updated after M4)

**State: M0–M4 complete** on branch `claude/wingman-execution-guide-iaisef`
(never merged to a default branch yet — the repo's default branch is the
old planning branch; consider making this branch the default or merging).
139 tests green, lint clean, 4 migrations. Each of M0–M3 also had a
review-fix commit; **M4's review pass has NOT run yet** — do that first
(rule 5) before starting M5.

**Owner context (important):** the requester is non-technical and is
building Wingman as a gift for Andy. Two standing requirements beyond
PLAN.md:

1. **Every Andy-specific parameter must be enterable in the app UI** —
   no config-file editing for personal data. Honored so far (vault,
   criteria, AI provider choice, thresholds all in-app). Keep it that way
   for M5 (per-ATS toggles, caps) and M6 (ntfy topic, watchlist
   companies, Adzuna/USAJOBS keys — put them in a settings UI even though
   PLAN.md says config file; keys may fall back to env for headless
   installs but the UI path must exist).
2. **M6's Android/PWA milestone is the requester's acceptance test.**
   They have no Linux machine. Deliver: (a) an idiot-proof, zero-jargon
   guide for starting Wingman on any computer (Windows/Mac dev-mode:
   install Python or uv → two commands → open browser; no systemd), and
   (b) a phone guide (same Wi-Fi first, Tailscale optional later, add to
   home screen). Put both in docs/ and link from README. There is no
   standalone APK — the phone is a window to the server; say so plainly.
   Send screenshots (Playwright, chromium at /opt/pw-browsers) after each
   milestone — that's how the requester verifies progress.

**Working notes for the next session:**
- Sandbox blocks outbound HTTP to job boards (proxy 403). Use fixtures +
  local HTTP servers for E2E; note it honestly in DEMO.md. A REAL
  `claude` CLI exists in the sandbox (/opt/node22/bin/claude, works) —
  useful for live AI-path checks; codex CLI is absent.
- Review cadence: 8 finder subagents (Sonnet) per the /code-review
  skill, then verify candidates EMPIRICALLY (run the failing input)
  before fixing; every fix gets a regression test. Subagent usage limits
  were hit twice — if finders fail, do the angles inline yourself; that
  produced the best findings anyway.
- Deliberate decisions (don't re-litigate without cause): one
  applications row per job (history in events; docs_json snapshots);
  remote=NULL passes remote-only filters (tested, intentional);
  threshold lives in profile table; capture may fetch private-network
  URLs (single-user localhost app, size-capped).
- M5 (apply engine) is flagged in EXECUTION.md as the milestone worth a
  strong model. It needs: playwright dependency added (install.sh
  already conditionally installs chromium), headed review-before-submit
  as default, never-auto-submit guardrails from CLAUDE.md, fixture-based
  filler tests (saved Greenhouse/Lever HTML), per-ATS toggles/caps in
  the UI (see requirement 1). applications.docs_json already carries
  the letter; snapshot exact documents on submit.
- Version is still 0.1.0 in wingman/__init__.py; DEMO.md M0 mentions
  "migrations:2" and "14 passing" — historical text, harmless.
