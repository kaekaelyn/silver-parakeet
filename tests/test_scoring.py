import json
import sqlite3
from datetime import UTC, datetime, timedelta

from wingman import scoring
from wingman.boolquery import compile_query
from wingman.scoring import Criteria


def _insert_job(conn: sqlite3.Connection, **overrides) -> sqlite3.Row:
    fields = {
        "source_id": None,
        "title": "Senior Python Engineer",
        "company": "Acme",
        "location": "Remote",
        "remote": 1,
        "salary_min": None,
        "salary_max": None,
        "description": "Build backend services in Python.",
        "posted_at": datetime.now(UTC).isoformat(),
        "url": f"https://example.com/{overrides.get('title', 'job')}",
        "dedupe_hash": overrides.get("url", str(overrides)),
    }
    fields.update(overrides)
    cursor = conn.execute(
        """INSERT INTO jobs (source_id, title, company, location, remote, salary_min,
                             salary_max, description, posted_at, url, dedupe_hash)
           VALUES (:source_id, :title, :company, :location, :remote, :salary_min,
                   :salary_max, :description, :posted_at, :url, :dedupe_hash)""",
        fields,
    )
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()


def make_criteria(**kwargs) -> Criteria:
    defaults = {"id": 1, "name": "Test"}
    if "query" in kwargs and isinstance(kwargs["query"], str):
        kwargs["query"] = compile_query(kwargs["query"])
    return Criteria(**{**defaults, **kwargs})


def test_query_match_scores_and_chips(conn: sqlite3.Connection) -> None:
    job = _insert_job(conn)
    score, chips = scoring.score_job(job, make_criteria(query="python AND backend"))
    assert score >= 40 + 15  # match + fresh
    assert "+python" in chips and "+backend" in chips and "+new" in chips


def test_no_query_match_scores_zero(conn: sqlite3.Connection) -> None:
    job = _insert_job(conn, title="Java Developer", description="Spring shop.")
    score, chips = scoring.score_job(job, make_criteria(query="python"))
    assert score == 0
    assert chips == ["−no keyword match"]


def test_exclude_term_wins_over_everything(conn: sqlite3.Connection) -> None:
    job = _insert_job(conn, description="Python backend for a crypto exchange.")
    score, chips = scoring.score_job(job, make_criteria(query="python", exclude=["crypto"]))
    assert score == 0
    assert chips == ["−crypto"]


def test_company_blocklist(conn: sqlite3.Connection) -> None:
    job = _insert_job(conn, company="Evil Corp Inc")
    score, chips = scoring.score_job(job, make_criteria(company_blocklist=["evil corp"]))
    assert score == 0
    assert chips == ["−evil corp"]


def test_remote_only_rejects_onsite_but_allows_unknown(conn: sqlite3.Connection) -> None:
    onsite = _insert_job(conn, remote=0, url="https://x.example/onsite")
    unknown = _insert_job(conn, remote=None, url="https://x.example/unknown")
    criteria = make_criteria(remote_only=True)
    assert scoring.score_job(onsite, criteria)[0] == 0
    assert scoring.score_job(unknown, criteria)[0] > 0


def test_salary_floor(conn: sqlite3.Connection) -> None:
    below = _insert_job(conn, salary_min=60000, salary_max=80000, url="https://x.example/lo")
    above = _insert_job(conn, salary_min=140000, salary_max=170000, url="https://x.example/hi")
    unknown = _insert_job(conn, url="https://x.example/unk")
    criteria = make_criteria(salary_floor=120000)
    assert scoring.score_job(below, criteria)[0] == 0
    above_score, above_chips = scoring.score_job(above, criteria)
    assert "+salary" in above_chips
    assert scoring.score_job(unknown, criteria)[0] > 0  # unknown salary is not a veto


def test_freshness_window(conn: sqlite3.Connection) -> None:
    old = _insert_job(
        conn,
        posted_at=(datetime.now(UTC) - timedelta(days=45)).isoformat(),
        url="https://x.example/old",
    )
    score, chips = scoring.score_job(old, make_criteria(freshness_days=30))
    assert (score, chips) == (0, ["−stale"])


def test_recency_bonus_tiers(conn: sqlite3.Connection) -> None:
    fresh = _insert_job(conn, url="https://x.example/f")
    week = _insert_job(
        conn,
        posted_at=(datetime.now(UTC) - timedelta(days=5)).isoformat(),
        url="https://x.example/w",
    )
    month = _insert_job(
        conn,
        posted_at=(datetime.now(UTC) - timedelta(days=20)).isoformat(),
        url="https://x.example/m",
    )
    criteria = make_criteria()
    assert (
        scoring.score_job(fresh, criteria)[0]
        > scoring.score_job(week, criteria)[0]
        > scoring.score_job(month, criteria)[0]
    )


