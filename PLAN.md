# Wingman — Master Plan

A self-hosted Linux app that automates the painful parts of a job search:
finding relevant postings, filtering them, applying fast, and tracking
everything — while keeping the human (Andy) in charge of what actually gets
sent out under his name.

---

## 1. Goals and non-goals

### Goals

1. **Zero-effort discovery.** New postings matching Andy's criteria appear in
   the app automatically, deduplicated across sources, ranked best-first.
2. **Near-zero-effort applying.** For supported application systems, one
   click opens the application with every field already filled in from his
   profile; he reviews and submits in seconds. Opt-in full auto-submit where
   it is safe.
3. **Never lose track.** Every job has a pipeline state (inbox → interested →
   applied → interviewing → offer/rejected), notes, and follow-up reminders.
4. **AI as an amplifier, not a dependency.** With a Claude or ChatGPT
   *subscription* (no API key), the app scores matches, tailors resumes, and
   drafts cover letters. Without it, deterministic scoring and templates keep
   every feature functional.
5. **Instant credibility.** The first demo must work flawlessly: install with
   a few commands, add criteria, watch real jobs stream in ranked. That's the
   moment Andy believes in it.
6. **Usable from Android** via responsive web UI / PWA and push notifications.

### Non-goals (deliberate)

- **No LinkedIn/Indeed/Glassdoor automation.** Their ToS prohibit bots, they
  actively detect and ban accounts, and CAPTCHAs make it unreliable anyway.
  A banned LinkedIn account would hurt the search far more than manual
  applications there ever could. Wingman instead offers a *capture* flow:
  paste (or share from Android) any job URL and it becomes a tracked job with
  parsed details, tailored materials, and reminders.
- **No mass identical applications.** Blasting the same resume at 200 jobs
  gets flagged by ATS software and performs worse than 20 tailored
  applications. Wingman optimizes *quality per minute of Andy's time*.
- **No cloud service, no accounts, no telemetry.** Local-first forever.

---

