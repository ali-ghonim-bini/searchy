from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# Dependency and package directories hold most files on a typical home directory.
DEFAULT_EXCLUDE = "node_modules:__pycache__:site-packages:venv:~/snap"


DEFAULT_WEB_SEARCH_URL = "https://duckduckgo.com/?q={query}"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _boolean(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _web_search_url(value: str) -> str:
    url = value.strip()
    if url and (not url.startswith(("https://", "http://")) or "{query}" not in url):
        raise ValueError("WEB_SEARCH_URL must be an http(s) URL containing {query}")
    return url


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


@dataclass(frozen=True)
class Config:
    search_roots: tuple[Path, ...]
    database_path: Path
    result_limit: int
    index_interval_seconds: int
    default_search_type: str
    exclude_patterns: tuple[str, ...]
    index_hidden: bool
    remember_usage: bool
    hide_on_focus_loss: bool
    web_search_url: str
    show_preview: bool
    search_bookmarks: bool
    index_removable: bool

    @classmethod
    def load(
        cls, env_file: Path | None = None, environ: dict[str, str] | None = None
    ) -> "Config":
        environ = os.environ if environ is None else environ
        values = _read_env(env_file or Path(__file__).resolve().parent.parent / ".env")

        def value(name: str, default: str) -> str:
            return environ.get(name, values.get(name, default))

        roots = tuple(
            Path(item).expanduser().resolve()
            for item in value("SEARCH_ROOTS", "~").split(":")
            if item.strip()
        )
        if not roots:
            raise ValueError("SEARCH_ROOTS must contain at least one path")
        search_type = value("DEFAULT_SEARCH_TYPE", "everything").lower()
        if search_type not in {"everything", "apps", "files", "folders"}:
            raise ValueError(
                "DEFAULT_SEARCH_TYPE must be everything, apps, files, or folders"
            )
        return cls(
            search_roots=roots,
            database_path=Path(
                value("DATABASE_PATH", "~/.local/state/searchy/index.sqlite3")
            ).expanduser(),
            result_limit=_positive_int(value("RESULT_LIMIT", "100"), "RESULT_LIMIT"),
            index_interval_seconds=_positive_int(
                value("INDEX_INTERVAL_SECONDS", "3600"), "INDEX_INTERVAL_SECONDS"
            ),
            default_search_type=search_type,
            exclude_patterns=tuple(
                item.strip()
                for item in value("EXCLUDE", DEFAULT_EXCLUDE).split(":")
                if item.strip()
            ),
            index_hidden=_boolean(value("INDEX_HIDDEN", "false"), "INDEX_HIDDEN"),
            remember_usage=_boolean(value("REMEMBER_USAGE", "true"), "REMEMBER_USAGE"),
            hide_on_focus_loss=_boolean(
                value("HIDE_ON_FOCUS_LOSS", "true"), "HIDE_ON_FOCUS_LOSS"
            ),
            web_search_url=_web_search_url(value("WEB_SEARCH_URL", DEFAULT_WEB_SEARCH_URL)),
            show_preview=_boolean(value("SHOW_PREVIEW", "true"), "SHOW_PREVIEW"),
            search_bookmarks=_boolean(value("SEARCH_BOOKMARKS", "true"), "SEARCH_BOOKMARKS"),
            index_removable=_boolean(value("INDEX_REMOVABLE", "false"), "INDEX_REMOVABLE"),
        )
