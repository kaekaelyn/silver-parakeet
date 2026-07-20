-- Initial schema, from PLAN.md §8.

CREATE TABLE sources (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    name          TEXT NOT NULL,
    config_json   TEXT NOT NULL DEFAULT '{}',
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_fetch_at TEXT,
    last_error    TEXT
);

CREATE TABLE jobs (
    id            INTEGER PRIMARY KEY,
    source_id     INTEGER REFERENCES sources(id),
    dedupe_hash   TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT,
    location      TEXT,
    remote        INTEGER,
    salary_min    INTEGER,
    salary_max    INTEGER,
    description   TEXT,
    posted_at     TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    ats_kind      TEXT,
    raw_json      TEXT
);
CREATE INDEX idx_jobs_dedupe_hash ON jobs(dedupe_hash);
CREATE INDEX idx_jobs_first_seen_at ON jobs(first_seen_at);

CREATE TABLE scores (
    job_id         INTEGER NOT NULL REFERENCES jobs(id),
    scorer         TEXT NOT NULL,
    score          INTEGER NOT NULL,
    rationale_json TEXT,
    scored_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, scorer)
);

CREATE TABLE criteria (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE profile (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE documents (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    path       TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE answers (
    id               INTEGER PRIMARY KEY,
    question_pattern TEXT NOT NULL,
    answer           TEXT NOT NULL,
    kind             TEXT
);

CREATE TABLE applications (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    state      TEXT NOT NULL DEFAULT 'inbox',
    applied_at TEXT,
    method     TEXT,
    docs_json  TEXT,
    notes      TEXT
);

CREATE TABLE reminders (
    id      INTEGER PRIMARY KEY,
    job_id  INTEGER REFERENCES jobs(id),
    due_at  TEXT NOT NULL,
    message TEXT NOT NULL,
    done    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE events (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL DEFAULT (datetime('now')),
    kind         TEXT NOT NULL,
    payload_json TEXT
);
CREATE INDEX idx_events_ts ON events(ts);
