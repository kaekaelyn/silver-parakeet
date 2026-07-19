from pathlib import Path

import pytest

from wingman import db, ingest, scheduler
from wingman.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    prepared = Settings(data_dir=tmp_path / "data")
    with db.session(prepared.db_path) as conn:
        db.migrate(conn)
        ingest.ensure_default_sources(conn)
    return prepared


def test_refresh_jobs_tracks_enabled_sources(settings: Settings) -> None:
    sched = scheduler.create_scheduler()
    sched.start(paused=True)
    try:
        scheduler.refresh_jobs(sched, settings)
        assert len(sched.get_jobs()) == 4

        with db.session(settings.db_path) as conn:
            conn.execute("UPDATE sources SET enabled = 0 WHERE id = 1")
            conn.commit()
        scheduler.refresh_jobs(sched, settings)
        jobs = sched.get_jobs()
        assert len(jobs) == 3
        assert "source-1" not in {job.id for job in jobs}

        with db.session(settings.db_path) as conn:
            conn.execute("UPDATE sources SET enabled = 1 WHERE id = 1")
            conn.commit()
        scheduler.refresh_jobs(sched, settings)
        assert len(sched.get_jobs()) == 4
    finally:
        sched.shutdown(wait=False)


def test_interval_config_change_reschedules(settings: Settings) -> None:
    import json

    sched = scheduler.create_scheduler()
    sched.start(paused=True)
    try:
        scheduler.refresh_jobs(sched, settings)
        before = sched.get_job("source-1").trigger.interval.total_seconds()
        with db.session(settings.db_path) as conn:
            conn.execute(
                "UPDATE sources SET config_json = ? WHERE id = 1",
                (json.dumps({"interval_minutes": 5}),),
            )
            conn.commit()
        scheduler.refresh_jobs(sched, settings)
        after = sched.get_job("source-1").trigger.interval.total_seconds()
        assert before != after
        assert after == 300
    finally:
        sched.shutdown(wait=False)
