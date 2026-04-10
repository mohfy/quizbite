# create_quiz.py
#
# Copyright 2026 mohfy
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Quiz editor dialog.

Allows creating a quiz and saving it to the local DB.
"""

from __future__ import annotations

from functools import partial
from gettext import gettext as _

from gi.repository import Adw, GLib, Gtk

from ...data.db import save_quiz
from ..utils.file_dialogs import (
    build_file_dialog,
    build_image_file_filter,
    dialog_error_was_dismissed,
    path_from_file,
)
from .create_quiz_support import (
    QuestionEditorBlock,
    build_option_row,
    create_image_row,
    create_action_group,
    create_correct_action,
    create_entry_row,
    find_question_block,
    load_question_image_selection,
    question_block_is_valid,
    serialize_question_block,
    set_question_block_image,
)


@Gtk.Template(resource_path="/dev/mohfy/quizbite/ui/editor/create_quiz.ui")
class QuizEditorDialog(Adw.Dialog):
    """Dialog to create a quiz and persist it."""

    __gtype_name__ = "QuizEditorDialog"

    create_button = Gtk.Template.Child()
    quiz_editor = Gtk.Template.Child()
    quiz_title = Gtk.Template.Child()
    questions_group = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.create_button.set_sensitive(False)
        self.question_blocks: list[QuestionEditorBlock] = []

        self.on_add_question_clicked(None)
        self._update_create_button()

    def _dialog_parent(self):
        """Return the parent window when available."""
        parent = self.get_root()
        return parent if isinstance(parent, Gtk.Window) else None

    def _finish_file_dialog(self, result, finish_method, error_title: str):
        """Finalize a file dialog and handle GLib dialog errors."""
        try:
            return finish_method(result)
        except GLib.Error as error:
            if dialog_error_was_dismissed(error):
                return None

            self._show_alert(error_title, error.message)
            return None

    def _show_alert(self, heading: str, body: str):
        """Show an alert dialog."""
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present(self._dialog_parent() or self)

    @Gtk.Template.Callback()
    def on_add_question_clicked(self, _button):
        """Add a new question editor block."""
        question_index = len(self.question_blocks) + 1
        group = Adw.PreferencesGroup(
            title=_("Question {number}").format(number=question_index)
        )

        question_title = create_entry_row(_("Question"), self.on_form_changed)
        group.add(question_title)

        image_row, image_preview, remove_image_button = create_image_row(
            self.on_choose_question_image_clicked,
            self.on_remove_question_image_clicked,
            group,
        )
        group.add(image_row)

        correct_action = create_correct_action(self.on_correct_option_changed)
        group.insert_action_group("question", create_action_group(correct_action))

        option_rows: list[Adw.EntryRow] = []
        first_check = None

        for option_index in range(4):
            option_row, option_check = build_option_row(
                option_index,
                first_check,
                self.on_form_changed,
            )
            if first_check is None:
                first_check = option_check

            group.add(option_row)
            option_rows.append(option_row)

        remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        remove_button.set_tooltip_text(_("Remove Question"))
        remove_button.add_css_class("flat")
        remove_button.add_css_class("destructive-action")
        remove_button.connect("clicked", self.on_remove_question_clicked, group)
        group.set_header_suffix(remove_button)

        self.quiz_editor.add(group)
        self.question_blocks.append(
            QuestionEditorBlock(
                group=group,
                question_title=question_title,
                image_row=image_row,
                image_preview=image_preview,
                option_rows=option_rows,
                correct_action=correct_action,
                remove_button=remove_button,
                remove_image_button=remove_image_button,
            )
        )

        self._update_question_titles()
        self._update_create_button()

    def on_remove_question_clicked(self, _button, group):
        """Remove a question block, if more than one exists."""
        if len(self.question_blocks) == 1:
            return

        block_to_remove = find_question_block(self.question_blocks, group)
        if block_to_remove is None:
            return

        self.quiz_editor.remove(group)
        self.question_blocks.remove(block_to_remove)

        self._update_question_titles()
        self._update_create_button()

    def _update_question_titles(self):
        """Renumber question groups and toggle remove buttons."""
        can_remove_question = len(self.question_blocks) > 1

        for question_number, block in enumerate(self.question_blocks, start=1):
            block.group.set_title(_("Question {number}").format(number=question_number))
            block.remove_button.set_sensitive(can_remove_question)

    def on_correct_option_changed(self, action, value):
        """Track the correct option selection."""
        action.set_state(value)
        self._update_create_button()

    def on_choose_question_image_clicked(self, _button, group):
        """Open a file dialog to select an image for a question."""
        dialog = build_file_dialog(
            title=_("Select Question Image"),
            accept_label=_("Select"),
            filters=[build_image_file_filter()],
        )
        dialog.open(
            self._dialog_parent(),
            None,
            partial(self.on_question_image_dialog_finished, group=group),
        )

    def on_question_image_dialog_finished(
        self,
        dialog,
        result,
        _user_data=None,
        *,
        group,
    ):
        """Handle the image file selection result."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.open_finish,
            _("Image Selection Failed"),
        )
        if selected_file is None:
            return

        block = find_question_block(self.question_blocks, group)
        if block is None:
            return

        try:
            image = load_question_image_selection(path_from_file(selected_file))
        except Exception as exc:
            self._show_alert(_("Image Selection Failed"), str(exc))
            return

        set_question_block_image(block, image)
        self._update_create_button()

    def on_remove_question_image_clicked(self, _button, group):
        """Clear the image selection for a question."""
        block = find_question_block(self.question_blocks, group)
        if block is None or block.image is None:
            return

        set_question_block_image(block, None)
        self._update_create_button()

    @Gtk.Template.Callback()
    def on_form_changed(self, _widget=None, *_args):
        """Revalidate the form on any input change."""
        self._update_create_button()

    def _quiz_is_valid(self):
        """Return True when the editor content is valid."""
        if not self.quiz_title.get_text().strip():
            return False

        if not self.question_blocks:
            return False

        return all(question_block_is_valid(block) for block in self.question_blocks)

    def _update_create_button(self):
        """Enable or disable the Create button."""
        self.create_button.set_sensitive(self._quiz_is_valid())

    @Gtk.Template.Callback()
    def on_create_quiz(self, *_args):
        """Persist the quiz and close the dialog."""
        quiz_data = {
            "title": self.quiz_title.get_text().strip(),
            "questions": [serialize_question_block(block) for block in self.question_blocks],
        }

        save_quiz(quiz_data)

        window = self.get_root()
        if window and hasattr(window, "load_quizzes"):
            window.load_quizzes()

        self.close()

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, *_args):
        self.close()
