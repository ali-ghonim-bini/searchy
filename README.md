# Searchy

Searchy is an instant GTK 4 desktop search application for Ubuntu GNOME on
Wayland. It searches installed applications and indexed file and folder names
under the configured roots. Searchy runs as a user service and opens with a
customizable GNOME shortcut, Alt+F by default.

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
NATIVE_SHORTCUT='<Alt>f'
DEFAULT_SEARCH_TYPE=everything
RESULT_LIMIT=100
INDEX_INTERVAL_SECONDS=3600
EXCLUDE=node_modules:__pycache__:site-packages:venv:~/snap
INDEX_HIDDEN=false
REMEMBER_USAGE=true
HIDE_ON_FOCUS_LOSS=true
SHOW_PREVIEW=true
WEB_SEARCH_URL='https://duckduckgo.com/?q={query}'
LOG_LEVEL=INFO
```

### What gets indexed

Searchy skips the directories that hold most files but are rarely searched:

- `EXCLUDE` is a colon-separated list. An entry without a slash matches any
  directory with that name and may use wildcards (`build`, `*.egg-info`). An
  entry with a slash names one directory (`~/snap`, `/mnt/backup`).
- `INDEX_HIDDEN=false` skips hidden directories such as `~/.cache`. Hidden
  files inside indexed directories are still found. Set it to `true` to index
  everything.
- A directory listed in `SEARCH_ROOTS` is always indexed, even when hidden, so
  `SEARCH_ROOTS=~:~/.config` adds one hidden directory back.

Changing `SEARCH_ROOTS`, `EXCLUDE`, or `INDEX_HIDDEN` rebuilds the index the
next time the service starts. Applications stay searchable while it rebuilds.

A smaller index also keeps the folder count under the kernel's inotify watch
limit (`fs.inotify.max_user_watches`), so new and renamed files appear within
moments. Above that limit Searchy only notices changes at each
`INDEX_INTERVAL_SECONDS` rescan.

The shortcut uses GNOME accelerator syntax. The index is stored at
`~/.local/state/searchy/index.sqlite3` by default. Directory symlinks are listed
but are not followed, inaccessible paths are skipped, and Searchy's own state
directory is excluded.

## Usage

1. Press Alt+F.
2. Enter part of an application name, filename, or path.
3. Choose Everything, Apps, Files, or Folders beside the search field.
4. Optionally enable Sort results and choose the field and direction.
5. Press Enter or double-click to open a result; single-click only selects it.
6. Right-click for Open or Open Source Location.

Escape hides the window while the indexing service remains active.
Pressing the shortcut again while Searchy is open hides it. The service
starts with the graphical session, and the shortcut starts it on demand if it
is not running.

Application results appear immediately. File and folder searches need one word
of at least three characters so large indexes never fall back to an unbounded
scan.

The letters that matched are shown in bold in each result. Words match in any order, so `2024 report` finds `Annual Report 2024.pdf`. A
word may also match a parent folder: `invoices march` finds `march.pdf` inside
`invoices/`. Applications also match by keyword (`browser`), initials (`vsc`),
and small typos. When no file or folder matches, Searchy retries allowing one
typing mistake in each word of five letters or more, so `holliday` still
finds `holiday.jpg`. Hidden and dependency directories rank below other matches.

### Learning from use

Searchy remembers which results you open and ranks them first among equally
good matches, so a frequently used application comes up after a letter or two.
With an empty search box, applications are listed most used first. An item
opened a month ago counts half as much as one opened today.

The history is stored in `~/.local/state/searchy/usage.sqlite3`, readable only
by you, and survives index rebuilds. Set `REMEMBER_USAGE=false` to turn it off;
delete the file to forget it.

### More than files

- **Calculator.** Type arithmetic such as `(1200 - 350) * 1.14` or `sqrt(2)`
  and the answer appears as the first result; Enter copies it. `+ - * / // %`,
  `^` or `**` for powers, parentheses, `pi`, `e`, and `sqrt`, `abs`, `round`,
  `sin`, `cos`, `tan`, `log`, `log10` are supported.
- **Recent files.** An empty search box lists the applications you use most,
  then the files your desktop recorded as recently used, then other
  applications.
- **Web search.** When nothing matches, the only result offers to search the
  web for your words in the default browser. Nothing is sent anywhere unless
  you open that result. `WEB_SEARCH_URL` sets the search engine; it must
  contain `{query}`. Leave it empty to turn the offer off.

### Commands

- **Shell commands.** Start with `>` to run a command: `> code ~/project`.
  The first row runs it in the background from your home folder; the second
  opens a terminal, runs it there, and keeps the terminal open so you can read
  the output. Nothing runs until you press Enter on a row.
- **System actions.** Type `lock`, `sleep`, `log out`, `restart` or
  `shut down`. Lock and Suspend act at once; Log Out, Restart and Shut Down
  ask for confirmation first, with Cancel as the default.

