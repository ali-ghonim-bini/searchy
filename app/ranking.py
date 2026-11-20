from __future__ import annotations

import re

from .models import SearchResult

# File and folder names are indexed as trigrams, so shorter words cannot use the index.
MIN_INDEXED_LENGTH = 3
NO_MATCH = 6
_WORDS = re.compile(r"[^\W_]+")
_NOISE_PARTS = ("/.", "/node_modules/", "/__pycache__/")


def tokenize(query: str) -> list[str]:
    return query.casefold().split()


def name_tier(name: str, tokens: list[str]) -> int:
    """Lower is better: 0 exact, 1 prefix, 2 word starts, 3 contains, 4 initials, 5 fuzzy."""
    if not tokens:
        return 0
    folded = name.casefold()
    full = " ".join(tokens)
    if folded == full or folded.rpartition(".")[0] == full:
        return 0
    if folded.startswith(full):
        return 1
    words = _WORDS.findall(folded)
    if all(any(word.startswith(token) for word in words) for token in tokens):
        return 2
    if all(token in folded for token in tokens):
        return 3
    if len(tokens) == 1 and len(full) >= 2:
        if "".join(word[0] for word in words).startswith(full):
            return 4
        if len(full) >= MIN_INDEXED_LENGTH and _is_subsequence(full, folded):
            return 5
    return NO_MATCH


def match_spans(name: str, tokens: list[str]) -> list[tuple[int, int]]:
    """Character ranges of `name` that the query words matched, merged and sorted."""
    folded = name.casefold()
    # Case folding can change a string's length; positions would then be wrong.
    if len(folded) != len(name):
        return []
    spans = []
    for token in tokens:
        start = folded.find(token)
        while token and start >= 0:
            spans.append((start, start + len(token)))
            start = folded.find(token, start + 1)
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def within_one_edit(first: str, second: str) -> bool:
    """True when one insertion, deletion, substitution or swap turns one into the other."""
    if first == second:
        return True
    if abs(len(first) - len(second)) > 1:
        return False
    if len(first) > len(second):
        first, second = second, first
    start = 0
    while start < len(first) and first[start] == second[start]:
        start += 1
    if len(first) == len(second):
        if first[start + 1 :] == second[start + 1 :]:
            return True
        return (
            start + 1 < len(first)
            and first[start] == second[start + 1]
            and first[start + 1] == second[start]
            and first[start + 2 :] == second[start + 2 :]
        )
    return first[start:] == second[start + 1 :]


def fuzzy_contains(text: str, token: str) -> bool:
    """Whether some stretch of `text` is `token` with at most one typing mistake."""
    for length in (len(token), len(token) - 1, len(token) + 1):
        for start in range(len(text) - length + 1):
            if within_one_edit(text[start : start + length], token):
                return True
    return False


def is_noise(path: str) -> bool:
    """Hidden and dependency directories are rarely what a search is looking for."""
    return any(part in path for part in _NOISE_PARTS)


def sort_key(result: SearchResult, tokens: list[str], usage: float = 0.0) -> tuple:
    """Order by match quality, then by how often the result has been opened."""
    name = result.name.casefold()
    if not tokens:
        return (0, -usage, 0, False, 0, name)
    return (
        name_tier(result.name, tokens),
        -usage,
        0 if result.kind == "app" else 1,
        is_noise(str(result.path)) if result.path else False,
        len(name),
        name,
    )


def _is_subsequence(needle: str, haystack: str) -> bool:
    """Typo-tolerant match: letters in order, from the first letter, close together."""
    if not haystack.startswith(needle[0]):
        return False
    position = -1
    for character in needle:
        position = haystack.find(character, position + 1)
        if position < 0:
            return False
    return position <= 2 * len(needle)
