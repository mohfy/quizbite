"""Score page builder.

Creates the final "Quiz Complete" page.
"""

from __future__ import annotations

from collections.abc import Callable
from gettext import gettext as _

from gi.repository import Adw, Gtk


def build_score_page(
    score: int,
    total_questions: int,
    on_retry: Callable,
    on_go_home: Callable,
) -> Adw.NavigationPage:
    """Build a navigation page for the final score."""
    toolbar_view = Adw.ToolbarView()
    header_bar = Adw.HeaderBar()
    header_bar.set_show_back_button(False)
    toolbar_view.add_top_bar(header_bar)

    passed_quiz = score / total_questions >= 0.5
    score_icon = "face-smile-symbolic" if passed_quiz else "face-sad-symbolic"
    status_page = Adw.StatusPage(
        icon_name=score_icon,
        title=_("Quiz Complete"),
        description=_("You scored {score} out of {total}.").format(
            score=score,
            total=total_questions,
        ),
    )

    buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    buttons_box.set_halign(Gtk.Align.CENTER)
    buttons_box.set_margin_top(24)

    retry_button = Gtk.Button(label=_("Try Again"))
    retry_button.add_css_class("pill")
    retry_button.add_css_class("suggested-action")
    retry_button.connect("clicked", on_retry)
    buttons_box.append(retry_button)

    home_button = Gtk.Button(label=_("Back to Library"))
    home_button.add_css_class("pill")
    home_button.connect("clicked", on_go_home)
    buttons_box.append(home_button)

    status_page.set_child(buttons_box)
    toolbar_view.set_content(status_page)

    score_page = Adw.NavigationPage.new(toolbar_view, _("Score"))
    score_page.set_can_pop(False)
    return score_page
