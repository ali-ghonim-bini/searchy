from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from .ranking import MIN_INDEXED_LENGTH

_KINDS = {
    "app": "app", "apps": "app",
    "file": "file", "files": "file",
    "folder": "folder", "folders": "folder", "dir": "folder",
    "bookmark": "bookmark", "bookmarks": "bookmark",
}


_SIZE = re.compile(r"(?P<sign>[<>]?)=?(?P<number>\d+(?:\.\d+)?)(?P<unit>[kmgt]?b?)")
# Decimal units, as file managers show them.
_SIZE_UNITS = {
    "b": 1, "": 1, "k": 10**3, "kb": 10**3, "m": 10**6, "mb": 10**6,
    "g": 10**9, "gb": 10**9, "t": 10**12, "tb": 10**12,
}
_AGE = re.compile(r"(?P<sign>[<>]?)=?(?P<number>\d+(?:\.\d+)?)(?P<unit>[hdwmy])")
_AGE_UNITS = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400, "y": 365 * 86400}
# A word may contain quoted stretches with spaces: in:"my documents".
_WORDS = re.compile(r'(?:[^\s"]|"[^"]*"?)+')


@dataclass(frozen=True)
class Query:
    """A search box entry split into words and `name:value` filters."""

    tokens: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    kind: str | None = None
    min_size: int | None = None
    max_size: int | None = None
    modified_after: float | None = None
    modified_before: float | None = None
    content: str | None = None

    @property
    def text(self) -> str:
        return " ".join(self.tokens)

    @property
    def has_file_filters(self) -> bool:
        return bool(
            self.extensions
            or self.folders
            or self.has_size_filter
            or self.content is not None
            or self.modified_after is not None
            or self.modified_before is not None
        )

    @property
    def has_size_filter(self) -> bool:
        return self.min_size is not None or self.max_size is not None

    @property
    def searches_files(self) -> bool:
        """Whether the query is selective enough to run against the file index."""
        return self.has_file_filters or any(
            len(token) >= MIN_INDEXED_LENGTH for token in self.tokens
        )


def parse_query(text: str, now: float | None = None) -> Query:
    now = time.time() if now is None else now
    limits: dict[str, float] = {}
    content = None
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
        elif separator and name == "content":
            content = value or content
        elif separator and name == "size" and (not value or _size_limit(value)):
            limits.update(_size_limit(value) or {})
        elif separator and name == "modified" and (not value or _modified_limit(value, now)):
            limits.update(_modified_limit(value, now) or {})
        else:
            tokens.append(word)
    return Query(
        tuple(tokens),
        tuple(extensions),
        tuple(folders),
        kind,
        min_size=int(limits["min_size"]) if "min_size" in limits else None,
        max_size=int(limits["max_size"]) if "max_size" in limits else None,
        modified_after=limits.get("modified_after"),
        modified_before=limits.get("modified_before"),
        content=content,
    )


def _size_limit(value: str) -> dict[str, float] | None:
    """`>100mb` and `100mb` mean at least; `<1gb` means at most."""
    match = _SIZE.fullmatch(value)
    if not match:
        return None
    size = float(match["number"]) * _SIZE_UNITS[match["unit"] or "b"]
    return {"max_size" if match["sign"] == "<" else "min_size": size}


def _modified_limit(value: str, now: float) -> dict[str, float] | None:
    """`today`, `yesterday`, `<7d` (within 7 days) or `>30d` (older than 30 days)."""
    midnight = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if value == "today":
        return {"modified_after": midnight.timestamp()}
    if value == "yesterday":
        return {
            "modified_after": (midnight - timedelta(days=1)).timestamp(),
            "modified_before": midnight.timestamp(),
        }
    match = _AGE.fullmatch(value)
    if not match:
        return None
    moment = now - float(match["number"]) * _AGE_UNITS[match["unit"]]
    return {"modified_before" if match["sign"] == ">" else "modified_after": moment}
