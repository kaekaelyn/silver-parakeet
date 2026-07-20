"""Shared filler machinery: control survey, question walker, highlighting.

The survey tags every form control with a data-wingman index and returns
its metadata in one JS pass; Python then decides what to fill. Anything
not confidently matched is left alone and reported — never guessed.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from wingman.apply import matching
from wingman.apply.packet import FillPacket

logger = logging.getLogger(__name__)

FILL_TIMEOUT_MS = 3000

CAPTCHA_SELECTOR = (
    "iframe[src*='recaptcha'], .g-recaptcha, "
    "iframe[src*='hcaptcha'], .h-captcha, "
    "iframe[src*='turnstile'], .cf-turnstile"
)

GENERIC_CONFIRMATION_MARKERS = (
    "thank you for applying",
    "application has been submitted",
    "application was submitted",
    "we have received your application",
    "your application has been received",
)


@dataclass
class FillReport:
    ats: str
    filled: list[str] = field(default_factory=list)
    unmatched_required: list[str] = field(default_factory=list)
    unmatched_optional: list[str] = field(default_factory=list)
    captcha: bool = False

    @property
    def clean(self) -> bool:
        """Safe for unattended submit: no CAPTCHA, no unanswered required field."""
        return not self.captcha and not self.unmatched_required

    def summary(self) -> dict[str, Any]:
        return {
            "ats": self.ats,
            "filled": len(self.filled),
            "unmatched_required": self.unmatched_required,
            "unmatched_optional": self.unmatched_optional,
            "captcha": self.captcha,
        }


_SURVEY_JS = """
() => {
  const controls = Array.from(
    document.querySelectorAll("form input, form textarea, form select"));
  const clean = (t) => (t || "").replace(/\\s+/g, " ").trim();
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.textContent;
    }
    const wrap = el.closest("label");
    if (wrap) return wrap.textContent;
    const aria = el.getAttribute("aria-label");
    if (aria) return aria;
    // Walk up, but never past the form or into containers holding other
    // controls — that would grab some unrelated question's label.
    let node = el.parentElement;
    for (let i = 0; i < 4 && node && node.tagName !== "FORM"; i++) {
      if (node.querySelectorAll("input, textarea, select").length === 1) {
        const l = node.querySelector("label, legend");
        if (l) return l.textContent;
      }
      node = node.parentElement;
    }
    return "";
  };
  const groupLabelFor = (el) => {
    const fs = el.closest("fieldset");
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg) return lg.textContent;
    }
    let node = el.parentElement;
    for (let i = 0; i < 5 && node && node.tagName !== "FORM"; i++) {
      const q = node.querySelector("legend, .application-label, .question-label");
      if (q) return q.textContent;
      node = node.parentElement;
    }
    return "";
  };
  return controls.map((el, i) => {
    el.setAttribute("data-wingman", String(i));
    const label = clean(labelFor(el));
    return {
      idx: i,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute("type") || "").toLowerCase(),
      name: el.getAttribute("name") || "",
      id: el.id || "",
      value: el.value || "",
      checked: !!el.checked,
      required: el.required || el.getAttribute("aria-required") === "true"
        || label.includes("*"),
      label,
      group_label: clean(groupLabelFor(el)),
      options: el.tagName === "SELECT"
        ? Array.from(el.options).map((o) => clean(o.textContent))
        : null,
    };
  });
}
"""

_SKIP_TYPES = {"hidden", "submit", "button", "image", "reset", "file"}


def survey(page: Page) -> list[dict]:
    """Tag and describe every form control on the page."""
    return page.evaluate(_SURVEY_JS)


def _selector(idx: int) -> str:
    return f'[data-wingman="{idx}"]'


def try_fill(page: Page, idx: int, value: str) -> bool:
    try:
        page.locator(_selector(idx)).fill(value, timeout=FILL_TIMEOUT_MS)
        return True
    except PlaywrightError as exc:
        logger.warning("could not fill control %d: %s", idx, str(exc).splitlines()[0])
        return False


def try_check(page: Page, idx: int) -> bool:
    try:
        page.locator(_selector(idx)).check(timeout=FILL_TIMEOUT_MS)
        return True
    except PlaywrightError as exc:
        logger.warning("could not check control %d: %s", idx, str(exc).splitlines()[0])
        return False


def _select_by_answer(page: Page, control: dict, answer: str) -> bool:
    """Pick the select option matching the answer text; False if none does."""
    answer_norm = matching.normalize(answer)
    if not answer_norm:
        return False
    options = control["options"] or []
    best = None
    for option in options:
        option_norm = matching.normalize(option)
        if not option_norm:
            continue
        if option_norm == answer_norm:
            best = option
            break
        if best is None and (answer_norm in option_norm or option_norm in answer_norm):
            best = option
    if best is None:
        return False
    try:
        page.locator(_selector(control["idx"])).select_option(label=best, timeout=FILL_TIMEOUT_MS)
        return True
    except PlaywrightError as exc:
        logger.warning("could not select option: %s", str(exc).splitlines()[0])
        return False


def attach_resume(page: Page, packet: FillPacket, report: FillReport) -> None:
    """Upload the default resume into the first file input that wants one."""
    for control in survey(page):
        if control["type"] != "file":
            continue
        haystack = matching.normalize(" ".join((control["label"], control["name"], control["id"])))
        if not any(word in haystack for word in ("resume", "cv")):
            continue
        if packet.resume_path is None:
            if control["required"]:
                report.unmatched_required.append("Resume upload (no default resume in vault)")
            return
        try:
            page.locator(_selector(control["idx"])).set_input_files(
                str(packet.resume_path), timeout=FILL_TIMEOUT_MS
            )
            report.filled.append("Resume")
        except PlaywrightError as exc:
            logger.warning("resume upload failed: %s", str(exc).splitlines()[0])
            report.unmatched_required.append("Resume upload")
        return


def walk_questions(
    page: Page,
    packet: FillPacket,
    report: FillReport,
    skip_names: tuple[str, ...] = (),
    skip_ids: tuple[str, ...] = (),
) -> None:
    """Generic pass: match every unanswered control's question to an answer."""
    controls = survey(page)
    radio_groups: dict[str, list[dict]] = {}
    for control in controls:
        if control["type"] == "radio" and control["name"]:
            radio_groups.setdefault(control["name"], []).append(control)

    seen_radio: set[str] = set()
    for control in controls:
        if control["tag"] == "input" and control["type"] in _SKIP_TYPES:
            continue
        if control["name"] in skip_names or (control["id"] and control["id"] in skip_ids):
            continue

        if control["type"] == "radio":
            if control["name"] in seen_radio:
                continue
            seen_radio.add(control["name"])
            _fill_radio_group(page, radio_groups[control["name"]], packet, report)
            continue

        if control["value"].strip() or control["checked"]:
            continue  # already answered (by a standard-field pass or the human)

        question = control["label"] or control["group_label"]
        if not question and not control["required"]:
            continue
        answer = matching.match_answer(question, packet.answers) if question else None

        if control["tag"] == "select":
            if answer is not None and _select_by_answer(page, control, answer["answer"]):
                report.filled.append(question)
                continue
        elif control["type"] == "checkbox":
            # A single checkbox is consent-shaped; never check one automatically.
            answer = None
        elif answer is not None:
            if try_fill(page, control["idx"], answer["answer"]):
                report.filled.append(question)
                continue

        _record_unmatched(report, control["required"], question or control["name"])


