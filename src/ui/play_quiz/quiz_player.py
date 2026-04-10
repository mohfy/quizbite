"""Quiz player view controller.

Uses an `Adw.NavigationView` to run a quiz session.
Shows questions, tracks answers, and shows the final score.
"""

from __future__ import annotations

import base64
from functools import partial
from gettext import gettext as _

from gi.repository import Adw, Gdk, GLib, Gtk

from .quiz_session import (
    QuizSession,
    build_option_check_button,
    calculate_score,
    create_action_group,
    create_answer_action,
    set_selected_answer_from_state,
)
from .score_view import build_score_page


QUESTION_IMAGE_CSS = """
.question-image-button {
  padding: 0;
}

.question-image-surface {
  border-radius: 20px;
}
"""


class QuizPlayer:
    """Controls quiz play flow inside the main window."""

    _question_image_css_provider: Gtk.CssProvider | None = None
    _question_image_css_installed = False

    def __init__(self, navigation_view: Adw.NavigationView):
        """Create a player bound to a navigation view."""
        self.navigation_view = navigation_view
        self.quiz_page = None
        self.quiz_page_progress = None
        self.quiz_question_view = None
        self.quiz_session: QuizSession | None = None
        self.score_page = None
        self.image_dialog: Adw.Dialog | None = None

    def _require_session(self) -> QuizSession:
        """Return the active session or raise."""
        if self.quiz_session is None:
            raise RuntimeError(_("Quiz session is not active."))

        return self.quiz_session

    def open_quiz(self, quiz_data: dict) -> None:
        """Start a new quiz session and push the quiz page."""
        self._ensure_question_image_css()
        self._close_image_dialog()
        self._return_to_root_page()
        self._reset_quiz_state()
        self.quiz_session = QuizSession(
            quiz=quiz_data,
            selected_answers=[None] * len(quiz_data["questions"]),
        )
        self.quiz_page = Adw.NavigationPage.new(
            self._build_quiz_shell(quiz_data),
            quiz_data["title"],
        )
        self.navigation_view.push(self.quiz_page)

    def _get_root_page(self) -> Adw.NavigationPage | None:
        """Return the first page in the navigation stack."""
        navigation_stack = self.navigation_view.get_navigation_stack()
        if navigation_stack.get_n_items() == 0:
            return None

        page = navigation_stack.get_item(0)
        if not isinstance(page, Adw.NavigationPage):
            return None

        return page

    def _reset_quiz_state(self) -> None:
        """Clear cached widgets and session state."""
        self.score_page = None
        self.quiz_page = None
        self.quiz_page_progress = None
        self.quiz_question_view = None
        self.quiz_session = None

    def _return_to_root_page(self) -> None:
        """Return the UI to the library page."""
        root_page = self._get_root_page()
        if root_page is None:
            return

        visible_page = self.navigation_view.get_visible_page()
        navigation_stack = self.navigation_view.get_navigation_stack()
        if visible_page is root_page and navigation_stack.get_n_items() == 1:
            return

        if visible_page is not root_page and self.navigation_view.pop_to_page(root_page):
            return

        self.navigation_view.replace([root_page])

    def _build_quiz_shell(self, quiz_data: dict) -> Adw.ToolbarView:
        """Build the quiz page shell and its question pages."""
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=0,
            margin_top=12,
            margin_bottom=12,
        )

        progress_clamp = Adw.Clamp(maximum_size=720, tightening_threshold=480)
        progress_clamp.set_margin_start(18)
        progress_clamp.set_margin_end(18)

        self.quiz_page_progress = Gtk.ProgressBar()
        progress_clamp.set_child(self.quiz_page_progress)
        content_box.append(progress_clamp)

        self.quiz_question_view = Adw.NavigationView()
        self.quiz_question_view.set_vexpand(True)
        content_box.append(self.quiz_question_view)

        toolbar_view.set_content(content_box)

        session = self._require_session()
        total_questions = len(quiz_data["questions"])

        for question_index, question in enumerate(quiz_data["questions"]):
            page = self._build_question_page(question, question_index, total_questions)
            session.question_pages.append(page)
            self.quiz_question_view.add(page)

        self.quiz_question_view.push(session.question_pages[0])
        self._update_quiz_progress()
        return toolbar_view

    def _build_question_page(
        self,
        question: dict,
        question_index: int,
        total_questions: int,
    ) -> Adw.NavigationPage:
        """Build one question page."""
        page_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=24,
            margin_bottom=24,
            margin_start=32,
            margin_end=32,
            vexpand=True,
        )
        page_content.set_focusable(True)

        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=480)
        clamp.set_child(page_content)

        session = self._require_session()
        answer_action = create_answer_action(
            session,
            question_index,
            self.on_answer_selection_changed,
        )
        page_content.insert_action_group("question", create_action_group(answer_action))

        section_label = Gtk.Label(
            label=_("Question {current} of {total}").format(
                current=question_index + 1,
                total=total_questions,
            ),
            xalign=0,
        )
        section_label.add_css_class("caption-heading")
        page_content.append(section_label)

        question_label = Gtk.Label(
            label=question["title"],
            wrap=True,
            xalign=0,
        )
        question_label.add_css_class("title-2")
        page_content.append(question_label)

        question_image = self._build_question_image_widget(question)
        if question_image is not None:
            page_content.append(question_image)

        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        options_box.set_vexpand(True)
        page_content.append(options_box)

        option_count = 0
        first_check = None

        for option_index, option in enumerate(question["options"]):
            option_check = build_option_check_button(
                option["text"],
                option_index,
                first_check,
            )
            if first_check is None:
                first_check = option_check

            options_box.append(option_check)
            option_count += 1

        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        buttons_box.set_halign(Gtk.Align.FILL)

        previous_button = Gtk.Button(label=_("Previous"))
        previous_button.add_css_class("pill")
        previous_button.set_sensitive(question_index > 0)
        previous_button.connect(
            "clicked", self.on_previous_question_clicked, question_index
        )
        buttons_box.append(previous_button)

        buttons_box.append(Gtk.Box(hexpand=True))

        next_button = Gtk.Button(
            label=_("Finish") if question_index == total_questions - 1 else _("Next")
        )
        next_button.add_css_class("suggested-action")
        next_button.add_css_class("pill")
        next_button.connect("clicked", self.on_next_question_clicked, question_index)
        buttons_box.append(next_button)

        page_content.append(buttons_box)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect(
            "key-pressed",
            self.on_question_key_pressed,
            page_content,
            previous_button,
            next_button,
            option_count,
        )
        page_content.add_controller(key_controller)

        return Adw.NavigationPage.new(
            clamp, _("Question {number}").format(number=question_index + 1)
        )

    def on_answer_selection_changed(self, action, value, question_index: int) -> None:
        """Persist answer selection in the session state."""
        action.set_state(value)
        set_selected_answer_from_state(self._require_session(), question_index, value)
        self._update_quiz_progress()

    def _ensure_question_image_css(self) -> None:
        """Install CSS for question images once per process."""
        if QuizPlayer._question_image_css_installed:
            return

        display = self.navigation_view.get_display()
        if display is None:
            return

        provider = Gtk.CssProvider()
        provider.load_from_string(QUESTION_IMAGE_CSS)
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        QuizPlayer._question_image_css_provider = provider
        QuizPlayer._question_image_css_installed = True

    def _build_question_image_surface(
        self,
        texture: Gdk.Texture,
        *,
        height: int | None = None,
    ) -> Gtk.Box:
        """Build the styled image surface for the question page."""
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_hexpand(True)
        picture.set_halign(Gtk.Align.FILL)
        picture.set_valign(Gtk.Align.FILL)

        if height is None:
            picture.set_vexpand(True)
        else:
            picture.set_size_request(-1, height)

        surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        surface.add_css_class("question-image-surface")
        surface.set_hexpand(True)
        surface.set_vexpand(height is None)
        surface.set_overflow(Gtk.Overflow.HIDDEN)
        surface.append(picture)
        return surface

    def _build_question_image_preview(self, texture: Gdk.Texture) -> Gtk.Picture:
        """Build a larger preview for the image dialog."""
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        picture.set_hexpand(True)
        picture.set_vexpand(True)
        picture.set_halign(Gtk.Align.FILL)
        picture.set_valign(Gtk.Align.FILL)
        return picture

    def _build_question_image_widget(self, question: dict) -> Gtk.Widget | None:
        """Build an image button when the question has an image."""
        question_image = question.get("image")
        if question_image is None:
            return None

        try:
            texture = Gdk.Texture.new_from_bytes(
                GLib.Bytes.new(base64.b64decode(question_image["data"]))
            )
        except (GLib.Error, ValueError, TypeError):
            return None

        image_button = Gtk.Button()
        image_button.add_css_class("flat")
        image_button.add_css_class("question-image-button")
        image_button.set_has_frame(False)
        image_button.set_hexpand(True)
        image_button.set_halign(Gtk.Align.FILL)
        image_button.set_tooltip_text(_("Open image"))
        image_button.set_child(
            self._build_question_image_surface(texture, height=260)
        )
        image_button.connect(
            "clicked",
            self.on_question_image_clicked,
            texture,
            question_image.get("filename") or _("Question image"),
        )

        return image_button

    def _close_image_dialog(self) -> None:
        """Close the image dialog if it is open."""
        if self.image_dialog is None:
            return

        dialog = self.image_dialog
        self.image_dialog = None
        dialog.force_close()

    def on_question_image_clicked(
        self,
        _button,
        texture: Gdk.Texture,
        title: str,
    ) -> None:
        """Open an image dialog for the question image."""
        self._close_image_dialog()

        dialog = Adw.Dialog.new()
        dialog.set_title(title)
        dialog.set_can_close(True)
        dialog.set_follows_content_size(False)
        dialog.set_presentation_mode(Adw.DialogPresentationMode.FLOATING)

        root = self.navigation_view.get_root()
        content_width = 900
        content_height = 700
        if root is not None:
            content_width = max(360, min(int(root.get_width() * 0.88), 1200))
            content_height = max(280, min(int(root.get_height() * 0.88), 900))

        dialog.set_content_width(content_width)
        dialog.set_content_height(content_height)

        dialog.set_child(self._build_question_image_preview(texture))
        dialog.connect(
            "notify::visible",
            self.on_question_image_dialog_visibility_changed,
        )

        self.image_dialog = dialog
        dialog.present(self.navigation_view)

    def on_question_image_dialog_visibility_changed(
        self,
        dialog: Adw.Dialog,
        _pspec,
    ) -> None:
        """Drop the dialog reference after it is closed."""
        if not dialog.get_visible() and self.image_dialog is dialog:
            self.image_dialog = None

    def on_previous_question_clicked(self, _button, question_index: int) -> None:
        """Go to the previous question page."""
        if question_index == 0:
            return

        self.quiz_question_view.pop()

    def on_next_question_clicked(self, _button, question_index: int) -> None:
        """Go to the next question page or finish."""
        session = self._require_session()
        total_questions = len(session.quiz["questions"])

        if question_index == total_questions - 1:
            self._show_score_view()
            return

        self.quiz_question_view.push(session.question_pages[question_index + 1])

    def on_question_key_pressed(
        self,
        _controller,
        keyval: int,
        _keycode: int,
        _state,
        question_page: Gtk.Widget,
        previous_button: Gtk.Button,
        next_button: Gtk.Button,
        option_count: int,
    ) -> bool:
        """Handle keyboard navigation and number shortcuts."""
        if keyval == Gdk.KEY_Left:
            if previous_button.get_sensitive():
                previous_button.activate()
                return True
            return False

        if keyval == Gdk.KEY_Right:
            next_button.activate()
            return True

        key_to_index = {
            Gdk.KEY_1: 0,
            Gdk.KEY_2: 1,
            Gdk.KEY_3: 2,
            Gdk.KEY_4: 3,
            Gdk.KEY_KP_1: 0,
            Gdk.KEY_KP_2: 1,
            Gdk.KEY_KP_3: 2,
            Gdk.KEY_KP_4: 3,
        }

        option_index = key_to_index.get(keyval)
        if option_index is None or option_index >= option_count:
            return False

        return question_page.activate_action(
            "question.select-answer",
            GLib.Variant.new_string(str(option_index)),
        )

    def _update_quiz_progress(self) -> None:
        """Update the progress bar based on answered questions."""
        session = self._require_session()
        total_questions = len(session.quiz["questions"])
        answered_questions = sum(
            selected_answer is not None for selected_answer in session.selected_answers
        )

        self.quiz_page_progress.set_fraction(answered_questions / total_questions)
        self.quiz_page_progress.set_show_text(False)

    def _show_score_view(self) -> None:
        """Compute score and show the score page."""
        session = self._require_session()
        score, total_questions = calculate_score(session)
        self.score_page = build_score_page(
            score=score,
            total_questions=total_questions,
            on_retry=partial(self.on_retry_clicked, quiz_data=session.quiz),
            on_go_home=self.on_go_home_clicked,
        )
        self.navigation_view.push(self.score_page)

    def on_retry_clicked(self, _button, *, quiz_data: dict | None = None) -> None:
        """Restart the same quiz."""
        if quiz_data is None:
            session = self.quiz_session
            if session is None:
                return

            quiz_data = session.quiz

        self.open_quiz(quiz_data)

    def on_go_home_clicked(self, _button) -> None:
        """Return to the library and clear session state."""
        self._close_image_dialog()
        self._return_to_root_page()
        self._reset_quiz_state()
