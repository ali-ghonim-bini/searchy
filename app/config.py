from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        values = _read_env(env_file or Path(".env"))

        def value(name: str, default: str) -> str:
            return os.environ.get(name, values.get(name, default))

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
                value("INDEX_INTERVAL_SECONDS", "300"), "INDEX_INTERVAL_SECONDS"
            ),
            default_search_type=search_type,
        )