def test_nice_to_have_caps_at_30(conn: sqlite3.Connection) -> None:
    job = _insert_job(conn, description="python fastapi postgres aws docker kubernetes")
    many = make_criteria(
        nice_to_have=["python", "fastapi", "postgres", "aws", "docker", "kubernetes"]
    )
    score_all, chips = scoring.score_job(job, many)
    assert score_all <= 25 + 30 + 15  # base + capped bonus + fresh
    assert "+fastapi" in chips


def test_best_criteria_wins(conn: sqlite3.Connection) -> None:
    job = _insert_job(conn)
    weak = make_criteria(id=1, name="Weak", query="java")
    strong = make_criteria(id=2, name="Strong", query="python")
    score, chips, name = scoring.score_job_best(job, [weak, strong])
    assert name == "Strong"
    assert score > 0


def test_score_new_jobs_and_rescore(conn: sqlite3.Connection) -> None:
    scoring.ensure_default_criteria(conn)
    _insert_job(conn, url="https://x.example/1")
    _insert_job(conn, url="https://x.example/2", title="Java Developer", description="Spring shop.")
    assert scoring.score_new_jobs(conn) == 2
    assert scoring.score_new_jobs(conn) == 0  # nothing left unscored
    conn.execute("UPDATE criteria SET config_json = ?", (json.dumps({"query": "python"}),))
    conn.commit()
    scoring.rescore_all(conn)
    scores = {
        row["score"] for row in conn.execute("SELECT score FROM scores WHERE scorer = 'heuristic'")
    }
    assert 0 in scores  # the Java job no longer matches


def test_invalid_stored_query_is_skipped_not_fatal(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO criteria (name, config_json) VALUES ('Broken', ?)",
        (json.dumps({"query": "python AND ("}),),
    )
    conn.execute(
        "INSERT INTO criteria (name, config_json) VALUES ('Fine', ?)",
        (json.dumps({"query": "python"}),),
    )
    conn.commit()
    loaded = scoring.load_enabled_criteria(conn)
    assert [c.name for c in loaded] == ["Fine"]


def test_threshold_roundtrip(conn: sqlite3.Connection) -> None:
    assert scoring.get_threshold(conn) == 0
    scoring.set_threshold(conn, 55)
    assert scoring.get_threshold(conn) == 55
    scoring.set_threshold(conn, 999)
    assert scoring.get_threshold(conn) == 100


def test_freshness_days_zero_means_today_only(conn: sqlite3.Connection) -> None:
    yesterday = _insert_job(
        conn,
        posted_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        url="https://x.example/y",
    )
    criteria = make_criteria(freshness_days=0)
    assert scoring.score_job(yesterday, criteria) == (0, ["−stale"])


def test_watchlist_boost_applied_and_capped(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        """INSERT INTO sources (kind, name, config_json)
           VALUES ('greenhouse_board', 'Watchlist: Hooli', '{"company": "hooli"}')"""
    )
    watch_id = cursor.lastrowid
    watched = _insert_job(conn, source_id=watch_id, url="https://x.example/watched")
    unwatched = _insert_job(conn, url="https://x.example/unwatched", title="Python Engineer")
    scoring.ensure_default_criteria(conn)

    scoring.score_new_jobs(conn)

    def row_for(job_id: int) -> sqlite3.Row:
        return conn.execute(
            "SELECT * FROM scores WHERE job_id = ? AND scorer = 'heuristic'", (job_id,)
        ).fetchone()

    watched_row, unwatched_row = row_for(watched["id"]), row_for(unwatched["id"])
    assert watched_row["score"] == unwatched_row["score"] + scoring.W_WATCHLIST
    assert "+watchlist" in json.loads(watched_row["rationale_json"])["chips"]
    assert "+watchlist" not in json.loads(unwatched_row["rationale_json"])["chips"]


def test_watchlist_boost_never_revives_excluded_jobs(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        """INSERT INTO sources (kind, name, config_json)
           VALUES ('lever_board', 'Watchlist: PP', '{"company": "pp"}')"""
    )
    job = _insert_job(conn, source_id=cursor.lastrowid, description="A crypto exchange.")
    conn.execute(
        "INSERT INTO criteria (name, config_json) VALUES ('c', ?)",
        (json.dumps({"exclude": ["crypto"]}),),
    )
    conn.commit()
    scoring.score_new_jobs(conn)
    row = conn.execute("SELECT * FROM scores WHERE job_id = ?", (job["id"],)).fetchone()
    assert row["score"] == 0
