from __future__ import annotations

import logging
import mimetypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from .catalog import ApplicationCatalog
from .database import SearchDatabase
from .models import SearchResult

LOGGER = logging.getLogger(__name__)
SEARCH_TYPES = ("everything", "apps", "files", "folders")


class SearchWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        application: Adw.Application,
        database: SearchDatabase,
        catalog: ApplicationCatalog,
        result_limit: int,
        default_search_type: str,
    ):
        super().__init__(application=application, title="Searchy")
        self.database = database
        self.catalog = catalog
        self.result_limit = result_limit
        self.results: list[SearchResult] = []
        self.search_generation = 0
        self.search_timeout_id = 0
        self.search_cancel_event: threading.Event | None = None
        self.search_hint = ""
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="searchy-search")
        self.thumbnail_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="searchy-thumbnail"
        )
        self.thumbnail_futures = []
        self.creation_sort_available = False
        self.set_default_size(780, 620)
        self.connect("close-request", self._on_close_request)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        toolbar.set_content(content)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search = Gtk.SearchEntry(
            placeholder_text="Search applications, files, and folders", hexpand=True
        )
        self.search.connect("search-changed", self._on_search_changed)
        search_row.append(self.search)
        self.search_type = Gtk.DropDown.new_from_strings(
            ["Everything", "Apps", "Files", "Folders"]
        )
        self.search_type.set_tooltip_text("Choose what Searchy searches")
        self.search_type.set_selected(SEARCH_TYPES.index(default_search_type))
        self.search_type.connect("notify::selected", self._on_filter_changed)
        search_row.append(self.search_type)
        content.append(search_row)

        sort_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.sort_enabled = Gtk.CheckButton(label="Sort results")
        self.sort_enabled.connect("toggled", self._on_sort_toggled)
        sort_row.append(self.sort_enabled)
        self.sort_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.sort_controls.set_visible(False)
        self.sort_field = Gtk.DropDown.new_from_strings(["Name"])
        self.sort_field.connect("notify::selected", self._on_filter_changed)
        self.sort_controls.append(self.sort_field)
        self.sort_direction = Gtk.DropDown.new_from_strings(["Ascending", "Descending"])
        self.sort_direction.connect("notify::selected", self._on_filter_changed)
        self.sort_controls.append(self.sort_direction)
        sort_row.append(self.sort_controls)
        content.append(sort_row)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list_box.set_activate_on_single_click(False)
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect("row-activated", self._on_row_activated)
        scroller.set_child(self.list_box)
        content.append(scroller)

        self.status = Gtk.Label(label="Preparing index...", xalign=0)
        self.status.add_css_class("dim-label")
        content.append(self.status)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    def show_search(self) -> None:
        self._refresh_creation_sort()
        self.search.set_text("")
        self.present()
        self.search.grab_focus()
        self._schedule_search(0)

    def set_index_status(self, message: str) -> bool:
        self.status.set_text(message)
        self._refresh_creation_sort()
        if self.get_visible():
            self._schedule_search()
        return GLib.SOURCE_REMOVE

    def shutdown(self) -> None:
        if self.search_cancel_event:
            self.search_cancel_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.thumbnail_executor.shutdown(wait=False, cancel_futures=True)

    def _refresh_creation_sort(self) -> None:
        available = self.database.has_creation_dates()
        if available == self.creation_sort_available:
            return
        self.creation_sort_available = available
        selected = self.sort_field.get_selected()
        labels = ["Name", "Date Created"] if available else ["Name"]
        self.sort_field.set_model(Gtk.StringList.new(labels))
        self.sort_field.set_selected(min(selected, len(labels) - 1))

    def _begin_search(self) -> None:
        if self.search_cancel_event:
            self.search_cancel_event.set()
        self.search_cancel_event = threading.Event()
        cancel_event = self.search_cancel_event
        self.search_generation += 1
        generation = self.search_generation
        query = self.search.get_text()
        mode = SEARCH_TYPES[self.search_type.get_selected()]
        started_at = time.monotonic()
        app_results = (
            self.catalog.search(query, self.result_limit)
            if mode in {"everything", "apps"}
            else []
        )
        if mode == "apps":
            self.search_hint = ""
            self._apply_results(generation, app_results)
            return
        if len(query.strip()) < 3:
            self.search_hint = "Type at least 3 characters to search files and folders"
            self._apply_results(
                generation, app_results if mode == "everything" else []
            )
            return
        self.search_hint = ""
        kind = "file" if mode == "files" else "folder" if mode == "folders" else None
        future = self.executor.submit(
            self.database.search, query, self.result_limit, kind, cancel_event
        )

        def completed(task) -> None:
            try:
                file_results = task.result()
            except Exception:
                LOGGER.exception("Search query failed")
                file_results = []
            combined = file_results if mode != "everything" else app_results + file_results
            LOGGER.info(
                "Search completed: mode=%s query_length=%s results=%s duration_ms=%.1f",
                mode,
                len(query.strip()),
                len(combined),
                (time.monotonic() - started_at) * 1000,
            )
            GLib.idle_add(self._apply_results, generation, combined)

        future.add_done_callback(completed)

    def _apply_results(self, generation: int, results: list[SearchResult]) -> bool:
        if generation != self.search_generation:
            return GLib.SOURCE_REMOVE
        query = self.search.get_text().strip().casefold()
        if self.sort_enabled.get_active():
            results = self._sort_results(results)
        else:
            results.sort(key=lambda result: _relevance(result, query))
        self.results = results[: self.result_limit]
        for future in self.thumbnail_futures:
            future.cancel()
        self.thumbnail_futures.clear()
        while child := self.list_box.get_first_child():
            self.list_box.remove(child)
        for result in self.results:
            self.list_box.append(self._make_row(result))
        first = self.list_box.get_row_at_index(0)
        if first:
            self.list_box.select_row(first)
        count = len(self.results)
        if count == 0 and self.search_hint:
            self.status.set_text(self.search_hint)
        else:
            self.status.set_text(f"{count} result" if count == 1 else f"{count} results")
        return GLib.SOURCE_REMOVE

    def _schedule_search(self, delay_ms: int = 180) -> None:
        if self.search_timeout_id:
            GLib.source_remove(self.search_timeout_id)
        self.search_timeout_id = GLib.timeout_add(delay_ms, self._run_scheduled_search)

    def _run_scheduled_search(self) -> bool:
        self.search_timeout_id = 0
        self._begin_search()
        return GLib.SOURCE_REMOVE

    def _sort_results(self, results: list[SearchResult]) -> list[SearchResult]:
        descending = self.sort_direction.get_selected() == 1
        if self.creation_sort_available and self.sort_field.get_selected() == 1:
            dated = [result for result in results if result.created_at is not None]
            unknown = [result for result in results if result.created_at is None]
            dated.sort(key=lambda result: result.created_at or 0, reverse=descending)
            return dated + sorted(unknown, key=lambda result: result.name.casefold())
        return sorted(
            results, key=lambda result: result.name.casefold(), reverse=descending
        )

    def _make_row(self, result: SearchResult) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.result = result
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(9)
        box.set_margin_bottom(9)
        box.set_margin_start(12)
        box.set_margin_end(12)
        if _is_image_result(result):
            preview = Gtk.Picture()
            preview.set_alternative_text(f"Preview of {result.name}")
            preview.set_can_shrink(True)
            preview.set_content_fit(Gtk.ContentFit.CONTAIN)
            preview.set_size_request(96, 72)
            box.append(preview)
            future = self.thumbnail_executor.submit(_load_thumbnail, result.path)
            self.thumbnail_futures.append(future)
            generation = self.search_generation

            def thumbnail_ready(task) -> None:
                try:
                    pixbuf = task.result()
                except Exception:
                    LOGGER.debug("Cannot create thumbnail for %s", result.path)
                    return
                GLib.idle_add(self._set_thumbnail, preview, pixbuf, generation)

            future.add_done_callback(thumbnail_ready)
        else:
            image = (
                Gtk.Image.new_from_gicon(result.icon)
                if result.icon is not None
                else Gtk.Image.new_from_icon_name(_icon_name(result.kind))
            )
            image.set_pixel_size(32)
            image.set_size_request(96, 72)
            box.append(image)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        name = Gtk.Label(label=result.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        name.add_css_class("heading")
        labels.append(name)
        detail = result.detail
        if result.created_at is not None:
            created = datetime.fromtimestamp(result.created_at).strftime("%Y-%m-%d %H:%M")
            detail = f"{detail}  |  Created {created}"
        metadata = Gtk.Label(label=detail, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        metadata.add_css_class("dim-label")
        labels.append(metadata)
        box.append(labels)
        type_label = Gtk.Label(label=result.kind.title())
        type_label.add_css_class("dim-label")
        box.append(type_label)
        row.set_child(box)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_context_click, row)
        row.add_controller(click)
        return row

    def _set_thumbnail(self, picture, pixbuf, generation: int) -> bool:
        if generation == self.search_generation:
            picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
        return GLib.SOURCE_REMOVE

    def _on_context_click(self, gesture, presses, x, y, row) -> None:
        self.list_box.select_row(row)
        popover = Gtk.Popover()
        popover.set_parent(row)
        rectangle = Gdk.Rectangle()
        rectangle.x = int(x)
        rectangle.y = int(y)
        rectangle.width = 1
        rectangle.height = 1
        popover.set_pointing_to(rectangle)
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu.set_margin_top(6)
        menu.set_margin_bottom(6)
        menu.set_margin_start(6)
        menu.set_margin_end(6)
        open_button = Gtk.Button(label="Open")
        open_button.connect("clicked", lambda _button: self._open_result(row.result, popover))
        menu.append(open_button)
        source_button = Gtk.Button(label="Open Source Location")
        source_button.set_sensitive(row.result.source_path is not None)
        source_button.connect(
            "clicked", lambda _button: self._reveal_result(row.result, popover)
        )
        menu.append(source_button)
        if row.result.kind in {"file", "folder"} and row.result.path is not None:
            trash_button = Gtk.Button(label="Move to Trash")
            trash_button.add_css_class("destructive-action")
            trash_button.connect(
                "clicked", lambda _button: self._confirm_trash(row.result, popover)
            )
            menu.append(trash_button)
        popover.set_child(menu)
        popover.connect("closed", lambda widget: widget.unparent())
        popover.popup()

    def _activate_selected(self) -> None:
        row = self.list_box.get_selected_row()
        if row:
            self._open_result(row.result)

    def _open_result(self, result: SearchResult, popover: Gtk.Popover | None = None) -> None:
        if popover:
            popover.popdown()
        try:
            if result.kind == "app":
                result.payload.launch([], None)
            elif result.path:
                Gio.AppInfo.launch_default_for_uri(
                    Gio.File.new_for_path(str(result.path)).get_uri(), None
                )
            self.set_visible(False)
        except GLib.Error as error:
            LOGGER.warning("Cannot open %s: %s", result.name, error.message)
            self.status.set_text(f"Could not open {result.name}")

    def _confirm_trash(self, result: SearchResult, popover: Gtk.Popover) -> None:
        popover.popdown()
        if result.path is None:
            return
        description = (
            f"Move “{result.name}” and all of its contents to the Trash?"
            if result.kind == "folder"
            else f"Move “{result.name}” to the Trash?"
        )
        dialog = Adw.AlertDialog(
            heading="Move to Trash?",
            body=description,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("trash", "Move to Trash")
        dialog.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_trash_response, result)
        dialog.present(self)

    def _on_trash_response(self, dialog, response: str, result: SearchResult) -> None:
        if response != "trash" or result.path is None:
            return
        file = Gio.File.new_for_path(str(result.path))
        file.trash_async(
            GLib.PRIORITY_DEFAULT,
            None,
            self._on_trash_finished,
            (result, file),
        )

    def _on_trash_finished(self, source, task, state) -> None:
        result, file = state
        try:
            file.trash_finish(task)
        except GLib.Error as error:
            LOGGER.warning("Cannot trash %s: %s", result.path, error.message)
            self.status.set_text(f"Could not move {result.name} to Trash")
            return
        future = self.executor.submit(self.database.delete_path, result.path)
        future.add_done_callback(lambda _task: GLib.idle_add(self._schedule_search, 0))

    def _reveal_result(self, result: SearchResult, popover: Gtk.Popover | None = None) -> None:
        if popover:
            popover.popdown()
        path = result.source_path
        if path is None:
            return
        uri = Gio.File.new_for_path(str(path)).get_uri()
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.FileManager1",
                "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1",
                None,
            )
            proxy.call_sync(
                "ShowItems",
                GLib.Variant("(ass)", ([uri], "")),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except GLib.Error:
            parent = path.parent if path.parent != path else path
            Gio.AppInfo.launch_default_for_uri(
                Gio.File.new_for_path(str(parent)).get_uri(), None
            )

    def _on_search_changed(self, search: Gtk.SearchEntry) -> None:
        self._schedule_search()

    def _on_filter_changed(self, dropdown, parameter) -> None:
        self._schedule_search(0)

    def _on_sort_toggled(self, button: Gtk.CheckButton) -> None:
        self.sort_controls.set_visible(button.get_active())
        self._schedule_search(0)

    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._open_result(row.result)

    def _on_close_request(self, window) -> bool:
        self.set_visible(False)
        return True

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._activate_selected()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            selected = self.list_box.get_selected_row()
            index = selected.get_index() if selected else -1
            index += 1 if keyval == Gdk.KEY_Down else -1
            row = self.list_box.get_row_at_index(max(0, min(index, len(self.results) - 1)))
            if row:
                self.list_box.select_row(row)
            return True
        if keyval == Gdk.KEY_Menu or (
            keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK
        ):
            row = self.list_box.get_selected_row()
            if row:
                self._on_context_click(None, 1, 20, row.get_height() / 2, row)
                return True
        return False


def _relevance(result: SearchResult, query: str) -> tuple[int, int, str]:
    name = result.name.casefold()
    if name == query:
        tier = 0
    elif name.startswith(query):
        tier = 1
    elif query in name:
        tier = 2
    else:
        tier = 3
    return tier, len(name), name


def _icon_name(kind: str) -> str:
    if kind == "folder":
        return "folder-symbolic"
    if kind == "app":
        return "application-x-executable-symbolic"
    return "text-x-generic-symbolic"


def _is_image_result(result: SearchResult) -> bool:
    if result.kind != "file" or result.path is None:
        return False
    mime_type, _encoding = mimetypes.guess_type(result.path.name)
    return mime_type is not None and mime_type.startswith("image/")


def _load_thumbnail(path) -> GdkPixbuf.Pixbuf:
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 96, 72, True)
