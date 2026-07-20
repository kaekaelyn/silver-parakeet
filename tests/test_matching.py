from wingman.apply import matching


def _answers(*pairs: tuple[str, str]) -> list[dict]:
    return [{"question_pattern": p, "answer": a} for p, a in pairs]


def test_exact_and_case_insensitive() -> None:
    answers = _answers(("salary expectations", "$150k"))
    assert matching.match_answer("Salary Expectations", answers)["answer"] == "$150k"


def test_phrase_inside_question() -> None:
    answers = _answers(("salary expectations", "$150k"))
    match = matching.match_answer("What are your salary expectations? *", answers)
    assert match is not None and match["answer"] == "$150k"


def test_tokens_scattered_in_question() -> None:
    answers = _answers(("visa sponsorship", "No"))
    match = matching.match_answer(
        "Will you now or in the future require sponsorship for a visa?", answers
    )
    assert match is not None and match["answer"] == "No"


def test_eeo_defaults_match() -> None:
    answers = _answers(("gender", "Decline to self-identify"))
    match = matching.match_answer("What is your gender?", answers)
    assert match is not None


def test_no_confident_match_returns_none() -> None:
    answers = _answers(("notice period", "2 weeks"), ("salary expectations", "$150k"))
    assert matching.match_answer("Describe your leadership style", answers) is None
    assert matching.match_answer("", answers) is None


def test_earlier_answers_win_ties() -> None:
    answers = _answers(
        ("linkedin", "https://derived.example"), ("linkedin", "https://vault.example")
    )
    assert matching.match_answer("LinkedIn", answers)["answer"] == "https://derived.example"


def test_normalize() -> None:
    assert matching.normalize("  What's your G.P.A.? ") == "what s your g p a"
