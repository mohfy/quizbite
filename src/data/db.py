"""SQLite persistence for quizzes.

Uses `dataset` to manage a small SQLite database in the user data dir.
This module owns the DB schema and CRUD helpers.
"""

from __future__ import annotations

from pathlib import Path

import dataset
from gi.repository import GLib

APP_DATA_DIR_NAME = "dev.mohfy.quizbite"
DB_FILE_NAME = "quizbite.db"


def get_data_dir() -> Path:
    """Return the app data directory.

    Creates it if needed.
    """
    data_dir = Path(GLib.get_user_data_dir()) / APP_DATA_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Return the SQLite DB path."""
    return get_data_dir() / DB_FILE_NAME


def get_db():
    """Open a `dataset` connection to the SQLite DB."""
    db_path = get_db_path()
    return dataset.connect(f"sqlite:///{db_path}")


def save_quiz(quiz_data: dict) -> int:
    """Insert a quiz and its questions.

    Expected payload shape:
    - `title`: str
    - `questions`: list of:
      - `question`: str
      - `options`: list[str]
      - `correct_index`: int
      - `image`: optional dict with base64 data
    """
    db = get_db()

    with db as tx:
        quiz_id = tx["quizzes"].insert(
            {
                "title": quiz_data["title"],
            }
        )

        for question_index, question in enumerate(quiz_data["questions"]):
            question_record = {
                "quiz_id": quiz_id,
                "position": question_index,
                "title": question["question"],
            }
            question_image = question.get("image")
            if question_image is not None:
                question_record.update(
                    {
                        "image_filename": question_image["filename"],
                        "image_media_type": question_image["media_type"],
                        "image_data": question_image["data"],
                    }
                )

            question_id = tx["questions"].insert(
                question_record
            )

            for option_index, option_text in enumerate(question["options"]):
                tx["options"].insert(
                    {
                        "question_id": question_id,
                        "position": option_index,
                        "text": option_text,
                        "is_correct": option_index == question["correct_index"],
                    }
                )

    return quiz_id


def get_quizzes() -> list[dict]:
    """Return all quizzes, ordered by id."""
    db = get_db()
    return list(db["quizzes"].find(order_by="id"))


def get_quizzes_with_question_counts() -> list[dict]:
    """Return quizzes with a `question_count` field."""
    quizzes = get_quizzes()
    if not quizzes:
        return []

    db = get_db()
    question_counts = {quiz["id"]: 0 for quiz in quizzes}

    for question in db["questions"].find(order_by="quiz_id"):
        quiz_id = question["quiz_id"]
        if quiz_id in question_counts:
            question_counts[quiz_id] += 1

    for quiz in quizzes:
        quiz["question_count"] = question_counts[quiz["id"]]

    return quizzes


def get_quiz(quiz_id: int) -> dict | None:
    """Load a quiz with questions and options.

    Returns `None` if the quiz does not exist.
    """
    db = get_db()

    quiz = db["quizzes"].find_one(id=quiz_id)
    if quiz is None:
        return None

    question_rows = list(db["questions"].find(quiz_id=quiz_id, order_by="position"))
    questions = []

    for question in question_rows:
        option_rows = list(
            db["options"].find(question_id=question["id"], order_by="position")
        )

        question_payload = {
            "id": question["id"],
            "title": question["title"],
            "options": option_rows,
        }
        if question.get("image_data"):
            question_payload["image"] = {
                "filename": question.get("image_filename") or "question-image",
                "media_type": question.get("image_media_type") or "image/png",
                "data": question["image_data"],
            }

        questions.append(question_payload)

    quiz["questions"] = questions
    return quiz


def export_quiz(quiz_id: int) -> dict | None:
    """Build a portable quiz payload.

    This output matches the `.quiz` JSON format.
    Returns `None` if the quiz does not exist.
    """
    quiz = get_quiz(quiz_id)
    if quiz is None:
        return None

    questions = []
    for question in quiz["questions"]:
        correct_index = None
        option_texts = []

        for index, option in enumerate(question["options"]):
            option_texts.append(option["text"])
            if option["is_correct"]:
                correct_index = index

        question_payload = {
            "question": question["title"],
            "options": option_texts,
            "correct_index": correct_index,
        }
        if question.get("image") is not None:
            question_payload["image"] = question["image"]

        questions.append(question_payload)

    return {
        "title": quiz["title"],
        "questions": questions,
    }


def delete_quiz(quiz_id: int) -> None:
    """Delete a quiz and its related rows."""
    db = get_db()

    with db as tx:
        question_rows = list(tx["questions"].find(quiz_id=quiz_id))
        question_ids = [question["id"] for question in question_rows]

        for question_id in question_ids:
            tx["options"].delete(question_id=question_id)

        tx["questions"].delete(quiz_id=quiz_id)
        tx["quizzes"].delete(id=quiz_id)
