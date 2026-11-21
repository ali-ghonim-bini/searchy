from __future__ import annotations

import re
from dataclasses import dataclass

from .ranking import MIN_INDEXED_LENGTH

_KINDS = {
    "app": "app", "apps": "app",
    "file": "file", "files": "file",
    "folder": "folder", "folders": "folder", "dir": "folder",
}


# A word may contain quoted stretches with spaces: in:"my documents".
_WORDS = re.compile(r'(?:[^\s"]|"[^"]*"?)+')


@dataclass(frozen=True)
class Query:
    """A search box entry split into words and `name:value` filters."""

    tokens: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    kind: str | None = None

    @property
    def text(self) -> str:
        return " ".join(self.tokens)

    @property
    def has_file_filters(self) -> bool:
        return bool(self.extensions or self.folders)

    @property
    def searches_files(self) -> bool:
        """Whether the query is selective enough to run against the file index."""
        return self.has_file_filters or any(
            len(token) >= MIN_INDEXED_LENGTH for token in self.tokens
        )


def parse_query(text: str) -> Query:
    tokens: list[str] = []
    extensions: list[str] = []
    folders: list[str] = []
    kind = None
    for raw_word in _WORDS.findall(text.casefold()):
        # Quotes only group words; they are not part of what is searched.
        word = raw_word.replace('"', "").strip()
        if not word:
            continue
        name, separator, value = word.partition(":")
        value = value.strip()
        if separator and name == "ext":
            extensions.extend(item.lstrip(".") for item in value.split(",") if item.strip("."))
        elif separator and name == "in":
            if value.strip("/"):
                folders.append(value.strip("/"))
        elif separator and name in {"kind", "type"} and (not value or value in _KINDS):
            kind = _KINDS.get(value, kind)
        else:
            tokens.append(word)
    return Query(tuple(tokens), tuple(extensions), tuple(folders), kind)
