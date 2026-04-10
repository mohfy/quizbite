"""Quiz session state and helpers.

Stores the current quiz and selected answers.
Provides small GTK action helpers for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gi.repository import Adw, Gio, GLib, Gtk

UNANSWERED_OPTION = ""


@dataclass(slots=True)
class QuizSession:
    """In-memory session state for the quiz player."""
    quiz: dict
    selected_answers: list[int | None]
    question_pages: list[Adw.NavigationPage] = field(default_factory=list)


def create_answer_action(
    session: QuizSession,
    question_index: int,
    on_change_state,
) -> Gio.SimpleAction:
    """Create a stateful action for selecting an answer."""
    action = Gio.SimpleAction.new_stateful(
        "select-answer",
        GLib.VariantType.new("s"),
        GLib.Variant.new_string(get_selected_answer_state(session, question_index)),
    )
    action.connect("change-state", on_change_state, question_index)
    return action


def create_action_group(action: Gio.SimpleAction) -> Gio.SimpleActionGroup:
    """Wrap an action in an action group."""
    action_group = Gio.SimpleActionGroup()
    action_group.add_action(action)
    return action_group


def build_option_check_button(
    option_text: str,
    option_index: int,
    first_check: Gtk.CheckButton | None,
) -> Gtk.CheckButton:
    """Build a check button wired to the answer action."""
    option_label = Gtk.Label(label=option_text, xalign=0)
    option_label.set_margin_start(8)

    option_check = Gtk.CheckButton()
    option_check.set_halign(Gtk.Align.START)
    option_check.set_child(option_label)
    option_check.set_action_name("question.select-answer")
    option_check.set_action_target_value(GLib.Variant.new_string(str(option_index)))

    if first_check is not None:
        option_check.set_group(first_check)

    return option_check


def get_selected_answer_state(session: QuizSession, question_index: int) -> str:
    """Return the action state string for a question."""
    selected_answer = session.selected_answers[question_index]
    if selected_answer is None:
        return UNANSWERED_OPTION

    return str(selected_answer)


def set_selected_answer_from_state(
    session: QuizSession,
    question_index: int,
    state: GLib.Variant,
) -> None:
    """Update session state from an action state."""
    selected_answer = state.get_string()
    session.selected_answers[question_index] = (
        None if selected_answer == UNANSWERED_OPTION else int(selected_answer)
    )


def calculate_score(session: QuizSession) -> tuple[int, int]:
    """Compute `(score, total_questions)` for the session."""
    total_questions = len(session.quiz["questions"])
    score = 0

    for selected_index, question in zip(
        session.selected_answers,
        session.quiz["questions"],
    ):
        if selected_index is None:
            continue

        if question["options"][selected_index]["is_correct"]:
            score += 1

    return score, total_questions