## 2. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│ Wingman daemon (single Python process, systemd user service)│
│                                                             │
│  ┌──────────┐   ┌─────────┐   ┌────────┐   ┌─────────────┐  │
│  │ Scheduler │→ │ Source   │→ │ Dedupe │→ │ Scoring      │  │
│  │(APSched.) │  │ adapters │  │ + norm │  │ (heuristic   │  │
│  └──────────┘   └─────────┘   └────────┘  │  and/or AI)  │  │
│                                            └──────┬──────┘  │
│  ┌───────────────────── SQLite (WAL) ─────────────▼──────┐  │
│  │ jobs · sources · criteria · profile · applications ·  │  │
│  │ documents · reminders · events                        │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  FastAPI ──→ Web UI (Jinja2 + HTMX, responsive, PWA)        │
│         ──→ JSON API (future native clients)                │
│                                                             │
│  Apply engine (Playwright, visible browser, prefill+review) │
│  AI providers: claude-cli │ codex-cli │ none (heuristics)   │
│  Notifier: ntfy push · web UI inbox                         │
└─────────────────────────────────────────────────────────────┘
```

### Stack (chosen for reliability and hackability — Andy is a coder)

| Concern | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Andy can read/extend it; best ecosystem for this job |
| Packaging | `uv` | Fast, reproducible, one-command setup |
| Web/API | FastAPI + Uvicorn | Boring, solid, typed |
| DB | SQLite (WAL mode) | Zero admin, trivially backed up (one file) |
| Migrations | plain SQL files + tiny runner | No Alembic ceremony for a personal app |
| Scheduler | APScheduler | In-process polling, no cron dependency |
| UI | Jinja2 + HTMX + one CSS file | No node toolchain; responsive; PWA manifest |
| Form autofill | Playwright (Chromium, headed) | Reliable, debuggable, human-in-loop |
| AI | subprocess to `claude -p` / `codex exec` | Uses subscriptions, not API keys |
| Push | ntfy.sh (or self-hosted ntfy) | Free Android push, one HTTP POST |
| Service | systemd *user* unit | Starts on login, survives reboots |

Install story: `git clone … && cd wingman && ./install.sh` → prints the URL.
The installer creates the venv with `uv`, initializes the DB, installs the
Playwright browser (once M5 adds the Playwright dependency; skipped with a
notice before that), and enables the systemd user service.

---

## 3. Job sources (reliability-first)

Source adapters implement one interface: `fetch() -> list[RawPosting]`.
Each is independently toggleable and rate-limited; one broken source never
takes down the pipeline.

**Tier A — stable APIs/feeds, ship first:**

| Source | Access | Notes |
| --- | --- | --- |
| Remotive | public JSON API | remote jobs, category filters |
| RemoteOK | public JSON API | remote tech jobs |
| We Work Remotely | RSS | remote jobs by category |
| Hacker News "Who is hiring?" | Algolia HN API | monthly thread, parse top-level comments |
| Adzuna | free API key | broad aggregator, salary data, location search |
| USAJOBS | free API key | US federal jobs (if relevant) |
| Company watchlist | Greenhouse / Lever / Ashby / Workable public JSON boards | Andy lists companies he'd love to work for; Wingman polls their boards directly — highest-signal source there is |
| Generic RSS | any feed URL | escape hatch for niche boards |

**Tier B — capture, not crawl:** a "paste any job URL" box (and Android
share-target once the PWA is installed). Wingman fetches the page, extracts
title/company/description (JSON-LD `JobPosting` markup is common), and
creates a tracked job. This is how LinkedIn/Indeed/anything-else jobs enter
the system without ToS-violating automation.

Dedupe: normalize (company, title, location) + fuzzy match + canonical URL
hashing, since aggregators repost each other's listings.

---

## 4. Criteria and scoring

Andy defines criteria in the UI (multiple named profiles allowed, e.g.
"backend roles" vs "stretch roles"):

- must-have keywords / nice-to-have keywords / exclude keywords (with simple
  boolean syntax: `python AND (backend OR platform) NOT crypto`)
- remote / hybrid / onsite + acceptable locations & timezones
- salary floor (when posted), seniority range, company blocklist
- freshness window and per-source enable flags

*Phasing note (M2):* the criteria editor shipped with the boolean query,
nice-to-have/exclude terms, remote-only, salary floor, freshness window,
and company blocklist. Hybrid/onsite modes, location/timezone lists,
seniority ranges, and per-source profile flags are criteria-v2 — slated
for a later milestone once Andy's real usage shows which he needs
(keyword queries cover most of these today, e.g. `senior NOT staff`).

**Heuristic scorer (always on, no AI needed):** weighted keyword and skill
matching between the posting text and criteria + parsed resume terms
(the vault landed in M3; resume-term extraction needs PDF text parsing
and joins the scorer with the M4 AI-layer work), recency boost,
salary-fit boost, watchlist-company boost (landed in M6 with the watchlist
sources). Produces 0–100 plus human-readable "why" chips
(`+python +remote −agency`).

**AI scorer (optional, on top):** sends posting + resume summary to the
configured AI provider, gets back a 0–100 fit score, three-bullet rationale,
and red flags (ghost-job signals, contract-vs-perm mismatch, visa issues).
AI scores are cached per job; nothing is re-scored twice.

Ranked feed = the product. Inbox shows only jobs above Andy's threshold;
everything else is reachable but out of the way.

---

## 5. The apply engine (the edge)

### Profile vault
One-time setup: contact details, work authorization, links (GitHub/site),
resume PDF(s) (multiple variants allowed), default cover letter template,
and canned answers to the standard questions every ATS asks (EEO
questions get an explicit "decline to answer" default; salary expectations,
notice period, "why us?" boilerplate, etc.). Stored locally in SQLite.

### Tier 1 — Assisted apply (default, human-in-the-loop)
For postings hosted on **Greenhouse, Lever, Ashby, Workable** (a huge share
of tech-company applications), the Apply button launches a *visible*
Playwright Chromium window, navigates to the form, and fills every field it
can from the vault: name, email, links, resume upload, cover letter (AI-
tailored if available, template otherwise), canned answers matched to
question text. Unrecognized questions are highlighted for Andy. He reviews
and clicks Submit himself. Target: **under 30 seconds of human time per
application.** Wingman records the application, attaches the exact documents
sent, and schedules a follow-up reminder.

### Tier 2 — Auto-submit (opt-in, capped)
Per-ATS toggle. When a filled form has zero unrecognized required fields and
no CAPTCHA, Wingman may submit unattended, respecting a daily cap (default
5) and a per-company cooldown. Every auto-submission generates a
notification with a screenshot of the completed form. Anything ambiguous
falls back to Tier 1 and asks.

### Tier 3 — Everything else
Jobs from non-supported systems get a "prep pack" instead: tailored resume
variant suggestion, generated cover letter, and the canned answers ready to
copy — so even a manual application takes minutes, not an hour.

---

## 6. AI integration (subscription-based, optional)

Provider abstraction with three implementations behind one interface
(`complete(system, prompt, schema) -> dict`):

| Provider | Mechanism | Auth |
| --- | --- | --- |
| `claude` | subprocess: `claude -p --output-format json` (Claude Code CLI headless mode) | your existing Claude Pro/Max subscription — `claude login` once, no API key |
| `codex` | subprocess: `codex exec` (OpenAI Codex CLI) | ChatGPT subscription sign-in |
| `none` | heuristics + templates | — |

Rules: the app must degrade gracefully — if the CLI is missing, logged out,
rate-limited, or the subscription lapsed, Wingman logs it once, falls back to
`none`, and every feature keeps working. AI calls are queued and batched
(e.g. score the night's new jobs in one session) to be polite to
subscription limits. All AI output is cached in the DB.

AI-powered features, in priority order:
1. Job fit scoring + rationale + red flags
2. Cover letter drafting (from Andy's template voice + the posting)
3. Resume tailoring suggestions (which bullets to emphasize; never fabricate)
4. Interview prep dossier (company summary, likely questions, questions to ask)
5. Follow-up email drafts

---

## 7. Tracker, reminders, and the daily loop

- **Pipeline board:** inbox → interested → applied → interviewing → offer /
  rejected / ghosted. List view + phone-friendly cards, not a heavy kanban.
- **Reminders:** auto-created on apply (+7 days "follow up?"), on interview
  ("prep dossier ready"), and manual. Surfaced in UI and via ntfy push.
- **Daily digest (the Android killer feature):** every morning, a push
  notification: "6 new matches (2 ≥ 90), 1 follow-up due." Tapping opens the
  PWA. Andy triages from the couch in two minutes.
- **Metrics page:** applications/week, response rate by source and by score
  band — so he can see what's working and Wingman can prove its worth.
- **Events log:** every fetch, score, and submission is recorded; the app
  can always answer "what did you do on my behalf and when."

---

## 8. Data model (SQLite)

```
sources(id, kind, name, config_json, enabled, last_fetch_at, last_error)
jobs(id, source_id, dedupe_hash, url, title, company, location, remote,
     salary_min, salary_max, description, posted_at, first_seen_at,
     ats_kind, raw_json)
