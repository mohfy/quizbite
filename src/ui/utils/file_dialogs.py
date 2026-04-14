"""GTK file dialog helpers.

Wraps `Gtk.FileDialog` creation and common filters.
"""

from __future__ import annotations

from pathlib import Path
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

QUIZ_FILE_PATTERNS = ("*.quiz", "*.json")
APKG_FILE_PATTERNS = ("*.apkg",)


def build_file_dialog(
    *,
    title: str,
    accept_label: str,
    filters: list[Gtk.FileFilter] | None = None,
    initial_name: str | None = None,
) -> Gtk.FileDialog:
    """Create a configured `Gtk.FileDialog`."""
    dialog = Gtk.FileDialog()
    dialog.set_title(title)
    dialog.set_accept_label(accept_label)
    dialog.set_modal(True)

    if initial_name is not None:
        dialog.set_initial_name(initial_name)

    if filters:
        filter_store = Gio.ListStore.new(Gtk.FileFilter)
        for file_filter in filters:
            filter_store.append(file_filter)

        dialog.set_filters(filter_store)
        dialog.set_default_filter(filters[0])

    return dialog


def build_quiz_file_filter() -> Gtk.FileFilter:
    """Create a quiz file filter."""
    quiz_filter = Gtk.FileFilter()
    quiz_filter.set_name(_("Quiz files"))

    for pattern in QUIZ_FILE_PATTERNS:
        quiz_filter.add_pattern(pattern)

    return quiz_filter


def build_apkg_file_filter() -> Gtk.FileFilter:
    """Create an APKG file filter."""
    apkg_filter = Gtk.FileFilter()
    apkg_filter.set_name(_("Anki deck files"))

    for pattern in APKG_FILE_PATTERNS:
        apkg_filter.add_pattern(pattern)

    return apkg_filter


def build_pdf_file_filter() -> Gtk.FileFilter:
    """Create a PDF file filter."""
    pdf_filter = Gtk.FileFilter()
    pdf_filter.set_name(_("PDF files"))
    pdf_filter.add_pattern("*.pdf")
    return pdf_filter


def build_image_file_filter() -> Gtk.FileFilter:
    """Create an image file filter."""
    image_filter = Gtk.FileFilter()
    image_filter.set_name(_("Images"))
    image_filter.add_pixbuf_formats()
    return image_filter


def dialog_error_was_dismissed(error: GLib.Error) -> bool:
    """Return True when the user dismissed the dialog."""
    return error.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED)


def path_from_file(file: Gio.File) -> Path:
    """Convert a `Gio.File` to a local `Path`.

    Raises ValueError when there is no local path.
    """
    file_path = file.get_path()
    if file_path is None:
        raise ValueError(_("The selected file is not available as a local path."))

    return Path(file_path)
