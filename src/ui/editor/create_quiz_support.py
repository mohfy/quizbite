"""Quiz editor support code.

Contains small helpers used by the quiz editor dialog.
Keeps widget wiring and serialization in one place.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from gettext import gettext as _
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

UNSELECTED_OPTION = ""


@dataclass(slots=True)
class QuestionImageSelection:
    """A selected image plus UI texture for previews."""
    filename: str
    media_type: str
    data: str
    texture: Gdk.Texture


@dataclass(slots=True)
class QuestionEditorBlock:
    """Widget group for one question editor section."""
    group: Adw.PreferencesGroup
    question_title: Adw.EntryRow
    image_row: Adw.ActionRow
    image_preview: Gtk.Picture
    option_rows: list[Adw.EntryRow]
    correct_action: Gio.SimpleAction
    remove_button: Gtk.Button
    remove_image_button: Gtk.Button
    image: QuestionImageSelection | None = None


def create_entry_row(title: str, on_changed: Callable) -> Adw.EntryRow:
    """Create an entry row and bind its change handler."""
    row = Adw.EntryRow(title=title)
    row.connect("changed", on_changed)
    return row


def create_correct_action(on_change_state: Callable) -> Gio.SimpleAction:
    """Create a stateful action for the correct option selection."""
    action = Gio.SimpleAction.new_stateful(
        "correct-option",
        GLib.VariantType.new("s"),
        GLib.Variant.new_string(UNSELECTED_OPTION),
    )
    action.connect("change-state", on_change_state)
    return action


def create_action_group(action: Gio.SimpleAction) -> Gio.SimpleActionGroup:
    """Wrap an action in an action group."""
    action_group = Gio.SimpleActionGroup()
    action_group.add_action(action)
    return action_group


def build_option_row(
    option_index: int,
    first_check: Gtk.CheckButton | None,
    on_changed: Callable,
) -> tuple[Adw.EntryRow, Gtk.CheckButton]:
    """Build an option entry row and its correct check button."""
    row = create_entry_row(
        _("Option {number}").format(number=option_index + 1),
        on_changed,
    )

    check = Gtk.CheckButton()
    check.set_valign(Gtk.Align.CENTER)
    check.set_tooltip_text(_("Mark as correct answer"))
    check.set_action_name("question.correct-option")
    check.set_action_target_value(GLib.Variant.new_string(str(option_index)))

    if first_check is not None:
        check.set_group(first_check)

    row.add_prefix(check)
    return row, check


def create_image_row(
    on_choose_clicked: Callable,
    on_remove_clicked: Callable,
    group: Adw.PreferencesGroup,
) -> tuple[Adw.ActionRow, Gtk.Picture, Gtk.Button]:
    """Build the optional image row UI."""
    row = Adw.ActionRow(
        title=_("Question Image (Optional)"),
        subtitle=_("No image selected"),
    )
    row.set_activatable(False)

    picture = Gtk.Picture()
    picture.set_size_request(80, 60)
    picture.set_content_fit(Gtk.ContentFit.COVER)
    picture.set_can_shrink(True)
    picture.set_visible(False)
    row.add_prefix(picture)

    choose_button = Gtk.Button(label=_("Choose Image"))
    choose_button.add_css_class("pill")
    choose_button.connect("clicked", on_choose_clicked, group)
    row.add_suffix(choose_button)

    remove_button = Gtk.Button(icon_name="user-trash-symbolic")
    remove_button.set_tooltip_text(_("Remove image"))
    remove_button.add_css_class("flat")
    remove_button.add_css_class("destructive-action")
    remove_button.set_sensitive(False)
    remove_button.connect("clicked", on_remove_clicked, group)
    row.add_suffix(remove_button)

    return row, picture, remove_button


def find_question_block(
    blocks: list[QuestionEditorBlock],
    group: Adw.PreferencesGroup,
) -> QuestionEditorBlock | None:
    """Find the block that owns `group`."""
    return next((block for block in blocks if block.group is group), None)


def load_question_image_selection(path: str | Path) -> QuestionImageSelection:
    """Load an image file and build a selection payload."""
    image_path = Path(path)
    image_bytes = image_path.read_bytes()
    content_type, _uncertain = Gio.content_type_guess(image_path.name, image_bytes)

    if not content_type or not content_type.startswith("image/"):
        raise ValueError(_("Selected file is not a supported image."))

    try:
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(image_bytes))
    except GLib.Error as error:
        raise ValueError(_("Selected file could not be loaded as an image.")) from error

    return QuestionImageSelection(
        filename=image_path.name,
        media_type=content_type,
        data=base64.b64encode(image_bytes).decode("ascii"),
        texture=texture,
    )


def set_question_block_image(
    block: QuestionEditorBlock,
    image: QuestionImageSelection | None,
) -> None:
    """Update a block UI when the image selection changes."""
    block.image = image

    if image is None:
        block.image_row.set_subtitle(_("No image selected"))
        block.image_preview.set_paintable(None)
        block.image_preview.set_visible(False)
        block.remove_image_button.set_sensitive(False)
        return

    block.image_row.set_subtitle(image.filename)
    block.image_preview.set_paintable(image.texture)
    block.image_preview.set_visible(True)
    block.remove_image_button.set_sensitive(True)


def get_selected_option_index(block: QuestionEditorBlock) -> int | None:
    """Return the selected option index in the editor UI."""
    state = block.correct_action.get_state()
    if state is None:
        return None

    selected_option = state.get_string()
    if selected_option == UNSELECTED_OPTION:
        return None

    return int(selected_option)


def question_block_is_valid(block: QuestionEditorBlock) -> bool:
    """Return True when the editor block is ready to save."""
    if not block.question_title.get_text().strip():
        return False

    filled_options = [
        row.get_text().strip() for row in block.option_rows if row.get_text().strip()
    ]
    if len(filled_options) < 2:
        return False

    selected_option_index = get_selected_option_index(block)
    if selected_option_index is None:
        return False

    selected_option_text = block.option_rows[selected_option_index].get_text().strip()
    return bool(selected_option_text)


def serialize_question_block(block: QuestionEditorBlock) -> dict:
    """Convert a block UI into a `.quiz` question payload."""
    selected_option_index = get_selected_option_index(block)
    options = []
    correct_index = None

    for option_index, row in enumerate(block.option_rows):
        option_text = row.get_text().strip()
        if not option_text:
            continue

        if option_index == selected_option_index:
            correct_index = len(options)

        options.append(option_text)

    question_payload = {
        "question": block.question_title.get_text().strip(),
        "options": options,
        "correct_index": correct_index,
    }
    if block.image is not None:
        question_payload["image"] = {
            "filename": block.image.filename,
            "media_type": block.image.media_type,
            "data": block.image.data,
        }

    return question_payload
