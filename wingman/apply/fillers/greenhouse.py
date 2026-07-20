"""Greenhouse application form filler (boards.greenhouse.io and embeds)."""

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from wingman.apply.fillers import common
from wingman.apply.packet import FillPacket, split_name

ATS = "greenhouse"
SUBMIT_SELECTOR = "#submit_app, button[type='submit'], input[type='submit']"
CONFIRMATION_MARKERS = ("thank you for applying",)

# Standard Greenhouse contact fields: (selector, contact key, label, required).
_STANDARD = (
    ("#first_name", "first", "First name", True),
    ("#last_name", "last", "Last name", True),
    ("#email", "email", "Email", True),
    ("#phone", "phone", "Phone", False),
)
_STANDARD_IDS = ("first_name", "last_name", "email", "phone", "cover_letter_text")


def fill(page: Page, packet: FillPacket) -> common.FillReport:
    report = common.FillReport(ats=ATS)
    first, last = split_name(packet.contact.get("name", ""))
    values = dict(packet.contact) | {"first": first, "last": last}

    for selector, key, label, required in _STANDARD:
        _fill_standard(page, report, selector, values.get(key, ""), label, required)

    common.attach_resume(page, packet, report)

    if packet.cover_letter:
        try:
            letter_box = page.locator("#cover_letter_text")
            if letter_box.count() and not letter_box.input_value():
                letter_box.fill(packet.cover_letter, timeout=common.FILL_TIMEOUT_MS)
                report.filled.append("Cover letter")
        except PlaywrightError:
            report.unmatched_optional.append("Cover letter")

    common.walk_questions(page, packet, report, skip_ids=_STANDARD_IDS)
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