scores(job_id, scorer, score, rationale_json, scored_at)
criteria(id, name, config_json, enabled)
profile(key, value)                       -- vault: contact, links, defaults
documents(id, kind, name, path, is_default)  -- resumes, cover letters
answers(id, question_pattern, answer, kind)  -- canned ATS answers
applications(id, job_id, state, applied_at, method, docs_json, notes)
reminders(id, job_id, due_at, message, done)
events(id, ts, kind, payload_json)
```

One file, WAL mode, backed up by `wingman backup` (copies the DB + documents
directory to a tarball). Nothing precious ever lives only in memory.

---

## 9. Android story

1. **PWA (day one):** responsive UI + web app manifest + service worker for
   the app shell. Andy installs [Tailscale](https://tailscale.com) (free tier)
   on the Linux box and his phone, opens `http://wingman-box:8484` from
   anywhere, taps "Add to home screen." No ports exposed to the internet.
2. **ntfy push (day one):** daily digest and reminders as real push
   notifications via the ntfy Android app.
3. **Share-target (later):** the PWA registers as an Android share target, so
   "Share → Wingman" from any job page in any app captures it (Tier B flow).
4. A native app is unnecessary; this delivers the Android experience with
   zero extra codebases.

---

## 10. Security and privacy

- Binds to localhost + Tailscale interface only by default.
- Opening it wider (`WINGMAN_HOST=0.0.0.0`) is gated by an optional PIN
  (`WINGMAN_PIN`): non-loopback clients get a login screen; the session
  cookie is an HMAC keyed with a per-install secret file, mode 600.
