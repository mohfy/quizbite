# window.py
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

"""Main application window.

Shows the quiz library.
Handles import, export, share, and delete flows.
"""

from __future__ import annotations

from functools import partial
from gettext import gettext as _

from gi.repository import Adw, GLib, Gtk

from ..data.db import (
    delete_quiz,
    export_quiz,
    get_quiz,
    get_quizzes_with_question_counts,
    save_quiz,
)
from ..data.quiz_file import load_quiz_file, save_quiz_file
from .utils.file_dialogs import (
    build_file_dialog,
    build_pdf_file_filter,
    build_quiz_file_filter,
    dialog_error_was_dismissed,
    path_from_file,
)
from .quiz_library import build_quiz_row
from .utils.pdfgenerator import generate_quiz_pdf
from .play_quiz.quiz_player import QuizPlayer


@Gtk.Template(resource_path="/dev/mohfy/quizbite/ui/window.ui")
class QuizbiteWindow(Adw.ApplicationWindow):
    """The top-level window for the app."""

    __gtype_name__ = "QuizbiteWindow"

    navigation_view = Gtk.Template.Child()
    quiz_status = Gtk.Template.Child()
    empty_page = Gtk.Template.Child()
    quiz_list_clamp = Gtk.Template.Child()
    quiz_list = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.quiz_rows: list[Adw.ActionRow] = []

        self.quiz_player = QuizPlayer(self.navigation_view)

        self.load_quizzes()

    def _finish_file_dialog(self, result, finish_method, error_title: str):
        """Finalize a file dialog and show errors."""
        try:
            return finish_method(result)
        except GLib.Error as error:
            if dialog_error_was_dismissed(error):
                return None

            self._show_alert(error_title, error.message)
            return None

    def _get_export_payload(self, quiz_id: int, error_message: str) -> dict:
        """Load a quiz and convert it to the portable export format."""
        payload = export_quiz(quiz_id)
        if payload is None:
            raise ValueError(error_message)

        return payload

    def load_quizzes(self):
        """Reload the quiz list UI from the database."""
        quizzes = get_quizzes_with_question_counts()

        for row in self.quiz_rows:
            self.quiz_list.remove(row)
        self.quiz_rows.clear()

        if not quizzes:
            self.quiz_status.set_visible_child(self.empty_page)
            return

        for quiz in quizzes:
            row = build_quiz_row(
                quiz,
                self.on_quiz_activated,
                self.on_share_quiz_clicked,
                self.on_export_quiz_clicked,
                self.on_delete_quiz_clicked,
            )
            self.quiz_list.add(row)
            self.quiz_rows.append(row)

        self.quiz_status.set_visible_child(self.quiz_list_clamp)

    def on_quiz_activated(self, _row, quiz):
        """Open the selected quiz in the player."""
        quiz_data = get_quiz(quiz["id"])
        if quiz_data is None or not quiz_data["questions"]:
            return

        self.quiz_player.open_quiz(quiz_data)

    def open_import_dialog(self):
        """Open the import file dialog."""
        dialog = build_file_dialog(
            title=_("Import Quiz"),
            accept_label=_("Import"),
            filters=[build_quiz_file_filter()],
        )
        dialog.open(self, None, self.on_import_dialog_finished)

    def on_import_dialog_finished(self, dialog, result, _user_data=None):
        """Handle the import file selection result."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.open_finish,
            _("Import Failed"),
        )
        if selected_file is None:
            return

        try:
            quiz_data = load_quiz_file(path_from_file(selected_file))
            save_quiz(quiz_data)
            self.load_quizzes()
        except Exception as exc:
            self._show_alert(_("Import Failed"), str(exc))

    def on_share_quiz_clicked(self, _button, quiz, popover):
        """Open a save dialog to export a quiz file."""
        popover.popdown()

        dialog = build_file_dialog(
            title=_("Share Quiz"),
            accept_label=_("Save"),
            filters=[build_quiz_file_filter()],
            initial_name=f"{quiz['title']}.quiz",
        )
        dialog.save(
            self,
            None,
            partial(self.on_share_dialog_finished, quiz_id=quiz["id"]),
        )

    def on_share_dialog_finished(
        self, dialog, result, _user_data=None, *, quiz_id: int
    ):
        """Handle the share save result."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.save_finish,
            _("Share Failed"),
        )
        if selected_file is None:
            return

        try:
            payload = self._get_export_payload(
                quiz_id,
                _("Quiz could not be loaded for export."),
            )
            save_quiz_file(path_from_file(selected_file), payload)
        except Exception as exc:
            self._show_alert(_("Share Failed"), str(exc))

    def on_export_quiz_clicked(self, _button, quiz, popover):
        """Prompt for PDF export options."""
        popover.popdown()

        dialog = Adw.AlertDialog(
            heading=_("Export PDF"),
            body=_("Choose whether the exported PDF should include the answer key."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("without-answers", _("Without Answer Key"))
        dialog.add_response("with-answers", _("With Answer Key"))
        dialog.set_default_response("without-answers")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_export_quiz_response, quiz)
        dialog.present(self)

    def on_export_quiz_response(self, _dialog, response, quiz):
        """Handle the PDF export option response."""
        if response == "cancel":
            return

        include_answer_key = response == "with-answers"
        dialog = build_file_dialog(
            title=_("Export Quiz PDF"),
            accept_label=_("Export"),
            filters=[build_pdf_file_filter()],
            initial_name=f"{quiz['title']}.pdf",
        )
        dialog.save(
            self,
            None,
            partial(
                self.on_export_dialog_finished,
                quiz_id=quiz["id"],
                include_answer_key=include_answer_key,
            ),
        )

    def on_export_dialog_finished(
        self,
        dialog,
        result,
        _user_data=None,
        *,
        quiz_id: int,
        include_answer_key: bool,
    ):
        """Handle the PDF save result and run export."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.save_finish,
            _("Export Failed"),
        )
        if selected_file is None:
            return

        try:
            payload = self._get_export_payload(
                quiz_id,
                _("Quiz could not be loaded for PDF export."),
            )
            generate_quiz_pdf(
                path_from_file(selected_file),
                payload,
                include_answer_key=include_answer_key,
            )
        except Exception as exc:
            self._show_alert(_("Export Failed"), str(exc))

    def on_delete_quiz_clicked(self, _button, quiz, popover):
        """Confirm quiz deletion."""
        popover.popdown()

        dialog = Adw.AlertDialog(
            heading=_("Delete Quiz?"),
            body=_('"{title}" will be removed from your library.').format(
                title=quiz["title"]
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_delete_quiz_response, quiz["id"])
        dialog.present(self)

    def on_delete_quiz_response(self, _dialog, response, quiz_id):
        """Delete the quiz if the user confirmed."""
        if response != "delete":
            return

        delete_quiz(quiz_id)
        self.load_quizzes()

    def _show_alert(self, heading: str, body: str):
        """Show an alert dialog."""
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present(self)
