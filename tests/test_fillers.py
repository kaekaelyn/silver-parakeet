"""Filler tests against saved ATS form fixtures — a real (headless) browser,
no live HTTP."""

from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from wingman.apply.fillers import common, greenhouse, lever
from wingman.apply.packet import FillPacket

pytestmark = pytest.mark.usefixtures("browser")


def _packet(tmp_path: Path, extra_answers: list[dict] | None = None) -> FillPacket:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake resume")
    answers = [
        {"question_pattern": "linkedin profile", "answer": "https://linkedin.com/in/andy"},
        {"question_pattern": "linkedin url", "answer": "https://linkedin.com/in/andy"},
        {"question_pattern": "github url", "answer": "https://github.com/andy"},
        {"question_pattern": "portfolio", "answer": "https://andy.example"},
        {"question_pattern": "salary expectations", "answer": "$140,000"},
        {"question_pattern": "visa sponsorship", "answer": "No"},
        {"question_pattern": "gender", "answer": "Decline to self-identify"},
        {"question_pattern": "years of python experience", "answer": "8"},
        {"question_pattern": "authorized to work", "answer": "Yes"},
    ]
    answers.extend(extra_answers or [])
    return FillPacket(
        contact={
            "name": "Andy Dwyer",
            "email": "andy@example.com",
            "phone": "555-0100",
            "location": "Pawnee, IN",
            "github": "https://github.com/andy",
            "website": "https://andy.example",
            "linkedin": "https://linkedin.com/in/andy",
        },
        resume_path=resume,
        resume_name="Default resume",
        cover_letter="Dear team, I am thrilled to apply.",
        answers=answers,
    )


HAMSTER = {"question_pattern": "hamster herding", "answer": "Extensive herd experience"}


def _goto(page, name: str) -> None:
    page.goto((FIXTURES / name).resolve().as_uri())


def test_greenhouse_fill(page, tmp_path: Path) -> None:
    _goto(page, "greenhouse_form.html")
    report = greenhouse.fill(page, _packet(tmp_path))

    assert page.input_value("#first_name") == "Andy"
    assert page.input_value("#last_name") == "Dwyer"
    assert page.input_value("#email") == "andy@example.com"
    assert page.input_value("#phone") == "555-0100"
    assert page.input_value("#cover_letter_text") == "Dear team, I am thrilled to apply."
    assert page.input_value("#answer_0") == "https://linkedin.com/in/andy"
    assert page.input_value("#answer_1") == "$140,000"
    assert page.input_value("#answer_2") == "No"
    assert page.evaluate("document.querySelector('#resume').files[0].name") == "resume.pdf"
    assert page.is_checked("input[name='job_application[gender]'][value='3']")

    # The nonsense question must be reported, never guessed.
    assert any("hamster" in q for q in report.unmatched_required)
    assert report.captcha is False
    assert not report.clean


def test_greenhouse_clean_when_all_answered(page, tmp_path: Path) -> None:
    _goto(page, "greenhouse_form.html")
    report = greenhouse.fill(page, _packet(tmp_path, [HAMSTER]))
    assert report.unmatched_required == []
    assert report.clean


def test_greenhouse_missing_vault_fields_reported(page, tmp_path: Path) -> None:
    _goto(page, "greenhouse_form.html")
    packet = _packet(tmp_path)
    packet.contact["email"] = ""
    packet.resume_path = None
    report = greenhouse.fill(page, packet)
    assert any("Email" in q for q in report.unmatched_required)
    assert any("Resume" in q for q in report.unmatched_required)


def test_lever_fill(page, tmp_path: Path) -> None:
    _goto(page, "lever_form.html")
    report = lever.fill(page, _packet(tmp_path))

    assert page.input_value("input[name='name']") == "Andy Dwyer"
    assert page.input_value("input[name='email']") == "andy@example.com"
    assert page.input_value("input[name='urls[LinkedIn]']") == "https://linkedin.com/in/andy"
    assert page.input_value("input[name='urls[GitHub]']") == "https://github.com/andy"
    assert page.input_value("input[name='urls[Portfolio]']") == "https://andy.example"
    assert page.input_value("textarea[name='comments']") == "Dear team, I am thrilled to apply."
    assert page.input_value("input[name='cards[abc123][field0]']") == "8"
    assert page.is_checked("input[name='cards[abc123][field1]'][value='yes']")
    assert page.evaluate("document.querySelector('input[name=resume]').files.length") == 1

    # 'Current company' has no canned answer: unmatched but optional.
    assert any("Current company" in q for q in report.unmatched_optional)
    assert report.unmatched_required == []
    assert report.clean


def test_captcha_detected_blocks_clean(page, tmp_path: Path) -> None:
    _goto(page, "greenhouse_captcha.html")
    report = greenhouse.fill(page, _packet(tmp_path))
    assert report.captcha is True
    assert not report.clean


def test_review_banner_and_highlight(page, tmp_path: Path) -> None:
    _goto(page, "greenhouse_form.html")
    report = greenhouse.fill(page, _packet(tmp_path))
    common.show_review_banner(page, report, "Review before submitting")
    assert page.text_content("#wingman-banner") == "Review before submitting"
    outline = page.evaluate("document.querySelector('#answer_3').style.outline")
    assert "solid" in outline


def test_submission_confirmed_after_submit(page, tmp_path: Path) -> None:
    _goto(page, "greenhouse_form.html")
    greenhouse.fill(page, _packet(tmp_path, [HAMSTER]))
    assert not common.submission_confirmed(page, greenhouse.CONFIRMATION_MARKERS)
    page.locator(greenhouse.SUBMIT_SELECTOR).first.click()
    page.wait_for_selector("#confirmation")
    assert common.submission_confirmed(page, greenhouse.CONFIRMATION_MARKERS)


def test_fill_is_idempotent(page, tmp_path: Path) -> None:
    """A second pass must not clobber values (e.g. after the human edits)."""
    _goto(page, "greenhouse_form.html")
    greenhouse.fill(page, _packet(tmp_path))
    page.fill("#answer_1", "$999,999")  # the human raised their ask
    report = greenhouse.fill(page, _packet(tmp_path))
    assert page.input_value("#answer_1") == "$999,999"
    assert report.captcha is False
