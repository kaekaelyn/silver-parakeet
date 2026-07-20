# Wingman 🪽

A personal, self-hosted job-search copilot for Linux. Built as a gift.

Wingman watches job boards so you don't have to. It pulls new postings from
sources with stable APIs, filters and ranks them against *your* criteria and
resume, pre-fills applications so submitting takes seconds instead of an hour,
tracks every application through the pipeline, and nudges you when it's time
to follow up. Optional AI (via a Claude or ChatGPT subscription you already
have — no API keys, no per-token billing) tailors cover letters and scores
matches; without AI, rule-based scoring keeps everything working.

**Design promises:**

- **Runs entirely on your machine.** SQLite database, no cloud account, your
  resume and personal data never leave your computer except inside the
  applications you choose to send.
- **Reliable over flashy.** Job sources are APIs and RSS feeds that don't
  break, not fragile scrapers. Automation that would get accounts banned
  (LinkedIn/Indeed bots) is deliberately out of scope.
- **You stay in control.** The default apply flow pre-fills everything and
  lets you review before submit. Full auto-submit is opt-in, per source,
  with daily caps.
- **Works from your phone.** The UI is a responsive web app (installable as
  a PWA on Android); daily digests arrive as push notifications via ntfy.

## Documents

| File | What it is |
| --- | --- |
| [docs/RUNNING.md](docs/RUNNING.md) | **Start here:** plain-language guide to running Wingman (Linux/Windows/Mac) |
| [docs/PHONE.md](docs/PHONE.md) | Using Wingman from your phone: home-screen install, Tailscale, push notifications |
| [docs/DEMO.md](docs/DEMO.md) | Per-milestone demo scripts (doubles as manual QA) |
| [PLAN.md](PLAN.md) | The master plan: goals, architecture, features, milestones |
| [docs/EXECUTION.md](docs/EXECUTION.md) | How to build it: session-sized tasks with ready-to-paste prompts |
| [CLAUDE.md](CLAUDE.md) | Conventions for AI coding sessions working in this repo |

## Status

M0–M6 complete: ingestion from six kinds of source (plus a company
watchlist and keyed Adzuna/USAJOBS boards), ranked scoring with criteria
profiles, tracker + vault + capture, optional AI scoring and cover
letters, the guarded apply engine, Android PWA with share-target, ntfy
push digests, and a metrics page. See docs/DEMO.md to try each piece.

## Quick start

```sh
git clone <repo-url> wingman && cd wingman
./install.sh          # uv sync, db init, systemd user service
# open http://127.0.0.1:8484
```

Not on Linux, or allergic to terminals? [docs/RUNNING.md](docs/RUNNING.md)
walks through Windows and Mac in plain language, and
[docs/PHONE.md](docs/PHONE.md) puts it on your phone.

Development: `make dev` (auto-reload server), `make test`, `make lint`.