def _fill_radio_group(
    page: Page, group: list[dict], packet: FillPacket, report: FillReport
) -> None:
    if any(option["checked"] for option in group):
        return
    question = next((o["group_label"] for o in group if o["group_label"]), "") or group[0]["label"]
    required = any(option["required"] for option in group)
    answer = matching.match_answer(question, packet.answers) if question else None
    if answer is not None:
        answer_norm = matching.normalize(answer["answer"])
        for option in group:
            option_norm = matching.normalize(option["label"])
            if option_norm and (
                option_norm == answer_norm
                or answer_norm in option_norm
                or option_norm in answer_norm
            ):
                if try_check(page, option["idx"]):
                    report.filled.append(question)
                    return
    _record_unmatched(report, required, question or group[0]["name"])


def _record_unmatched(report: FillReport, required: bool, question: str) -> None:
    entry = question.strip() or "(unlabeled field)"
    if required:
        report.unmatched_required.append(entry)
    else:
        report.unmatched_optional.append(entry)


def detect_captcha(page: Page) -> bool:
    return page.locator(CAPTCHA_SELECTOR).count() > 0


_HIGHLIGHT_JS = """
(args) => {
  const outline = (idx, color) => {
    const el = document.querySelector(`[data-wingman="${idx}"]`);
    if (el) {
      el.style.outline = `3px solid ${color}`;
      el.style.outlineOffset = "2px";
    }
  };
  args.required.forEach((i) => outline(i, "#d33"));
  args.optional.forEach((i) => outline(i, "#e6a700"));
  let banner = document.getElementById("wingman-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "wingman-banner";
    banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;" +
      "background:#1c2333;color:#fff;padding:10px 16px;font:14px system-ui;" +
      "border-bottom:3px solid #5b8def;";
    document.body.prepend(banner);
  }
  banner.textContent = args.message;
}
"""


def show_review_banner(page: Page, report: FillReport, message: str) -> None:
    """Banner + outlines so the human sees what still needs attention."""
    controls = survey(page)
    by_question: dict[str, list[int]] = {}
    for control in controls:
        question = (control["label"] or control["group_label"] or control["name"]).strip()
        by_question.setdefault(question, []).append(control["idx"])
    required = [i for q in report.unmatched_required for i in by_question.get(q, [])]
    optional = [i for q in report.unmatched_optional for i in by_question.get(q, [])]
    try:
        page.evaluate(
            _HIGHLIGHT_JS, {"required": required, "optional": optional, "message": message}
        )
    except PlaywrightError as exc:
        logger.warning("could not draw review banner: %s", str(exc).splitlines()[0])


def submission_confirmed(page: Page, extra_markers: tuple[str, ...] = ()) -> bool:
    """Did the page turn into a submission confirmation?"""
    try:
        url = page.url.lower()
        if "confirmation" in url or "/thanks" in url:
            return True
        content = page.content().lower()
    except PlaywrightError:
        return False
    return any(marker in content for marker in GENERIC_CONFIRMATION_MARKERS + extra_markers)
