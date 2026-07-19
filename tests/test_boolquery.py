import pytest

from wingman.boolquery import Query, QueryError, compile_query, term_in_text


def matches(query: str, text: str) -> bool:
    return Query(query).matches(text)[0]


def test_single_term() -> None:
    assert matches("python", "Senior Python Engineer")
    assert not matches("python", "Senior Java Engineer")


def test_word_boundaries() -> None:
    assert not matches("go", "Django developer wanted")
    assert matches("go", "Go developer wanted")
    assert matches("c++", "We use C++ daily")


def test_and() -> None:
    assert matches("python AND backend", "Backend role using Python")
    assert not matches("python AND backend", "Backend role using Java")


def test_implicit_and() -> None:
    assert matches("python backend", "Backend role using Python")
    assert not matches("python backend", "Frontend role using Python")


def test_or() -> None:
    assert matches("backend OR platform", "Platform team")
    assert not matches("backend OR platform", "Frontend team")


def test_not() -> None:
    assert matches("python NOT crypto", "Python at a bank")
    assert not matches("python NOT crypto", "Python for crypto trading")


def test_precedence_not_binds_tighter_than_and_than_or() -> None:
    # a OR b AND c == a OR (b AND c)
    assert matches("java OR python AND backend", "java shop")
    assert not matches("java OR python AND backend", "python frontend")
    assert matches("java OR python AND backend", "python backend")
    # NOT c AND b == (NOT c) AND b
    assert matches("NOT crypto AND python", "python roles")


def test_parentheses() -> None:
    query = "python AND (backend OR platform) NOT crypto"
    assert matches(query, "Python backend engineer")
    assert matches(query, "Python platform engineer")
    assert not matches(query, "Python data engineer")
    assert not matches(query, "Python backend engineer, crypto exchange")


def test_nested_parentheses() -> None:
    assert matches("((python))", "python")
    assert matches("(python OR (go AND backend))", "go backend role")


def test_quoted_phrase() -> None:
    assert matches('"machine learning"', "Machine Learning Engineer")
    assert not matches('"machine learning"', "machine operator learning fast")


def test_case_insensitive() -> None:
    assert matches("PYTHON and BACKEND", "python backend")
    assert matches("python", "PYTHON role")


def test_double_not() -> None:
    assert matches("NOT NOT python", "python role")
    assert not matches("NOT NOT python", "java role")


def test_matched_terms_collected_for_chips() -> None:
    matched, hits = Query("python AND (backend OR platform)").matches("python platform team")
    assert matched
    assert hits == ["python", "platform"]


def test_negated_terms_not_collected() -> None:
    matched, hits = Query("python NOT crypto").matches("python role")
    assert matched
    assert hits == ["python"]


def test_invalid_queries_raise() -> None:
    for bad in ("python AND", "(python", "python)", "AND python", "NOT", "OR", ""):
        with pytest.raises(QueryError):
            Query(bad)


def test_compile_query_blank_is_none() -> None:
    assert compile_query("") is None
    assert compile_query("   ") is None
    assert compile_query("python") is not None


def test_term_in_text_escapes_regex_chars() -> None:
    assert term_in_text("c++", "we use c++ here")
    assert term_in_text(".net", "a .net shop")
    assert not term_in_text(".net", "internet company")
