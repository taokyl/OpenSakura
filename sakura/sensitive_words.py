"""Tiered sensitive-word matcher.

- Lowercased, NFKC-normalized
- Whole-word via \\b{word}\\b (so 'rigger' won't match 'trigger')
- Leetspeak fold: 1->i, 0->o, 3->e, 4->a, @->a, $->s, plus strip zero-width
- match() returns the highest-severity tier hit (severe > bad > mild)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

Tier = Literal["mild", "bad", "severe"]
_ORDER: list[Tier] = ["mild", "bad", "severe"]

_ZERO_WIDTH = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")
# Context-aware @ handling: `@` at a word boundary is a separator (mention prefix);
# `@` between word chars folds to `a` (leetspeak for cl@nker style).
_SEP_AT = re.compile(r"(^|\W)@")                # @ at start-of-string or after non-word
_LEETSPEAK = str.maketrans({"1": "i", "0": "o", "3": "e", "4": "a", "@": "a", "$": "s", "5": "s"})
# `_` `-` `+` `.` are join chars — force word boundaries around them.
_GLUE_TO_SPACE = re.compile(r"[_\-+.]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t)
    t = t.lower()
    t = _SEP_AT.sub(r"\1 ", t)                  # "@clanker" -> " clanker", "cl@nker" untouched
    t = t.translate(_LEETSPEAK)                 # remaining @ (only in mid-word) folds to 'a'
    t = _GLUE_TO_SPACE.sub(" ", t)
    return t


class WordBank:
    def __init__(self, tiers: dict[str, list[str]]):
        self._patterns: dict[Tier, re.Pattern | None] = {}
        for tier in _ORDER:
            words = [w.strip().lower() for w in (tiers.get(tier) or []) if w.strip()]
            if not words:
                self._patterns[tier] = None
                continue
            escaped = "|".join(re.escape(w) for w in words)
            # trailing `s?` catches plural forms (rigger -> riggers) without adding
            # every plural to the bank. Still word-bounded so "snigger" doesn't match.
            self._patterns[tier] = re.compile(rf"\b(?:{escaped})s?\b", re.IGNORECASE)

    def match(self, text: str) -> Tier | None:
        """Return the highest-severity tier that matches, or None."""
        norm = normalize(text)
        for tier in reversed(_ORDER):
            pat = self._patterns.get(tier)
            if pat and pat.search(norm):
                return tier
        return None
