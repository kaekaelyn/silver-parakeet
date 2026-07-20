"""Lever application form filler (jobs.lever.co/<company>/<id>/apply)."""

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from wingman.apply.fillers import common
from wingman.apply.packet import FillPacket

ATS = "lever"
SUBMIT_SELECTOR = "button[type='submit'], #btn-submit"
CONFIRMATION_MARKERS = ("application has been received", "thanks for applying")

# Standard Lever fields: (selector, contact key, label, required).
_STANDARD = (
    ("input[name='name']", "name", "Full name", True),
    ("input[name='email']", "email", "Email", True),
    ("input[name='phone']", "phone", "Phone", False),
    ("input[name='urls[LinkedIn]']", "linkedin", "LinkedIn", False),
    ("input[name='urls[GitHub]']", "github", "GitHub", False),
    ("input[name='urls[Portfolio]']", "website", "Portfolio", False),
)
_STANDARD_NAMES = (
    "name",
    "email",
    "phone",
    "urls[LinkedIn]",
    "urls[GitHub]",
    "urls[Portfolio]",
    "comments",
)


def fill(page: Page, packet: FillPacket) -> common.FillReport:
    report = common.FillReport(ats=ATS)

    for selector, key, label, required in _STANDARD:
        _fill_standard(page, report, selector, packet.contact.get(key, ""), label, required)

    common.attach_resume(page, packet, report)

    if packet.cover_letter:
        try:
            comments = page.locator("textarea[name='comments']")
            if comments.count() and not comments.input_value():
                comments.fill(packet.cover_letter, timeout=common.FILL_TIMEOUT_MS)
                report.filled.append("Cover letter")
        except PlaywrightError:
            report.unmatched_optional.append("Cover letter")

    common.walk_questions(page, packet, report, skip_names=_STANDARD_NAMES)
    report.captcha = common.detect_captcha(page)
    return report


def _fill_standard(
    page: Page, report: common.FillReport, selector: str, value: str, label: str, required: bool
) -> None:
    try:
        locator = page.locator(selector)
        if not locator.count():
            return
        if locator.input_value():
            return  # already answered (by the human or a previous pass)
        if value:
            locator.fill(value, timeout=common.FILL_TIMEOUT_MS)
            report.filled.append(label)
        elif required:
            report.unmatched_required.append(f"{label} (empty in vault)")
    except PlaywrightError:
        report.unmatched_required.append(label)
