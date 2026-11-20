from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TEXT_BYTES = 4000
TEXT_LINES = 30
TEXT_COLUMNS = 80
FOLDER_COUNT_LIMIT = 1000


@dataclass(frozen=True)
class Preview:
    title: str
    details: tuple[tuple[str, str], ...]
    text: str | None = None
    is_image: bool = False


def format_size(size: int) -> str:
    """Decimal units, as file managers show them."""
    value = float(size)
    for unit in ("bytes", "kB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} TB"


def describe(path: Path) -> Preview:
    """Collect what the preview pane shows for one file or folder."""
    try:
        stat = path.stat()
    except OSError:
        return Preview(path.name, (("Status", "No longer available"),))
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    if path.is_dir():
        details = (
            ("Type", "Folder"),
            ("Contains", _folder_count(path)),
            ("Modified", modified),
            ("Location", str(path.parent)),
        )
        return Preview(path.name, details)
    mime_type = mimetypes.guess_type(path.name)[0]
    details = (
        ("Type", mime_type or "Unknown"),
        ("Size", format_size(stat.st_size)),
        ("Modified", modified),
        ("Location", str(path.parent)),
    )
    if mime_type and mime_type.startswith("image/"):
        return Preview(path.name, details, is_image=True)
    return Preview(path.name, details, text=_text_excerpt(path))


def _folder_count(path: Path) -> str:
    try:
        with os.scandir(path) as entries:
            count = 0
            for _entry in entries:
                count += 1
                if count > FOLDER_COUNT_LIMIT:
                    return f"more than {FOLDER_COUNT_LIMIT} items"
    except OSError:
        return "cannot be read"
    return "1 item" if count == 1 else f"{count} items"


def _text_excerpt(path: Path) -> str | None:
    """The first lines of a text file, or None when it is not readable text."""
    try:
        with path.open("rb") as file:
            data = file.read(TEXT_BYTES)
    except OSError:
        return None
    if not data or b"\0" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        # A multi-byte character cut off by the read limit is not binary data.
        if error.start < len(data) - 4:
            return None
        text = data[: error.start].decode("utf-8")
    lines = [line[:TEXT_COLUMNS] for line in text.splitlines()[:TEXT_LINES]]
    return "\n".join(lines)
