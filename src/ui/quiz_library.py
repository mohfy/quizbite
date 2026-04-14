"""Widgets for the study library list."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from gettext import gettext as _, ngettext

from gi.repository import Adw, Gtk


def build_library_row(
    item: dict,
    on_activate: Callable,
    menu_actions: Sequence[dict],
) -> Adw.ActionRow:
    """Build one row for the mixed library list."""
    row = Adw.ActionRow(
        title=item["title"],
        subtitle=format_library_item_subtitle(item),
    )
    row.set_activatable(True)
    row.add_suffix(build_item_menu_button(menu_actions))
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    row.connect("activated", on_activate, item)
    return row


def build_item_menu_button(
    menu_actions: Sequence[dict],
) -> Gtk.MenuButton:
    """Build the "more" menu button for a library row."""
    menu_button = Gtk.MenuButton(icon_name="view-more-symbolic")
    menu_button.set_valign(Gtk.Align.CENTER)
    menu_button.add_css_class("flat")
    menu_button.set_tooltip_text(_("Item actions"))

    popover = Gtk.Popover()
    popover.add_css_class("menu")

    menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    for action in menu_actions:
        menu_box.append(
            build_menu_item_button(
                action["label"],
                action["callback"],
                action["item"],
                popover,
                destructive=action.get("destructive", False),
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


def format_library_item_subtitle(item: dict) -> str:
    """Format the mixed-library count/type subtitle."""
    entry_count = item["entry_count"]
    if item["item_type"] == "flashcard":
        count_label = ngettext(
            "{count} flashcard",
            "{count} flashcards",
            entry_count,
        ).format(count=entry_count)
        type_label = _("Flashcard")
    else:
        count_label = ngettext(
            "{count} question",
            "{count} questions",
            entry_count,
        ).format(count=entry_count)
        type_label = _("Quiz")

    return _("{count} • {type}").format(count=count_label, type=type_label)
