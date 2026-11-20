from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PathFilter:
    """Decides which directories the indexer skips.

    Only a directory's own name and path are checked: the indexer never descends
    into a skipped directory, so its ancestors were already accepted.
    """

    excluded_paths: tuple[str, ...]
    excluded_names: tuple[str, ...]
    index_hidden: bool

    @classmethod
    def create(
        cls, state_directory: Path, patterns: tuple[str, ...], index_hidden: bool
    ) -> "PathFilter":
        # A pattern with a slash names one directory; any other matches by name.
        paths = [str(state_directory.resolve())]
        names = []
        for pattern in patterns:
            if "/" in pattern:
                paths.append(str(Path(pattern).expanduser().resolve()))
            else:
                names.append(pattern)
        return cls(tuple(paths), tuple(names), index_hidden)

    def signature(self) -> str:
        return repr((sorted(self.excluded_paths), sorted(self.excluded_names), self.index_hidden))

    def skips_directory(self, path: Path) -> bool:
        name = path.name
        if not self.index_hidden and name.startswith("."):
            return True
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in self.excluded_names):
            return True
        return str(path) in self.excluded_paths