- The vault holds PII (and nothing else does); export/delete is one command.
- No credentials for job boards are ever stored — Playwright uses a
  dedicated persistent browser profile where Andy logs in himself once,
  and the app never sees passwords.
- Secrets (Adzuna key, ntfy topic) live in `~/.config/wingman/env`, mode 600.

---

## 11. Milestones

Each milestone is a self-contained coding session with demoable output and
acceptance criteria (ready-to-paste build prompts live in
`docs/EXECUTION.md`). Order is chosen so the **first three milestones
produce the "watch it work before your eyes" demo**.

### M0 — Skeleton (small)
Repo scaffold: `uv` project, FastAPI app with health page, SQLite schema +
migration runner, config loading, `install.sh`, systemd user unit, Makefile
(`make dev`, `make test`), pytest wired up, CI (GitHub Actions: lint+test).
**Accept:** fresh clone → `./install.sh` → service running → UI loads.

### M1 — Ingestion (medium)
Source adapter interface + Remotive, RemoteOK, WWR-RSS, HN Who-is-hiring,
generic RSS. Normalization, dedupe, scheduler polling, events log, source
admin page (enable/disable, last fetch, errors).
**Accept:** enable sources → real jobs in DB within one poll cycle; dedupe
proven by fixture tests; one failing source doesn't stop the others.

### M2 — Criteria + heuristic scoring + feed UI (medium)
Criteria editor, boolean keyword engine, heuristic scorer with "why" chips,
ranked inbox UI (responsive), job detail page, hide/interested actions.
**Accept:** with Andy-like criteria, the inbox shows plausibly-ranked real
jobs with visible reasons. **← This is the demo-to-Andy moment.**

### M3 — Tracker + vault (medium)
Profile vault forms, documents upload, canned answers, pipeline states,
notes, reminders, paste-a-URL capture with JSON-LD parsing, backup command.
**Accept:** full lifecycle on a real job: capture → interested → applied
(manually marked) → reminder fires.

### M4 — AI layer (medium)
Provider abstraction, `claude` + `codex` + `none` providers, health check UI
("Claude: logged in ✓"), queued batch scoring, cover letter generation,
caching, graceful degradation tests (kill the CLI mid-run → app unaffected).
**Accept:** with `claude` logged in, new jobs get AI scores + rationale and
a one-click cover letter draft; with it logged out, everything still works.

### M5 — Apply engine (large)
Playwright setup, persistent browser profile, Greenhouse + Lever fillers
first (then Ashby, Workable), field-mapping via question-text matching to
the answers table, review-before-submit flow, application recording with
document snapshots, then opt-in auto-submit with caps + screenshots.
**Accept:** on live Greenhouse/Lever postings, prefill accuracy is high
enough that Andy only reviews; auto-submit demonstrably respects caps and
never submits with unanswered required fields.

### M6 — Polish + Android (small-medium)
PWA manifest + service worker + share-target, ntfy digests and reminder
pushes, metrics page, watchlist company boards (Greenhouse/Lever/Ashby
public JSON), Adzuna + USAJOBS adapters, docs pass.
**Accept:** installable on Android via Tailscale; morning digest arrives as
push; metrics render.

### Later / stretch
- Ghost-job detection heuristics (reposted >60 days, agency patterns)
- Contact finder (company team pages) + outreach draft for hiring managers
- Browser extension for one-click capture on desktop
- Weekly "state of the search" AI-written summary email
- Import LinkedIn saved-jobs export (their official data export, not scraping)

---

## 12. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| ATS markup changes break fillers | fillers are per-ATS modules with fixture tests; failures degrade to Tier 3 prep-pack, never crash |
| Source APIs change/vanish | adapters isolated + health-monitored; generic RSS + capture flow as universal fallback |
| CAPTCHAs on apply forms | headed browser + human present in Tier 1; auto-submit aborts to Tier 1 on any CAPTCHA |
| Subscription CLI auth expires | health check + one-tap "re-login" instructions; automatic fallback to heuristics |
| Andy doesn't adopt it | M2 demo is designed as the hook; daily digest keeps it in his pocket, not buried on a desktop |
| Over-automation harms his reputation | human-in-loop default, caps, per-company cooldown, full audit log |
