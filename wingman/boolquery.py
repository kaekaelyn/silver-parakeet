"""Boolean keyword engine: AND / OR / NOT, parentheses, quoted phrases.

Grammar (case-insensitive keywords, implicit AND between adjacent terms):

    expr    := orexpr
    orexpr  := andexpr (OR andexpr)*
    andexpr := notexpr ((AND)? notexpr)*
    notexpr := NOT notexpr | atom
    atom    := '(' expr ')' | term | "quoted phrase"

Terms match whole words in the target text, case-insensitively; quoted
phrases match the phrase with word boundaries. Matched positive terms are
collected so the scorer can turn them into "why" chips.
"""

import re
from dataclasses import dataclass, field


class QueryError(ValueError):
    """The query string is malformed; the message says where."""


@dataclass
class _Token:
    kind: str  # AND | OR | NOT | LPAREN | RPAREN | TERM
    value: str = ""


_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<lparen>\() |
        (?P<rparen>\)) |
        (?P<quoted>"[^"]*") |
        (?P<word>[^\s()"]+)
    )""",
    re.VERBOSE,
)

_KEYWORDS = {"and": "AND", "or": "OR", "not": "NOT"}


def _tokenize(query: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(query):
        match = _TOKEN_RE.match(query, pos)
        if not match or match.end() == pos:
            if query[pos:].strip():
                raise QueryError(f"cannot parse query at: {query[pos:]!r}")
            break
        pos = match.end()
        if match.group("lparen"):
            tokens.append(_Token("LPAREN"))
        elif match.group("rparen"):
            tokens.append(_Token("RPAREN"))
        elif match.group("quoted"):
            phrase = match.group("quoted")[1:-1].strip()
            if phrase:
                tokens.append(_Token("TERM", phrase))
        else:
            word = match.group("word")
            kind = _KEYWORDS.get(word.lower())
            tokens.append(_Token(kind, "") if kind else _Token("TERM", word))
    return tokens


@dataclass
class _Node:
    op: str  # term | and | or | not
    term: str = ""
    children: list["_Node"] = field(default_factory=list)


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.peek()
        if token is None:
            raise QueryError("unexpected end of query")
        self.pos += 1
        return token

    def parse(self) -> _Node:
        node = self.or_expr()
        if self.peek() is not None:
            raise QueryError(f"unexpected {self.peek().kind.lower()} near end of query")
        return node

    def or_expr(self) -> _Node:
        children = [self.and_expr()]
        while (token := self.peek()) and token.kind == "OR":
            self.take()
            children.append(self.and_expr())
        return children[0] if len(children) == 1 else _Node("or", children=children)

    def and_expr(self) -> _Node:
        children = [self.not_expr()]
        while (token := self.peek()) and token.kind in ("AND", "NOT", "TERM", "LPAREN"):
            if token.kind == "AND":
                self.take()
            children.append(self.not_expr())
        return children[0] if len(children) == 1 else _Node("and", children=children)

    def not_expr(self) -> _Node:
        token = self.peek()
        if token and token.kind == "NOT":
            self.take()
            return _Node("not", children=[self.not_expr()])
        return self.atom()

    def atom(self) -> _Node:
        token = self.take()
        if token.kind == "LPAREN":
            node = self.or_expr()
            closing = self.take()
            if closing.kind != "RPAREN":
                raise QueryError("missing closing parenthesis")
            return node
        if token.kind == "TERM":
            return _Node("term", term=token.value)
        raise QueryError(f"unexpected {token.kind.lower()} in query")


class Query:
    """A compiled boolean query; evaluate with .matches(text)."""

    def __init__(self, source: str) -> None:
        self.source = source
        tokens = _tokenize(source)
        if not tokens:
            raise QueryError("empty query")
        self._root = _Parser(tokens).parse()

    def matches(self, text: str) -> tuple[bool, list[str]]:
        """Return (matched, positive terms that matched)."""
        hits: list[str] = []
        result = self._eval(self._root, text.lower(), hits, negated=False)
        return result, hits

    def _eval(self, node: _Node, text: str, hits: list[str], negated: bool) -> bool:
        if node.op == "term":
            found = term_in_text(node.term, text)
            if found and not negated and node.term not in hits:
                hits.append(node.term)
            return found
        if node.op == "not":
            return not self._eval(node.children[0], text, hits, not negated)
        results = [self._eval(child, text, hits, negated) for child in node.children]
        return all(results) if node.op == "and" else any(results)


def term_in_text(term: str, lowered_text: str) -> bool:
    """Whole-word, case-insensitive match ('go' must not match 'django')."""
    pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
    return re.search(pattern, lowered_text) is not None


def compile_query(source: str) -> Query | None:
    """Compile a query, treating blank input as 'match everything' (None)."""
    if not source or not source.strip():
        return None
    return Query(source)
