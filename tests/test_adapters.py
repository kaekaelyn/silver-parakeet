import json
from pathlib import Path

import httpx

from wingman.sources import hn, remoteok, remotive, rss, wwr

FIXTURES = Path(__file__).parent / "fixtures"


def test_remotive_parse() -> None:
    payload = json.loads((FIXTURES / "remotive.json").read_text())
    postings = remotive.parse(payload)
    assert len(postings) == 3
    first = postings[0]
    assert first.title == "Senior Backend Engineer"
    assert first.company == "Acme Inc."
    assert first.location == "Worldwide"
    assert first.remote is True
    assert (first.salary_min, first.salary_max) == (120000, 150000)
    assert first.posted_at is not None
    assert "<p>" not in first.description
    assert "PostgreSQL at scale" in first.description


def test_remoteok_parse_skips_legal_notice() -> None:
    payload = json.loads((FIXTURES / "remoteok.json").read_text())
    postings = remoteok.parse(payload)
    assert len(postings) == 2
    first = postings[0]
    assert first.company == "Acme"
    assert first.title == "Senior Backend Engineer"
    assert (first.salary_min, first.salary_max) == (120000, 150000)
    assert first.posted_at is not None


def test_wwr_parse_splits_company_from_title() -> None:
    postings = wwr.parse((FIXTURES / "wwr.rss").read_text())
    assert len(postings) == 2
    first = postings[0]
    assert first.company == "PixelWorks"
    assert first.title == "Senior Frontend Developer"
    assert first.location == "Anywhere in the World"
    assert first.posted_at is not None
    assert "TypeScript" in first.description


def test_hn_parse_top_level_comments() -> None:
    item = json.loads((FIXTURES / "hn_item.json").read_text())
    postings = hn.parse(item)
    # Three children, one deleted (no text) — replies to comments are not parsed.
    assert len(postings) == 2
    first = postings[0]
    assert first.company == "Nimbus Robotics"
    assert first.title == "Senior Python Engineer"
    assert first.location == "Remote (US)"
    assert first.remote is True
    assert (first.salary_min, first.salary_max) == (140000, 170000)
    assert first.url == "https://news.ycombinator.com/item?id=44444100"
    second = postings[1]
    assert second.company == "Foo Labs"
    assert second.location == "Berlin, Germany"
    assert second.remote is None


def test_generic_rss_parse() -> None:
    postings = rss.parse((FIXTURES / "generic.rss").read_text())
    assert len(postings) == 2
    assert postings[0].title == "Django Developer at Riverbend Software"
    assert postings[0].url == "https://djangojobs.example/jobs/riverbend-django-developer"
    assert postings[0].posted_at is not None


def test_hn_fetch_two_step_with_mock_transport() -> None:
    search_payload = (FIXTURES / "hn_search.json").read_text()
    item_payload = (FIXTURES / "hn_item.json").read_text()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/search_by_date":
            return httpx.Response(200, text=search_payload)
        return httpx.Response(200, text=item_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    postings = hn.HackerNewsWhoIsHiringSource().fetch({}, client)
    assert len(postings) == 2
    assert calls == ["/api/v1/search_by_date", "/api/v1/items/44444001"]

    # With a pinned story_id the search step is skipped.
    calls.clear()
    postings = hn.HackerNewsWhoIsHiringSource().fetch({"story_id": 44444001}, client)
    assert len(postings) == 2
    assert calls == ["/api/v1/items/44444001"]


def test_html_to_text_preserves_escaped_markup() -> None:
    from wingman.sources import html_to_text

    assert (
        html_to_text("<p>Use &lt;template&gt; tags &amp; 5 &lt; 10</p>")
        == "Use <template> tags & 5 < 10"
    )


def test_salary_parse_ignores_401k_and_hourly() -> None:
    from wingman.sources import parse_salary_range

    assert parse_salary_range("$150k | 401k and health insurance") == (150000, None)
    assert parse_salary_range("$40/hr, 40 hours") == (None, None)


def test_generic_rss_rejects_non_feed_content() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="not a valid RSS/Atom feed"):
        rss.parse("<html><body>This is a webpage, not a feed</body></html>")


