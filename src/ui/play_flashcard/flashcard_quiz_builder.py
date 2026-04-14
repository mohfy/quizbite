"""Build multiple-choice quiz sessions from flashcard decks."""

from __future__ import annotations

import random
from gettext import gettext as _

SIDE_TERM = "term"
SIDE_DEFINITION = "definition"


def build_flashcard_quiz(deck_data: dict, prompt_side: str) -> dict:
    """Convert a flashcard deck into a multiple-choice quiz payload."""
    cards = list(deck_data["cards"])
    if len(cards) < 2:
        raise ValueError(_("Quiz mode needs at least two flashcards."))

    target_side = _opposite_side(prompt_side)
    shuffled_cards = random.sample(cards, len(cards))
    questions = []

    for card in shuffled_cards:
        correct_option_text = _format_side_option_text(card, target_side)
        distractor_option_texts = _pick_distractor_options(
            cards=cards,
            excluded_card=card,
            side=target_side,
            excluded_option_text=correct_option_text,
        )

        option_texts = [correct_option_text, *distractor_option_texts]
        random.shuffle(option_texts)
        correct_index = option_texts.index(correct_option_text)

        question_payload = {
            "title": _build_question_title(card, prompt_side),
            "options": [
                {
                    "text": option_text,
                    "is_correct": option_index == correct_index,
                }
                for option_index, option_text in enumerate(option_texts)
            ],
        }
        prompt_image = card.get(f"{prompt_side}_image")
        if prompt_image is not None:
            question_payload["image"] = prompt_image

        questions.append(question_payload)

    return {
        "title": _("{title} (Quiz Mode)").format(title=deck_data["title"]),
        "questions": questions,
    }


def _pick_distractor_options(
    *,
    cards: list[dict],
    excluded_card: dict,
    side: str,
    excluded_option_text: str,
) -> list[str]:
    """Return up to three distinct distractor option labels."""
    distractor_cards = [card for card in cards if card is not excluded_card]
    random.shuffle(distractor_cards)

    distractors = []
    seen_options = {excluded_option_text}

    for card in distractor_cards:
        option_text = _format_side_option_text(card, side)
        if option_text in seen_options:
            continue

        distractors.append(option_text)
        seen_options.add(option_text)
        if len(distractors) == 3:
            break

    return distractors


def _build_question_title(card: dict, prompt_side: str) -> str:
    """Return the prompt title shown by the quiz player."""
    prompt_text = (card.get(f"{prompt_side}_text") or "").strip()
    if prompt_text:
        return prompt_text

    if prompt_side == SIDE_TERM:
        return _("Identify the matching definition for this image.")

    return _("Identify the matching term for this image.")


def _format_side_option_text(card: dict, side: str) -> str:
    """Render a side into a compact option label."""
    side_text = (card.get(f"{side}_text") or "").strip()
    side_has_image = card.get(f"{side}_image") is not None

    if side_text and side_has_image:
        return _("{text} [Image]").format(text=side_text)
    if side_text:
        return side_text
    if side == SIDE_TERM:
        return _("[Image Term]")
    return _("[Image Definition]")


def _opposite_side(side: str) -> str:
    """Return the opposite flashcard side name."""
    return SIDE_DEFINITION if side == SIDE_TERM else SIDE_TERM
