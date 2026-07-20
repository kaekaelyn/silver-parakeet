"""Ashby application form filler (jobs.ashbyhq.com/<company>/<id>/application)."""

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from wingman.apply import matching
from wingman.apply.fillers import common
from wingman.apply.packet import FillPacket

ATS = "ashby"
SUBMIT_SELECTOR = "button.ashby-application-form-submit-button, button[type='submit']"
CONFIRMATION_MARKERS = ("application submitted", "application has been submitted")

# Standard Ashby system fields: (selector, contact key, label, required).
_STANDARD = (
    ("#_systemfield_name", "name", "Full name", True),
    ("#_systemfield_email", "email", "Email", True),
    ("#_systemfield_phone", "phone", "Phone", False),
)
_STANDARD_IDS = ("_systemfield_name", "_systemfield_email", "_systemfield_phone")


def fill(page: Page, packet: FillPacket) -> common.FillReport:
    report = common.FillReport(ats=ATS)

    for selector, key, label, required in _STANDARD:
        _fill_standard(page, report, selector, packet.contact.get(key, ""), label, required)

    common.attach_resume(page, packet, report)

    if packet.cover_letter:
        _fill_cover_letter(page, packet, report)

    common.walk_questions(page, packet, report, skip_ids=_STANDARD_IDS)
    report.captcha = common.detect_captcha(page)
    return report


def _fill_cover_letter(page: Page, packet: FillPacket, report: common.FillReport) -> None:
    # Ashby has no fixed cover-letter field id — boards add it as a custom
    # question — so find the first textarea whose label says "cover letter".
    for control in common.survey(page):
        if control["tag"] != "textarea":
            continue
        if "cover letter" not in matching.normalize(control["label"]):
            continue
        if control["value"].strip():
            return  # already answered (by the human or a previous pass)
        if common.try_fill(page, control["idx"], packet.cover_letter):
            report.filled.append("Cover letter")
        else:
            report.unmatched_optional.append("Cover letter")
        return


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
