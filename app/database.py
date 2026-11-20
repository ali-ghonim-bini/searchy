from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .models import SearchResult
from .ranking import MIN_INDEXED_LENGTH, tokenize

_RESULT_COLUMNS = (
    "entries.path, entries.name, entries.parent, entries.kind, entries.created_at"
)
# Sorts hidden and dependency directories after everything else.
_NOISE_SQL = (
    "(instr(entries.path, '/.') > 0 OR instr(entries.path, '/node_modules/') > 0"
    " OR instr(entries.path, '/__pycache__/') > 0)"
)


@dataclass(frozen=True)
class IndexedPath:
    path: Path
    kind: str
    created_at: float | None
    modified_at: float


class SearchDatabase:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    parent TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('file', 'folder')),
                    created_at REAL,
                    modified_at REAL NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scan_seen (
                    path TEXT PRIMARY KEY
                ) WITHOUT ROWID;
                """
            )
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            schema_version = int(row[0]) if row else 0
            if schema_version < 2:
                connection.executescript(
                    """
                    DROP TRIGGER IF EXISTS entries_ai;
                    DROP TRIGGER IF EXISTS entries_ad;
                    DROP TRIGGER IF EXISTS entries_au;
                    DROP TABLE IF EXISTS entries_fts;
                    CREATE VIRTUAL TABLE entries_fts USING fts5(
                        name, content='entries', content_rowid='id', tokenize='trigram'
                    );
                    CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
                        INSERT INTO entries_fts(rowid, name) VALUES (new.id, new.name);
                    END;
                    CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
                        INSERT INTO entries_fts(entries_fts, rowid, name)
                        VALUES ('delete', old.id, old.name);
                    END;
                    CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
                        INSERT INTO entries_fts(entries_fts, rowid, name)
                        VALUES ('delete', old.id, old.name);
                        INSERT INTO entries_fts(rowid, name) VALUES (new.id, new.name);
                    END;
                    INSERT INTO entries_fts(rowid, name) SELECT id, name FROM entries;
                    INSERT INTO metadata(key, value) VALUES ('schema_version', '2')
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value;
                    """
                )
            if schema_version < 3:
                connection.executescript(
                    """
                    DROP TRIGGER IF EXISTS entries_au;
                    CREATE TRIGGER entries_au AFTER UPDATE ON entries
                    WHEN old.name IS NOT new.name BEGIN
                        INSERT INTO entries_fts(entries_fts, rowid, name)
                        VALUES ('delete', old.id, old.name);
                        INSERT INTO entries_fts(rowid, name) VALUES (new.id, new.name);
                    END;
                    INSERT INTO metadata(key, value) VALUES ('schema_version', '3')
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value;
                    """
                )

    def reset(self) -> None:
        """Discard the index file; deleting most rows one by one is far slower."""
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        self._initialize()

    def index_rules(self) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'index_rules'"
            ).fetchone()
        return row[0] if row else None

    def set_index_rules(self, rules: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('index_rules', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (rules,),
            )

    def next_generation(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'generation'"
            ).fetchone()
            generation = int(row[0]) + 1 if row else 1
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('generation', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(generation),),
            )
            connection.execute("DELETE FROM scan_seen")
        return generation

    def upsert_many(
        self,
        entries: Iterable[IndexedPath],
        generation: int,
        track_scan: bool = True,
    ) -> None:
        rows = [
            (
                str(entry.path),
                entry.path.name or str(entry.path),
                str(entry.path.parent),
                entry.kind,
                entry.created_at,
                entry.modified_at,
                generation,
            )
            for entry in entries
        ]
        if not rows:
            return
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO entries(path, name, parent, kind, created_at, modified_at, generation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    parent=excluded.parent,
                    kind=excluded.kind,
                    created_at=excluded.created_at,
                    modified_at=excluded.modified_at,
                    generation=excluded.generation
                WHERE entries.name IS NOT excluded.name
                    OR entries.parent IS NOT excluded.parent
                    OR entries.kind IS NOT excluded.kind
                    OR entries.created_at IS NOT excluded.created_at
                    OR entries.modified_at IS NOT excluded.modified_at
                """,
                rows,
            )
            if track_scan:
                connection.executemany(
                    "INSERT OR IGNORE INTO scan_seen(path) VALUES (?)",
                    ((row[0],) for row in rows),
                )

    def finish_generation(self, generation: int, roots: tuple[Path, ...]) -> None:
        clauses = []
        parameters: list[object] = []
        for root in roots:
            root_text = str(root)
            clauses.append("(path = ? OR path LIKE ? ESCAPE '\\')")
            parameters.extend((root_text, _escape_like(root_text) + "/%"))
        if not clauses:
            return
        with self._connection() as connection:
            connection.execute(
                f"DELETE FROM entries WHERE ({' OR '.join(clauses)}) "
                "AND NOT EXISTS (SELECT 1 FROM scan_seen WHERE scan_seen.path = entries.path)",
                parameters,
            )
            connection.execute("DELETE FROM scan_seen")
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('last_completed_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(time.time()),),
            )

    def upsert(self, entry: IndexedPath) -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'generation'"
            ).fetchone()
            generation = int(row[0]) if row else 0
        self.upsert_many((entry,), generation, track_scan=False)

    def delete_path(self, path: Path) -> None:
        text = str(path)
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM entries WHERE path = ? OR path LIKE ? ESCAPE '\\'",
                (text, _escape_like(text) + "/%"),
            )

    def search(
        self,
        query: str,
        limit: int,
        kind: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[SearchResult]:
        """Match every word of the query, in any order, against names then paths."""
        if kind not in {None, "file", "folder"}:
            raise ValueError("kind must be file, folder, or None")
        tokens = tokenize(query)
        indexed = [token for token in tokens if len(token) >= MIN_INDEXED_LENGTH]
        if not indexed:
            return []
        if cancel_event and cancel_event.is_set():
            return []
        match = " AND ".join(_fts_phrase(token) for token in indexed)
        conditions = ["entries_fts MATCH ?"]
        parameters: list[object] = [match]
        if kind:
            conditions.append("entries.kind = ?")
            parameters.append(kind)
        for token in tokens:
            if len(token) < MIN_INDEXED_LENGTH:
                conditions.append("lower(entries.name) LIKE ? ESCAPE '\\'")
                parameters.append("%" + _escape_like(token) + "%")
        full = " ".join(tokens)
        parameters.extend(
            (full, _escape_like(full) + ".%", _escape_like(tokens[0]) + "%", limit)
        )
        sql = f"""
            SELECT {_RESULT_COLUMNS}
            FROM entries
            JOIN entries_fts ON entries.id = entries_fts.rowid
            WHERE {" AND ".join(conditions)}
            ORDER BY CASE
                WHEN lower(entries.name) = ? THEN 0
                WHEN lower(entries.name) LIKE ? ESCAPE '\\' THEN 0
                WHEN lower(entries.name) LIKE ? ESCAPE '\\' THEN 1
                ELSE 2
            END, {_NOISE_SQL}, length(entries.name), entries.modified_at DESC
            LIMIT ?
        """
        with self._connection() as connection:
            if cancel_event:
                connection.set_progress_handler(
                    lambda: 1 if cancel_event.is_set() else 0, 1000
                )
            try:
                rows = connection.execute(sql, parameters).fetchall()
                seen = {row[0] for row in rows}
                if len(rows) < limit and len(tokens) > 1:
                    rows.extend(
                        self._search_paths(
                            connection, tokens, indexed, kind, limit - len(rows), seen
                        )
                    )
                if len(rows) < limit:
                    rows.extend(
                        self._search_folder_paths(
                            connection, match, kind, limit - len(rows), seen
                        )
                    )
            except sqlite3.OperationalError as error:
                if cancel_event and cancel_event.is_set() and "interrupted" in str(error):
                    return []
                raise
        return [
            SearchResult(
                kind=row[3],
                name=row[1],
                detail=row[2],
                created_at=row[4],
                path=Path(row[0]),
                source_path=Path(row[0]),
            )
            for row in rows
        ]

    def _search_paths(
        self,
        connection: sqlite3.Connection,
        tokens: list[str],
        indexed: list[str],
        kind: str | None,
        limit: int,
        seen: set[str],
    ) -> list[tuple]:
        """Find entries whose name has one word while parent folders have the rest."""
        results: list[tuple] = []
        # Longer words are usually rarer, so they make cheaper index lookups.
        for anchor in sorted(indexed, key=len, reverse=True)[:2]:
            if len(results) >= limit:
                break
            conditions = ["entries_fts MATCH ?"]
            parameters: list[object] = [_fts_phrase(anchor)]
            if kind:
                conditions.append("entries.kind = ?")
                parameters.append(kind)
            for token in tokens:
                if token != anchor:
                    conditions.append("lower(entries.path) LIKE ? ESCAPE '\\'")
                    parameters.append("%" + _escape_like(token) + "%")
            parameters.append(limit + len(seen))
            rows = connection.execute(
                f"""
                SELECT {_RESULT_COLUMNS}
                FROM entries
                JOIN entries_fts ON entries.id = entries_fts.rowid
                WHERE {" AND ".join(conditions)}
                ORDER BY {_NOISE_SQL}, length(entries.path)
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            for row in rows:
                if len(results) >= limit:
                    break
                if row[0] not in seen:
                    seen.add(row[0])
                    results.append(row)
        return results

    def _search_folder_paths(
        self,
        connection: sqlite3.Connection,
        match: str,
        kind: str | None,
        limit: int,
        existing_paths: set[str],
    ) -> list[tuple]:
        folder_rows = connection.execute(
            """
            SELECT entries.path
            FROM entries
            JOIN entries_fts ON entries.id = entries_fts.rowid
            WHERE entries_fts MATCH ? AND entries.kind = 'folder'
            ORDER BY length(entries.path)
            LIMIT 10
            """,
            (match,),
        ).fetchall()
        results: list[tuple] = []
        for (folder_path,) in folder_rows:
            if len(results) >= limit:
                break
            prefix = folder_path.rstrip("/") + "/"
            upper_bound = prefix[:-1] + "0"
            parameters: list[object] = [prefix, upper_bound]
            kind_condition = ""
            if kind:
                kind_condition = " AND kind = ?"
                parameters.append(kind)
            parameters.append(limit - len(results))
            descendants = connection.execute(
                f"""
                SELECT path, name, parent, kind, created_at
                FROM entries
                WHERE path >= ? AND path < ?{kind_condition}
                ORDER BY path
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            for row in descendants:
                if row[0] not in existing_paths:
                    existing_paths.add(row[0])
                    results.append(row)
        return results

    def has_creation_dates(self) -> bool:
        with self._connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM entries WHERE created_at IS NOT NULL LIMIT 1"
                ).fetchone()
                is not None
            )

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM entries").fetchone()[0])

    def folder_count(self) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM entries WHERE kind = 'folder'"
                ).fetchone()[0]
            )

    def index_is_fresh(self, interval: int) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'last_completed_at'"
            ).fetchone()
        return row is not None and time.time() - float(row[0]) < interval


def _fts_phrase(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
