# main.py
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

"""Application entrypoint.

Defines the `Adw.Application`.
Registers global actions and shortcuts.
"""

import sys
from gettext import gettext as _

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from .ui import QuizbiteWindow, QuizEditorDialog

APPLICATION_ID = "dev.mohfy.quizbite"
APPLICATION_NAME = _("Quizbite")
APPLICATION_DEVELOPER_NAME = "mohfy"
APPLICATION_WEBSITE = "https://github.com/mohfy/quizbite"
APPLICATION_ISSUES_URL = "https://github.com/mohfy/quizbite/issues"
APPLICATION_COMMENTS = _("Create quizzes, study flashcards, and export both.")


class QuizbiteApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, version: str):
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            resource_base_path="/dev/mohfy/quizbite",
        )
        self.version = version
        self.create_action("quit", lambda *_: self.quit(), ["<control>q"])
        self.create_action("about", self.on_about_action)
        self.create_action(
            "shortcuts",
            self.on_shortcuts_action,
            ["<control>question"],
        )
        self.create_action("create", self.on_create_action, ["<control>n"])
        self.create_action("import", self.on_import_action, ["<control>o"])

    def do_activate(self):
        """Create or present the main window."""
        win = self.props.active_window
        if not win:
            win = QuizbiteWindow(application=self)
        win.present()

    def on_about_action(self, *args):
        """Show the About dialog."""
        about = Adw.AboutDialog(
            application_name=APPLICATION_NAME,
            application_icon=APPLICATION_ID,
            developer_name=APPLICATION_DEVELOPER_NAME,
            version=self.version,
            comments=APPLICATION_COMMENTS,
            website=APPLICATION_WEBSITE,
            issue_url=APPLICATION_ISSUES_URL,
            license_type=Gtk.License.GPL_3_0,
            translator_credits=_("translator-credits"),
            developers=[APPLICATION_DEVELOPER_NAME],
            copyright="© 2026 mohfy",
        )
        about.present(self.props.active_window)

    def on_shortcuts_action(self, *args):
        """Show the shortcuts window."""
        builder = Gtk.Builder.new_from_resource(
            "/dev/mohfy/quizbite/shortcuts_dialog.ui"
        )
        dialog = builder.get_object("shortcuts_dialog")
        dialog.present(self.props.active_window)

    def on_create_action(self, *args):
        """Open the quiz editor dialog."""
        dialog = QuizEditorDialog()
        dialog.present(self.props.active_window)

    def on_import_action(self, *args):
        """Trigger the window import flow, if available."""
        window = self.props.active_window
        if window is not None and hasattr(window, "open_import_dialog"):
            window.open_import_dialog()

    def create_action(self, name, callback, shortcuts=None):
        """Register an app action and optional accelerators."""
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version):
    """Run the application.

    `version` is passed by the Meson wrapper script.
    """
    app = QuizbiteApplication(version)
    return app.run(sys.argv)
