from __future__ import annotations

import logging
import os
import signal
import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gdk, Gio, GLib

from .bookmarks import BookmarkCatalog
from .catalog import ApplicationCatalog
from .config import Config
from .content import search_content
from .database import INDEX_VERSION, SearchDatabase
from .drives import DriveMonitor
from .excludes import PathFilter
from .indexer import FileIndexer
from .ui import SearchWindow
from .usage import UsageStore

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)


class SearchyApplication(Adw.Application):
    def __init__(self, config: Config):
        super().__init__(
            application_id="io.github.alighonimbini.Searchy",
            flags=Gio.ApplicationFlags.IS_SERVICE,
        )
        self.config = config
        self.database: SearchDatabase | None = None
        self.catalog: ApplicationCatalog | None = None
        self.window: SearchWindow | None = None
        self.indexer: FileIndexer | None = None
        self.app_monitor: Gio.AppInfoMonitor | None = None
        self.drive_monitor: DriveMonitor | None = None
        self.exit_code = 0

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self.hold()
        # A failed startup must end the process: otherwise it keeps the bus name
        # with no window and the shortcut silently does nothing.
        try:
            self._start()
        except Exception:
            LOGGER.exception("Searchy failed to start")
            self._fail()

    def _fail(self) -> None:
        self.exit_code = 1
        self.quit()

    def _start(self) -> None:
        if Gdk.Display.get_default() is None:
            LOGGER.error("No Wayland display is available")
            self._fail()
            return
        action = Gio.SimpleAction.new("show-search", None)
        action.connect("activate", lambda _action, _parameter: self.show_search())
        self.add_action(action)
        for name, rebuild in (("reindex", False), ("rebuild-index", True)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._on_reindex, rebuild)
            self.add_action(action)
        self.database = SearchDatabase(self.config.database_path)
        path_filter = PathFilter.create(
            self.config.database_path.parent,
            self.config.exclude_patterns,
            self.config.index_hidden,
        )
        # Entries indexed under other rules would linger, so start a fresh index.
        rules = repr(
            (sorted(map(str, self.config.search_roots)), path_filter.signature(), INDEX_VERSION)
        )
        if self.database.index_rules() != rules:
            LOGGER.info("Index rules changed; rebuilding the index")
            self.database.reset()
            self.database.set_index_rules(rules)
        self.catalog = ApplicationCatalog()
        usage = UsageStore(
            self.config.database_path.parent / "usage.sqlite3"
            if self.config.remember_usage
            else None
        )
        self.window = SearchWindow(
            self,
            self.database,
            self.catalog,
            usage,
            self.config.result_limit,
            self.config.default_search_type,
            self.config.hide_on_focus_loss,
            self.config.web_search_url,
            self.config.show_preview,
            lambda query, limit, cancel_event: search_content(
                query,
                self.config.search_roots,
                path_filter.excluded_names,
                self.config.index_hidden,
                limit,
                cancel_event,
            ),
            BookmarkCatalog() if self.config.search_bookmarks else None,
        )
        self.indexer = FileIndexer(
            self.database,
            self.config.search_roots,
            path_filter,
            self.config.index_interval_seconds,
            lambda message: GLib.idle_add(self._set_index_status, message),
        )
        self.indexer.start()
        if self.config.index_removable:
            self.drive_monitor = DriveMonitor(self.indexer.add_root, self.indexer.remove_root)
        # Keep a reference: the monitor stops emitting once it is collected.
        self.app_monitor = Gio.AppInfoMonitor.get()
        self.app_monitor.connect("changed", lambda _monitor: self.catalog.refresh())
        LOGGER.info("Searchy service started")

    def do_shutdown(self) -> None:
        if self.indexer:
            self.indexer.stop()
        if self.window:
            self.window.shutdown()
        Adw.Application.do_shutdown(self)

    def show_search(self) -> None:
        if self.window is None:
            LOGGER.error("Cannot show search: window is not initialized")
            return
        # The shortcut toggles: pressing it while the window is open hides it.
        if self.window.get_visible():
            self.window.set_visible(False)
            LOGGER.info("Search window hidden")
        else:
            self.window.show_search()
            LOGGER.info("Search window shown")

    def _on_reindex(self, _action, _parameter, rebuild: bool) -> None:
        if self.indexer is None:
            LOGGER.error("Cannot reindex: the indexer is not running")
            return
        LOGGER.info("Reindex requested (rebuild=%s)", rebuild)
        self.indexer.request_reindex(rebuild)

    def _set_index_status(self, message: str) -> bool:
        if self.window:
            return self.window.set_index_status(message)
        return GLib.SOURCE_REMOVE


def main() -> int:
    def log_unhandled(error_type, error, traceback) -> None:
        LOGGER.critical("Unhandled exception", exc_info=(error_type, error, traceback))

    sys.excepthook = log_unhandled
    try:
        config = Config.load()
    except ValueError as error:
        LOGGER.error("Invalid configuration: %s", error)
        return 2
    if not os.environ.get("WAYLAND_DISPLAY"):
        # Exit non-zero so systemd retries once the session exports the display.
        LOGGER.error("WAYLAND_DISPLAY is not set; the graphical session is not ready")
        return 1
    application = SearchyApplication(config)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: application.quit())
    status = application.run(sys.argv)
    return status or application.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