### Emoji and symbols

Start with a colon to find a character by name: `:smile`, `:heart`,
`:arrow right`, `:degree`, `:euro`. Enter copies it and hides Searchy so you
can paste it where you were. A few everyday words are understood too, such as
`:lol`, `:thumbsup`, `:tick` and `:dash`.

The names come from the Unicode data shipped with Python, so nothing is
downloaded and there is no extra file to install.

### Window

Searchy opens as a launcher panel without a title bar. Drag any empty area to
move it. It hides when you open a result, press Escape, press the shortcut
again, or click another window. Set `HIDE_ON_FOCUS_LOSS=false` to keep it open
when another window takes focus.

### Preview

Selecting a file or folder shows a pane on the right with its type, size, last
change and location. Images are shown, text files show their first lines, and
folders show how many items they hold. Files are only read when selected, and
only the first 4 kB of a text file. Set `SHOW_PREVIEW=false` to hide the pane.

### Keyboard

| Keys | Action |
|---|---|
| Up / Down | Move through results |
| Enter | Open the selected result |
| Ctrl+Enter | Show the selected result in the file manager |
| Alt+1 … Alt+9 | Open that result directly; each row shows its number |
| Ctrl+Shift+C | Copy the selected result's path |
| F2 | Rename the selected file or folder |
| Ctrl+Shift+T | Open a terminal in the selected folder, or in a file's folder |
| Menu or Shift+F10 | Open the right-click menu, which also has Copy Path |
| Escape | Hide Searchy |

### Searching inside files

`content:` looks inside files instead of at their names. It runs
[ripgrep](https://github.com/BurntSushi/ripgrep) over the search roots when you
ask, so the index stays small and nothing about file contents is stored. Each
result shows the first matching line.

- It skips what the index skips (`EXCLUDE`, hidden folders unless
  `INDEX_HIDDEN=true`), plus binary files, files over 2 MB, and anything your
  `.gitignore` files ignore.
- Combine it with other filters: `content:todo ext:py in:searchy`.
- It stops after `RESULT_LIMIT` matches or 15 seconds, whichever comes first.
- It needs the `rg` command (`sudo apt install ripgrep`). Without it,
  `content:` finds nothing and the journal says why.

### Actions

Right-click a file or folder (or press Menu) for more than opening it:

- **Open with …** lists other applications that can open that type of file.
- **Copy File / Copy Folder** puts the item itself on the clipboard, ready to
  paste in a file manager.
- **Rename…** asks for a new name. It refuses names containing `/` and names
  already taken in that folder, so nothing is overwritten.
- **Open Terminal Here** starts the first terminal found among Ptyxis, GNOME
  Terminal, Console, Konsole, Xfce Terminal and `x-terminal-emulator`.
- **Move to Trash** asks for confirmation first.

After renaming a folder, the files inside it reappear under the new path at the
next rescan (`searchy reindex`, or within `INDEX_INTERVAL_SECONDS`).

### Filters

Type filters in the search box alongside, or instead of, ordinary words:

| Filter | Finds | Example |
|---|---|---|
| `ext:` | Files with that extension; separate several with commas | `invoice ext:pdf`, `ext:jpg,png` |
| `in:` | Items inside a folder whose name starts with the value | `report in:Documents` |
| `kind:` | Only `app`, `file`, or `folder`; overrides the dropdown | `projects kind:folder` |
| `size:` | Files at least (`>`, or no sign) or at most (`<`) a size; units `kb`, `mb`, `gb` | `size:>100mb`, `size:<10kb` |
| `modified:` | Changed `today`, `yesterday`, within (`<`) or longer ago than (`>`) a period; units `h`, `d`, `w`, `m`, `y` | `modified:<7d`, `modified:>1y` |
| `content:` | Files whose text contains the value; quote a phrase | `content:invoice`, `content:"due date" ext:md` |

Filters combine: `ext:pdf in:invoices 2024`. A filter on its own is enough to
search files, so `ext:iso` lists every ISO image. `size:>1gb` lists your
largest files and `modified:today` what you worked on today. Put quotes around
a folder name with spaces: `in:"My Documents"`.

Quotes also make an exact phrase: `"annual report"` only finds names with
those words next to each other, in that order.

## The `searchy` command

`./install.sh` puts a `searchy` command in `~/.local/bin`:

| Command | What it does |
|---|---|
| `searchy status` | Shows whether the service is running, how many items are indexed, when the last full scan finished, the index size, and whether live updates are on |
| `searchy reindex` | Rescans the search roots now instead of waiting for the next interval |
| `searchy reindex --rebuild` | Discards the index and builds it again from scratch |
| `searchy show` | Shows or hides the search window, like the shortcut |

The usage history is kept by a rebuild. If `searchy` is not found, log out and
back in so `~/.local/bin` joins your `PATH`.

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
