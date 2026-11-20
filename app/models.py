from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    kind: str
    name: str
    detail: str
    created_at: float | None
    path: Path | None = None
    source_path: Path | None = None
    icon: Any = None
    payload: Any = None
    keywords: str = ""
