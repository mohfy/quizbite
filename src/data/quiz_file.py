"""Quiz file load and save helpers.

Quiz files are JSON.
They are validated and normalized on load.
"""

from __future__ import annotations

import base64
import binascii
import json
from gettext import gettext as _
from pathlib import Path


def load_quiz_file(path: str | Path) -> dict:
    """Load and validate a quiz file."""
    quiz_path = Path(path)
    payload = json.loads(quiz_path.read_text(encoding="utf-8"))
    return normalize_quiz_payload(payload)


def save_quiz_file(path: str | Path, quiz_data: dict) -> Path:
    """Write a quiz file.

    Ensures the path has a `.quiz` suffix.
    """
    quiz_path = Path(path)
    if quiz_path.suffix != ".quiz":
        quiz_path = quiz_path.with_suffix(".quiz")

    quiz_path.write_text(
        json.dumps(quiz_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return quiz_path


def normalize_question_image(payload: object) -> dict | None:
    """Validate and normalize a question image object.

    Returns `None` when no image is provided.
    """
    if payload is None:
        return None

    if not isinstance(payload, dict):
        raise ValueError(_("Question image must be a JSON object."))

    filename = payload.get("filename", "")
    media_type = payload.get("media_type", "")
    data = payload.get("data", "")

    if not isinstance(filename, str) or not filename.strip():
        raise ValueError(_("Question image filename is required."))

    if not isinstance(media_type, str) or not media_type.strip():
        raise ValueError(_("Question image media_type is required."))

    if not media_type.strip().startswith("image/"):
        raise ValueError(_("Question image media_type must be an image MIME type."))

    if not isinstance(data, str) or not data.strip():
        raise ValueError(_("Question image data is required."))

    try:
        base64.b64decode(data.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(_("Question image data must be valid base64.")) from exc

    return {
        "filename": filename.strip(),
        "media_type": media_type.strip(),
        "data": data.strip(),
    }


def normalize_quiz_payload(payload: dict) -> dict:
    """Validate and normalize the quiz JSON payload."""
    if not isinstance(payload, dict):
        raise ValueError(_("Quiz file must contain a JSON object."))

    title = payload.get("title", "")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(_("Quiz title is required."))

    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError(_("Quiz must include at least one question."))

    normalized_questions = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError(_("Each question must be a JSON object."))

        question_title = question.get("question", "")
        options = question.get("options")
        correct_index = question.get("correct_index")
        normalized_image = normalize_question_image(question.get("image"))

        if not isinstance(question_title, str) or not question_title.strip():
            raise ValueError(_("Each question needs text."))

        if not isinstance(options, list) or len(options) < 2:
            raise ValueError(_("Each question must have at least two options."))

        normalized_options = []
        for option in options:
            if not isinstance(option, str) or not option.strip():
                raise ValueError(_("Options must be non-empty strings."))
            normalized_options.append(option.strip())

        if not isinstance(correct_index, int) or not (
            0 <= correct_index < len(normalized_options)
        ):
            raise ValueError(_("Each question must have a valid correct_index."))

        normalized_question = {
            "question": question_title.strip(),
            "options": normalized_options,
            "correct_index": correct_index,
        }
        if normalized_image is not None:
            normalized_question["image"] = normalized_image

        normalized_questions.append(normalized_question)

    return {
        "title": title.strip(),
        "questions": normalized_questions,
    }
