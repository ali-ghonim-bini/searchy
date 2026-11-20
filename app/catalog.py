from __future__ import annotations

import os
import shutil
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from .birthtime import creation_time
from .models import SearchResult
from .ranking import NO_MATCH, name_tier, tokenize


class ApplicationCatalog:
    def __init__(self):
        self.results: list[SearchResult] = []
        self.refresh()

    def refresh(self) -> None:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for app in Gio.AppInfo.get_all():
            app_id = app.get_id() or app.get_name()
            if app_id in seen or not app.should_show():
                continue
            seen.add(app_id)
            executable = _resolve_executable(app.get_executable())
            results.append(
                SearchResult(
                    kind="app",
                    name=app.get_display_name() or app.get_name(),
                    detail=app.get_description() or app.get_executable() or app_id,
                    created_at=creation_time(executable) if executable else None,
                    source_path=executable,
                    icon=app.get_icon(),
                    payload=app,
                    keywords=_keywords(app, app_id),
                )
            )
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        tokens = tokenize(query)
        ranked = []
        for result in self.results:
            tier = name_tier(result.name, tokens)
            if tier == NO_MATCH:
                # Fall back to the description, keywords, and executable name.
                if not all(token in result.keywords for token in tokens):
                    continue
            name = result.name.casefold()
            ranked.append((tier, len(name), name, result))
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked[:limit]]


def _resolve_executable(executable: str | None) -> Path | None:
    if not executable:
        return None
    expanded = os.path.expanduser(executable)
    resolved = shutil.which(expanded)
    if resolved:
        return Path(resolved).resolve()
    path = Path(expanded)
    return path.resolve() if path.is_file() else None


def _keywords(app, app_id: str) -> str:
    parts = [app.get_description(), app.get_executable(), app_id]
    # Desktop entries also carry a generic name and keywords ("browser", "terminal").
    for getter in ("get_generic_name", "get_keywords"):
        try:
            value = getattr(app, getter)()
        except (AttributeError, TypeError):
            continue
        parts.extend(value if isinstance(value, list) else [value])
    return " ".join(part for part in parts if part).casefold()
