from __future__ import annotations

import unicodedata
from functools import lru_cache

from .models import SearchResult
from .ranking import name_tier

EMOJI_PREFIX = ":"
MIN_QUERY_LENGTH = 2
# Whole blocks of pictographs, and blocks where only symbols are wanted.
_PICTOGRAPH_RANGES = ((0x1F300, 0x1FAFF),)
_SYMBOL_RANGES = ((0x00A1, 0x00FF), (0x2010, 0x2BFF), (0x3000, 0x303F))
_SYMBOL_CATEGORIES = {"So", "Sm", "Sc", "Sk", "Pd", "Po", "Pi", "Pf"}
# Everyday words for characters whose official names say something else.
_ALIASES = {
    "lol": "face with tears of joy",
    "smile": "smiling face with smiling eyes",
    "heart": "heavy black heart",
    "sad": "crying face",
    "thumbsup": "thumbs up sign",
    "thumbsdown": "thumbs down sign",
    "ok": "ok hand sign",
    "tick": "check mark",
    "shrug": "shrug",
    "poop": "pile of poo",
    "party": "party popper",
    "100": "hundred points symbol",
    "tm": "trade mark sign",
    "dash": "em dash",
}


@lru_cache(maxsize=1)
def characters() -> tuple[tuple[str, str], ...]:
    """Every pictograph and symbol Python knows a name for, as (character, name)."""
    found = []
    for ranges, wanted in ((_PICTOGRAPH_RANGES, None), (_SYMBOL_RANGES, _SYMBOL_CATEGORIES)):
        for start, end in ranges:
            for code in range(start, end + 1):
                character = chr(code)
                name = unicodedata.name(character, "")
                if name and (wanted is None or unicodedata.category(character) in wanted):
                    found.append((character, name.lower()))
    return tuple(found)


def is_emoji_query(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(EMOJI_PREFIX) and " :" not in stripped


def emoji_results(text: str, limit: int) -> list[SearchResult]:
    """Characters whose name matches the words after the colon."""
    words = text.strip()[len(EMOJI_PREFIX) :].casefold().split()
    if len("".join(words)) < MIN_QUERY_LENGTH:
        return []
    found: dict[str, str] = {}
    alias = _ALIASES.get(" ".join(words))
    if alias:
        found.update(_matching(alias.split()))
    found.update((key, value) for key, value in _matching(words) if key not in found)
    # Official names say "smiling" and "laughing" where people type "smile",
    # so near word forms are listed after the exact matches.
    stems = [word[:-1] if len(word) > 4 else word for word in words]
    if stems != words:
        found.update((key, value) for key, value in _matching(stems) if key not in found)
    return [
        SearchResult(
            kind="emoji",
            name=f"{character}   {name}",
            detail="Enter copies it",
            created_at=None,
            payload=character,
        )
        for character, name in list(found.items())[:limit]
    ]


def _matching(tokens: list[str]) -> list[tuple[str, str]]:
    ranked = []
    for character, name in characters():
        tier = name_tier(name, tokens)
        if tier <= 3:
            ranked.append((tier, len(name), name, character))
    ranked.sort()
    return [(character, name) for _tier, _length, name, character in ranked]
