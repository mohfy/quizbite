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

Shows the mixed quiz/flashcard library.
Handles import, export, play, and delete flows.
"""

from __future__ import annotations

from functools import partial
from gettext import gettext as _

from gi.repository import Adw, GLib, Gtk

from ..data.db import (
    ITEM_TYPE_FLASHCARD,
    delete_flashcard_deck,
    delete_quiz,
    export_flashcard_deck,
    export_quiz,
    get_flashcard_deck,
    get_library_items,
    get_quiz,
    save_flashcard_deck,
    save_quiz,
)
from ..data.flashcard_apkg import load_apkg_file, save_apkg_file
from ..data.quiz_file import load_quiz_file, save_quiz_file
from .play_flashcard import (
    FlashcardMatchPlayer,
    build_flashcard_mode_page,
    build_flashcard_quiz,
)
from .play_quiz.quiz_player import QuizPlayer
from .quiz_library import build_library_row
from .utils.file_dialogs import (
    build_apkg_file_filter,
    build_file_dialog,
    build_pdf_file_filter,
    build_quiz_file_filter,
    dialog_error_was_dismissed,
    path_from_file,
)
from .utils.pdfgenerator import generate_flashcard_pdf, generate_quiz_pdf


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
        self.library_rows: list[Adw.ActionRow] = []
        self.flashcard_mode_page: Adw.NavigationPage | None = None

        self.quiz_player = QuizPlayer(self.navigation_view)
        self.flashcard_match_player = FlashcardMatchPlayer(self.navigation_view)

        self.load_library()

    def _finish_file_dialog(self, result, finish_method, error_title: str):
        """Finalize a file dialog and show errors."""
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
        dialog.present(self)

    def _get_quiz_export_payload(self, quiz_id: int, error_message: str) -> dict:
        """Load a quiz and convert it to the portable export format."""
        payload = export_quiz(quiz_id)
        if payload is None:
            raise ValueError(error_message)

        return payload

    def _get_flashcard_export_payload(self, deck_id: int, error_message: str) -> dict:
        """Load a flashcard deck and convert it to an export payload."""
        payload = export_flashcard_deck(deck_id)
        if payload is None:
            raise ValueError(error_message)

        return payload

    def load_library(self):
        """Reload the mixed study library from the database."""
        items = get_library_items()

        for row in self.library_rows:
            self.quiz_list.remove(row)
        self.library_rows.clear()

        if not items:
            self.quiz_status.set_visible_child(self.empty_page)
            return

        for item in items:
            row = build_library_row(
                item,
                self.on_library_item_activated,
                self._build_menu_actions(item),
            )
            self.quiz_list.add(row)
            self.library_rows.append(row)

        self.quiz_status.set_visible_child(self.quiz_list_clamp)

    def _build_menu_actions(self, item: dict) -> list[dict]:
        """Return the per-item menu actions for a library row."""
        if item["item_type"] == ITEM_TYPE_FLASHCARD:
            return [
                {
                    "label": _("Export APKG"),
                    "callback": self.on_export_flashcard_package_clicked,
                    "item": item,
                },
                {
                    "label": _("Export PDF"),
                    "callback": self.on_export_flashcard_pdf_clicked,
                    "item": item,
                },
                {
                    "label": _("Delete Flashcards"),
                    "callback": self.on_delete_flashcard_clicked,
                    "item": item,
                    "destructive": True,
                },
            ]

        return [
            {
                "label": _("Share Quiz"),
                "callback": self.on_share_quiz_clicked,
                "item": item,
            },
            {
                "label": _("Export PDF"),
                "callback": self.on_export_quiz_clicked,
                "item": item,
            },
            {
                "label": _("Delete Quiz"),
                "callback": self.on_delete_quiz_clicked,
                "item": item,
                "destructive": True,
            },
        ]

    def on_library_item_activated(self, _row, item):
        """Open the selected library item."""
        if item["item_type"] == ITEM_TYPE_FLASHCARD:
            deck_data = get_flashcard_deck(item["id"])
            if deck_data is None or not deck_data["cards"]:
                return

            self._open_flashcard_mode_page(deck_data)
            return

        quiz_data = get_quiz(item["id"])
        if quiz_data is None or not quiz_data["questions"]:
            return

        self.quiz_player.open_quiz(quiz_data)

    def _open_flashcard_mode_page(self, deck_data: dict) -> None:
        """Push the flashcard start page."""
        self.flashcard_mode_page = build_flashcard_mode_page(
            deck_data=deck_data,
            on_start_quiz=partial(self._start_flashcard_quiz, deck_data),
            on_start_match=partial(self._start_flashcard_match, deck_data),
        )
        self.navigation_view.push(self.flashcard_mode_page)

    def _start_flashcard_quiz(self, deck_data: dict, prompt_side: str) -> None:
        """Launch flashcard quiz mode using the existing quiz player."""
        try:
            quiz_payload = build_flashcard_quiz(deck_data, prompt_side)
        except Exception as exc:
            self._show_alert(_("Quiz Mode Unavailable"), str(exc))
            return

        self.quiz_player.open_quiz(quiz_payload)

    def _start_flashcard_match(self, deck_data: dict, prompt_side: str) -> None:
        """Launch flashcard match mode."""
        self.flashcard_match_player.open_deck(deck_data, prompt_side)

    def open_import_dialog(self):
        """Open the import file dialog."""
        dialog = build_file_dialog(
            title=_("Import Study Set"),
            accept_label=_("Import"),
            filters=[build_quiz_file_filter(), build_apkg_file_filter()],
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

        selected_path = path_from_file(selected_file)
        try:
            if selected_path.suffix.casefold() == ".apkg":
                import_result = load_apkg_file(selected_path)
                for deck in import_result["decks"]:
                    save_flashcard_deck(deck)
                self.load_library()
                self._maybe_show_apkg_import_summary(import_result)
                return

            quiz_data = load_quiz_file(selected_path)
            save_quiz(quiz_data)
            self.load_library()
        except Exception as exc:
            self._show_alert(_("Import Failed"), str(exc))

    def _maybe_show_apkg_import_summary(self, import_result: dict) -> None:
        """Show a summary when APKG import had multiple decks or skips."""
        deck_count = len(import_result["decks"])
        skipped_count = int(import_result.get("skipped_card_count", 0))
        if deck_count == 1 and skipped_count == 0:
            return

        body = _("Imported {deck_count} flashcard deck(s).").format(
            deck_count=deck_count
        )
        if skipped_count:
            body = _(
                "Imported {deck_count} flashcard deck(s) and skipped {skipped_count} unsupported card(s)."
            ).format(
                deck_count=deck_count,
                skipped_count=skipped_count,
            )

        self._show_alert(_("Import Complete"), body)

    def on_share_quiz_clicked(self, _button, item, popover):
        """Open a save dialog to export a quiz file."""
        popover.popdown()

        dialog = build_file_dialog(
            title=_("Share Quiz"),
            accept_label=_("Save"),
            filters=[build_quiz_file_filter()],
            initial_name=f"{item['title']}.quiz",
        )
        dialog.save(
            self,
            None,
            partial(self.on_share_dialog_finished, quiz_id=item["id"]),
        )

    def on_share_dialog_finished(
        self, dialog, result, _user_data=None, *, quiz_id: int
    ):
        """Handle the quiz share save result."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.save_finish,
            _("Share Failed"),
        )
        if selected_file is None:
            return

        try:
            payload = self._get_quiz_export_payload(
                quiz_id,
                _("Quiz could not be loaded for export."),
            )
            save_quiz_file(path_from_file(selected_file), payload)
        except Exception as exc:
            self._show_alert(_("Share Failed"), str(exc))

    def on_export_flashcard_package_clicked(self, _button, item, popover):
        """Open a save dialog to export a flashcard deck as APKG."""
        popover.popdown()

        dialog = build_file_dialog(
            title=_("Export Flashcards"),
            accept_label=_("Save"),
            filters=[build_apkg_file_filter()],
            initial_name=f"{item['title']}.apkg",
        )
        dialog.save(
            self,
            None,
            partial(
                self.on_export_flashcard_package_finished,
                deck_id=item["id"],
            ),
        )

    def on_export_flashcard_package_finished(
        self, dialog, result, _user_data=None, *, deck_id: int
    ):
        """Handle the flashcard APKG save result."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.save_finish,
            _("Export Failed"),
        )
        if selected_file is None:
            return

        try:
            payload = self._get_flashcard_export_payload(
                deck_id,
                _("Flashcards could not be loaded for export."),
            )
            save_apkg_file(path_from_file(selected_file), payload)
        except Exception as exc:
            self._show_alert(_("Export Failed"), str(exc))

    def on_export_quiz_clicked(self, _button, item, popover):
        """Prompt for quiz PDF export options."""
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
        dialog.connect("response", self.on_export_quiz_response, item)
        dialog.present(self)

    def on_export_quiz_response(self, _dialog, response, item):
        """Handle the quiz PDF export option response."""
        if response == "cancel":
            return

        include_answer_key = response == "with-answers"
        dialog = build_file_dialog(
            title=_("Export Quiz PDF"),
            accept_label=_("Export"),
            filters=[build_pdf_file_filter()],
            initial_name=f"{item['title']}.pdf",
        )
        dialog.save(
            self,
            None,
            partial(
                self.on_export_quiz_dialog_finished,
                quiz_id=item["id"],
                include_answer_key=include_answer_key,
            ),
        )

    def on_export_quiz_dialog_finished(
        self,
        dialog,
        result,
        _user_data=None,
        *,
        quiz_id: int,
        include_answer_key: bool,
    ):
        """Handle the quiz PDF save result and run export."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.save_finish,
            _("Export Failed"),
        )
        if selected_file is None:
            return

        try:
            payload = self._get_quiz_export_payload(
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

    def on_export_flashcard_pdf_clicked(self, _button, item, popover):
        """Prompt for flashcard PDF export options."""
        popover.popdown()

        dialog = Adw.AlertDialog(
            heading=_("Export Flashcard PDF"),
            body=_("Choose which sides should appear in the exported study sheet."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("both", _("Show Term and Definition"))
        dialog.add_response("hide-definition", _("Hide Definition"))
        dialog.add_response("hide-term", _("Hide Term"))
        dialog.set_default_response("both")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_export_flashcard_pdf_response, item)
        dialog.present(self)

    def on_export_flashcard_pdf_response(self, _dialog, response, item):
        """Handle the flashcard PDF export option response."""
        if response == "cancel":
            return

        dialog = build_file_dialog(
            title=_("Export Flashcard PDF"),
            accept_label=_("Export"),
            filters=[build_pdf_file_filter()],
            initial_name=f"{item['title']}.pdf",
        )
        dialog.save(
            self,
            None,
            partial(
                self.on_export_flashcard_pdf_dialog_finished,
                deck_id=item["id"],
                export_mode=response,
            ),
        )

    def on_export_flashcard_pdf_dialog_finished(
        self,
        dialog,
        result,
        _user_data=None,
        *,
        deck_id: int,
        export_mode: str,
    ):
        """Handle the flashcard PDF save result and run export."""
        selected_file = self._finish_file_dialog(
            result,
            dialog.save_finish,
            _("Export Failed"),
        )
        if selected_file is None:
            return

        try:
            payload = self._get_flashcard_export_payload(
                deck_id,
                _("Flashcards could not be loaded for PDF export."),
            )
            generate_flashcard_pdf(
                path_from_file(selected_file),
                payload,
                export_mode=export_mode,
            )
        except Exception as exc:
            self._show_alert(_("Export Failed"), str(exc))

    def on_delete_quiz_clicked(self, _button, item, popover):
        """Confirm quiz deletion."""
        popover.popdown()

        dialog = Adw.AlertDialog(
            heading=_("Delete Quiz?"),
            body=_('"{title}" will be removed from your library.').format(
                title=item["title"]
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_delete_quiz_response, item["id"])
        dialog.present(self)

    def on_delete_quiz_response(self, _dialog, response, quiz_id):
        """Delete the quiz if the user confirmed."""
        if response != "delete":
            return

        delete_quiz(quiz_id)
        self.load_library()

    def on_delete_flashcard_clicked(self, _button, item, popover):
        """Confirm flashcard deck deletion."""
        popover.popdown()

        dialog = Adw.AlertDialog(
            heading=_("Delete Flashcards?"),
            body=_('"{title}" will be removed from your library.').format(
                title=item["title"]
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_delete_flashcard_response, item["id"])
        dialog.present(self)

    def on_delete_flashcard_response(self, _dialog, response, deck_id):
        """Delete the flashcard deck if the user confirmed."""
        if response != "delete":
            return

        delete_flashcard_deck(deck_id)
        self.load_library()
