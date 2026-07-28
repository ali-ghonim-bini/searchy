# Searchy

Searchy is an instant GTK 4 desktop search application for Ubuntu GNOME on
Wayland. It searches installed applications and indexed file and folder names
under the configured roots. Searchy runs as a user service and opens with a
customizable GNOME shortcut, Alt+S by default.

## Features

- Searches applications, files, folders, or all three together with separate
  filters for each type.
- Uses a persistent SQLite FTS5 trigram index for substring matching.
- Keeps the index current with Linux inotify and periodic reconciliation.
- Sorts by relevance, name, or creation date when the filesystem exposes one.
- Opens results with the default desktop handler.
- Reveals a file, folder, or application's resolved executable from the
  right-click menu.
- Shows thumbnail previews for image-file results.
- Moves files and folders to Trash from the right-click menu after confirmation.
- Supports Enter, double-click, arrow navigation, Escape, and keyboard context
  menu activation.

## Install

Searchy requires Python 3, GTK 4, PyGObject, libadwaita, SQLite FTS5, systemd,
and GNOME `gsettings`. Install and start it without root privileges:

```bash
./install.sh
```

The first index of the home directory runs in the background. View progress or
errors with:

```bash
systemctl --user status searchy.service
journalctl --user -u searchy.service -f
```

## Configuration

Edit `.env`, then run `./install.sh` again. `SEARCH_ROOTS` accepts a
colon-separated list.

```dotenv
SEARCH_ROOTS=/home/bini
DATABASE_PATH=~/.local/state/searchy/index.sqlite3
NATIVE_SHORTCUT='<Alt>s'
DEFAULT_SEARCH_TYPE=everything
RESULT_LIMIT=100
INDEX_INTERVAL_SECONDS=3600
LOG_LEVEL=INFO
```

The shortcut uses GNOME accelerator syntax. The index is stored at
`~/.local/state/searchy/index.sqlite3` by default. Directory symlinks are listed
but are not followed, inaccessible paths are skipped, and Searchy's own state
directory is excluded.

## Usage

1. Press Alt+S.
2. Enter part of an application name, filename, or path.
3. Choose Everything, Apps, Files, or Folders beside the search field.
4. Optionally enable Sort results and choose the field and direction.
5. Press Enter or double-click to open a result; single-click only selects it.
6. Right-click for Open or Open Source Location.

Escape hides the window while the indexing service remains active.
Application results appear immediately. File and folder searches start after
three characters so large indexes never fall back to an unbounded scan.

## Logs

Searchy writes to the systemd user journal, which handles persistence and
rotation. Follow logs with:

```bash
journalctl --user -u searchy.service -f
```

Search logs include mode, query length, result count, and duration without
recording the private query text. Index logs include reconciliation duration
and item count.

## Remove

Preserve the existing index:

```bash
./uninstall.sh
```

Remove the index too:

```bash
./uninstall.sh --purge
```

## Tests

```bash
python3 -m unittest discover -v
```
