import re

from bm25s.stopwords import STOPWORDS_EN

WORD = re.compile(r"\w+")
# Parts of an identifier: "get_max_len" -> get, max, len; "LLMEngine" -> LLM,
# Engine.
PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
STOPWORDS: frozenset[str] = frozenset(STOPWORDS_EN)


def tokenize(text: str) -> list[str]:
    """Return lowercase words, adding the parts of compound identifiers."""
    tokens: list[str] = []
    for word in WORD.findall(text):
        tokens.append(word.lower())
        parts = PART.findall(word)
        if len(parts) > 1:
            tokens += [part.lower() for part in parts]
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]
