from __future__ import annotations

import os
import shutil
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from .birthtime import creation_time
from .models import SearchResult


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
                )
            )
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        needle = query.strip().casefold()
        matches = [
            result
            for result in self.results
            if not needle
            or needle in result.name.casefold()
            or needle in result.detail.casefold()
        ]
        matches.sort(key=lambda result: _rank(result, needle))
        return matches[:limit]


def _resolve_executable(executable: str | None) -> Path | None:
    if not executable:
        return None
    expanded = os.path.expanduser(executable)
    resolved = shutil.which(expanded)
    if resolved:
        return Path(resolved).resolve()
    path = Path(expanded)
    return path.resolve() if path.is_file() else None


def _rank(result: SearchResult, needle: str) -> tuple[int, int, str]:
    name = result.name.casefold()
    if name == needle:
        tier = 0
    elif name.startswith(needle):
        tier = 1
    elif needle in name:
        tier = 2
    else:
        tier = 3
    return tier, len(name), name