def test_greenhouse_board_parse() -> None:
    from wingman.sources import boards

    payload = json.loads((FIXTURES / "greenhouse_board.json").read_text())
    postings = boards.parse_greenhouse(payload, "Hooli")
    assert len(postings) == 2  # the entry with no URL is dropped
    first = postings[0]
    assert first.title == "Senior Platform Engineer"
    assert first.company == "Hooli"
    assert first.remote is True
    assert first.posted_at is not None
    # The boards API escapes the HTML body once; it must come out as text.
    assert "platform" in first.description and "<strong>" not in first.description
    assert postings[1].remote is None  # New York office role: unknown, not False


def test_lever_board_parse() -> None:
    from wingman.sources import boards

    payload = json.loads((FIXTURES / "lever_board.json").read_text())
    postings = boards.parse_lever(payload, "Pied Piper")
    assert len(postings) == 2
    first = postings[0]
    assert first.title == "Backend Engineer, Payments"
    assert first.company == "Pied Piper"
    assert first.remote is True
    assert (first.salary_min, first.salary_max) == (130000, 165000)
    assert first.posted_at is not None
    assert "payments pipeline" in first.description
    assert postings[1].remote is None  # on-site: not confirmed-remote


def test_ashby_board_parse_skips_unlisted() -> None:
    from wingman.sources import boards

    payload = json.loads((FIXTURES / "ashby_board.json").read_text())
    postings = boards.parse_ashby(payload, "Aviato")
    assert len(postings) == 1  # isListed=false entries never become jobs
    first = postings[0]
    assert first.title == "Machine Learning Engineer"
    assert first.remote is True
    assert (first.salary_min, first.salary_max) == (150000, 190000)
    assert first.posted_at is not None


def test_board_fetch_uses_config_slug() -> None:
    from wingman.sources import boards

    payload = (FIXTURES / "greenhouse_board.json").read_text()
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, text=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    postings = boards.GreenhouseBoardSource().fetch(
        {"company": "hooli", "company_name": "Hooli"}, client
    )
    assert len(postings) == 2
    assert urls == ["https://boards-api.greenhouse.io/v1/boards/hooli/jobs?content=true"]


def test_board_fetch_without_slug_raises() -> None:
    import pytest as _pytest

    from wingman.sources import boards

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with _pytest.raises(ValueError, match="board slug"):
        boards.LeverBoardSource().fetch({}, client)


def test_adzuna_parse() -> None:
    from wingman.sources import adzuna

    payload = json.loads((FIXTURES / "adzuna.json").read_text())
    postings = adzuna.parse(payload)
    assert len(postings) == 2
    first = postings[0]
    assert first.title == "Python Developer"
    assert first.company == "Initech"
    assert (first.salary_min, first.salary_max) == (110000, 135000)
    assert first.posted_at is not None
    assert "<b>" not in first.description


def test_adzuna_fetch_requires_keys_and_sends_them() -> None:
    import pytest as _pytest

    from wingman.sources import adzuna

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=(FIXTURES / "adzuna.json").read_text())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with _pytest.raises(ValueError, match="keys are not configured"):
        adzuna.AdzunaSource().fetch({}, client)
    assert seen == []  # no request without keys

    postings = adzuna.AdzunaSource().fetch(
        {"app_id": "id1", "app_key": "k1", "what": "python"}, client
    )
    assert len(postings) == 2
    params = dict(seen[0].url.params)
    assert params["app_id"] == "id1" and params["app_key"] == "k1"
    assert params["what"] == "python"
    assert "/jobs/us/search/1" in seen[0].url.path


def test_usajobs_parse_annual_salary_only() -> None:
    from wingman.sources import usajobs

    payload = json.loads((FIXTURES / "usajobs.json").read_text())
    postings = usajobs.parse(payload)
    assert len(postings) == 2
    first = postings[0]
    assert first.title == "IT Specialist (APPSW)"
    assert first.company == "Department of the Treasury"
    assert (first.salary_min, first.salary_max) == (99200, 153354)
    assert first.remote is None
    # Hourly rates must not be read as annual salaries.
    second = postings[1]
    assert (second.salary_min, second.salary_max) == (None, None)
    assert second.remote is True


def test_usajobs_fetch_sends_auth_headers() -> None:
    import pytest as _pytest

    from wingman.sources import usajobs

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=(FIXTURES / "usajobs.json").read_text())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with _pytest.raises(ValueError, match="keys are not configured"):
        usajobs.USAJobsSource().fetch({"api_key": "k"}, client)  # email missing

    usajobs.USAJobsSource().fetch({"api_key": "k1", "email": "andy@example.com"}, client)
    assert seen[0].headers["authorization-key"] == "k1"
    assert seen[0].headers["user-agent"] == "andy@example.com"
