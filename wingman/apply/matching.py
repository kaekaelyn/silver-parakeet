"""Fuzzy matching of ATS question text against canned vault answers.

Unmatched questions are *never* guessed — a miss means the field is left
for the human, so the matcher prefers precision over recall.
"""

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")
_RATIO_FLOOR = 0.8


def normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _match_score(pattern: str, question: str) -> float:
    if not pattern or not question:
        return 0.0
    if pattern == question:
        return 1.0
    if f" {pattern} " in f" {question} ":
        return 0.95  # the pattern appears as a phrase inside the question
    pattern_tokens = set(pattern.split())
    if pattern_tokens and pattern_tokens <= set(question.split()):
        return 0.9  # every pattern word appears somewhere in the question
    ratio = SequenceMatcher(None, pattern, question).ratio()
    return ratio if ratio >= _RATIO_FLOOR else 0.0


def match_answer(question: str, answers: Sequence[Any]) -> Any | None:
    """Best answer row for a question, or None below the confidence floor.

    `answers` rows need `question_pattern` and `answer` keys; earlier rows
    win ties so derived contact answers can take precedence.
    """
    question_norm = normalize(question)
    best = None
    best_score = 0.0
    for row in answers:
        score = _match_score(normalize(row["question_pattern"]), question_norm)
        if score > best_score:
            best, best_score = row, score
    return best
