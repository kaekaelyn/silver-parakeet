"""Workable application form filler (apply.workable.com/<company>/j/<id>/apply)."""

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from wingman.apply.fillers import common
from wingman.apply.packet import FillPacket, split_name

ATS = "workable"
SUBMIT_SELECTOR = "button[data-ui='submit-application'], button[type='submit']"
CONFIRMATION_MARKERS = ("application has been submitted successfully", "thank you for applying")

# Standard Workable contact fields: (selector, contact key, label, required).
_STANDARD = (
    ("input[data-ui='firstname']", "first", "First name", True),
    ("input[data-ui='lastname']", "last", "Last name", True),
    ("input[data-ui='email']", "email", "Email", True),
    ("input[data-ui='phone']", "phone", "Phone", False),
)
_STANDARD_NAMES = ("firstname", "lastname", "email", "phone", "cover_letter")


def fill(page: Page, packet: FillPacket) -> common.FillReport:
    report = common.FillReport(ats=ATS)
    first, last = split_name(packet.contact.get("name", ""))
    values = dict(packet.contact) | {"first": first, "last": last}

    for selector, key, label, required in _STANDARD:
        _fill_standard(page, report, selector, values.get(key, ""), label, required)

    common.attach_resume(page, packet, report)

    if packet.cover_letter:
        try:
            letter_box = page.locator("textarea[data-ui='cover_letter']")
            if letter_box.count() and not letter_box.input_value():
                letter_box.fill(packet.cover_letter, timeout=common.FILL_TIMEOUT_MS)
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
