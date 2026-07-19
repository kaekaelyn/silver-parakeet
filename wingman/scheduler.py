"""APScheduler polling: one interval job per enabled source, with jitter."""

import json
import logging
import random
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from wingman import db, ingest
from wingman.config import Settings
from wingman.sources import ADAPTERS

logger = logging.getLogger(__name__)

_JOB_PREFIX = "source-"


def _run_fetch(settings: Settings, source_id: int) -> None:
    with db.session(settings.db_path) as conn:
        ingest.fetch_source(conn, source_id)


def create_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler()


def refresh_jobs(scheduler: BackgroundScheduler, settings: Settings) -> None:
    """Sync scheduler jobs with the enabled sources in the DB."""
    with db.session(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT id, kind, config_json FROM sources WHERE enabled = 1"
        ).fetchall()
    desired: dict[str, tuple[int, int]] = {}
    for row in rows:
        adapter = ADAPTERS.get(row["kind"])
        if adapter is None:
            logger.warning("source %d has unknown kind %r; skipping", row["id"], row["kind"])
            continue
        config = json.loads(row["config_json"] or "{}")
        interval = int(config.get("interval_minutes", adapter.default_interval_minutes))
        desired[f"{_JOB_PREFIX}{row['id']}"] = (row["id"], interval)

    existing = {job.id for job in scheduler.get_jobs() if job.id.startswith(_JOB_PREFIX)}
    for job_id in existing - desired.keys():
        scheduler.remove_job(job_id)
    for job_id, (source_id, interval) in desired.items():
        if job_id in existing:
            continue
        interval_seconds = interval * 60
        # First run lands 15-90s after startup (staggered per source) so a
        # fresh install shows real jobs within a minute or two.
        first_run = datetime.now(UTC) + timedelta(seconds=random.randint(15, 90))
        scheduler.add_job(
            _run_fetch,
            IntervalTrigger(seconds=interval_seconds, jitter=max(30, interval_seconds // 10)),
            args=(settings, source_id),
            id=job_id,
            next_run_time=first_run,
        )
