from __future__ import annotations

import logging
import os
import signal
import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gio, GLib

from .catalog import ApplicationCatalog
from .config import Config
from .database import SearchDatabase
from .indexer import FileIndexer
from .ui import SearchWindow

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

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self.hold()
        action = Gio.SimpleAction.new("show-search", None)
        action.connect("activate", lambda _action, _parameter: self.show_search())
        self.add_action(action)
        self.database = SearchDatabase(self.config.database_path)
        self.catalog = ApplicationCatalog()
        self.window = SearchWindow(
            self,
            self.database,
            self.catalog,
            self.config.result_limit,
            self.config.default_search_type,
        )
        self.indexer = FileIndexer(
            self.database,
            self.config.search_roots,
            self.config.database_path.parent,
            self.config.index_interval_seconds,
            lambda message: GLib.idle_add(self._set_index_status, message),
        )
        self.indexer.start()
        LOGGER.info("Searchy service started")

    def do_shutdown(self) -> None:
        if self.indexer:
            self.indexer.stop()
        if self.window:
            self.window.shutdown()
        Adw.Application.do_shutdown(self)

    def show_search(self) -> None:
        if self.window:
            self.window.show_search()

    def _set_index_status(self, message: str) -> bool:
        if self.window:
            return self.window.set_index_status(message)
        return GLib.SOURCE_REMOVE


def main() -> int:
    try:
        config = Config.load()
    except ValueError as error:
        LOGGER.error("Invalid configuration: %s", error)
        return 2
    application = SearchyApplication(config)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: application.quit())
    return application.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
