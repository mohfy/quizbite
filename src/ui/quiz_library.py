"""Widgets for the quiz library list.

This module builds rows and menus for the main window list.
"""

from __future__ import annotations

from collections.abc import Callable
from gettext import gettext as _, ngettext

from gi.repository import Adw, Gtk


def build_quiz_row(
    quiz: dict,
    on_activate: Callable,
    on_share: Callable,
    on_export: Callable,
    on_delete: Callable,
) -> Adw.ActionRow:
    """Build a quiz row for the library list."""
    row = Adw.ActionRow(
        title=quiz["title"],
        subtitle=format_question_count(quiz["question_count"]),
    )
    row.set_activatable(True)
    row.add_suffix(build_quiz_menu_button(quiz, on_share, on_export, on_delete))
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    row.connect("activated", on_activate, quiz)
    return row


def build_quiz_menu_button(
    quiz: dict,
    on_share: Callable,
    on_export: Callable,
    on_delete: Callable,
) -> Gtk.MenuButton:
    """Build the "more" menu button for a quiz row."""
    menu_button = Gtk.MenuButton(icon_name="view-more-symbolic")
    menu_button.set_valign(Gtk.Align.CENTER)
    menu_button.add_css_class("flat")
    menu_button.set_tooltip_text(_("Quiz actions"))

    popover = Gtk.Popover()
    popover.add_css_class("menu")

    menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    menu_box.append(build_menu_item_button(_("Share Quiz"), on_share, quiz, popover))
    menu_box.append(build_menu_item_button(_("Export PDF"), on_export, quiz, popover))
    menu_box.append(
        build_menu_item_button(
            _("Delete Quiz"),
            on_delete,
            quiz,
            popover,
            destructive=True,
        )
    )

    popover.set_child(menu_box)
    menu_button.set_popover(popover)
    return menu_button


def build_menu_item_button(
    label: str,
    callback: Callable,
    *args,
    destructive: bool = False,
) -> Gtk.Button:
    """Build a menu-like button for a popover list."""
    button = Gtk.Button(label=label)
    button.set_halign(Gtk.Align.FILL)
    button.set_hexpand(True)
    button.set_has_frame(False)
    button.add_css_class("menuitem")

    if destructive:
        button.add_css_class("destructive-action")

    button.connect("clicked", callback, *args)
    return button


def format_question_count(question_count: int) -> str:
    """Format a question count label."""
    return ngettext(
        "{count} question",
        "{count} questions",
        question_count,
    ).format(count=question_count)
