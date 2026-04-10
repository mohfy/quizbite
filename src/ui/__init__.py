"""UI package.

Exports the main window and the quiz editor dialog.
"""

from .editor import QuizEditorDialog
from .window import QuizbiteWindow

__all__ = [
    "QuizEditorDialog",
    "QuizbiteWindow",
]
