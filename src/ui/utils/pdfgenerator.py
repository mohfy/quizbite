"""PDF export support.

Builds an HTML representation of a quiz.
Renders it to PDF via WebKit printing.
"""

from __future__ import annotations

from html import escape
from gettext import gettext as _, ngettext
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")

from gi.repository import GLib, Gtk, WebKit

OPTION_GRID_MAX_CHARS = 28


def generate_quiz_pdf(
    path: str | Path, quiz_data: dict, include_answer_key: bool
) -> Path:
    """Generate a PDF for `quiz_data`.

    Ensures the output path has a `.pdf` suffix.
    """
    pdf_path = Path(path)
    if pdf_path.suffix != ".pdf":
        pdf_path = pdf_path.with_suffix(".pdf")

    html = _build_quiz_html(quiz_data, include_answer_key)
    _render_html_to_pdf(html, pdf_path)
    return pdf_path


def _render_html_to_pdf(html: str, pdf_path: Path) -> None:
    """Render HTML to a PDF file path."""
    loop = GLib.MainLoop()
    error_holder: dict[str, Exception] = {}

    web_view = WebKit.WebView()

    settings = Gtk.PrintSettings()
    settings.set(Gtk.PRINT_SETTINGS_PRINTER, "Print to File")
    settings.set(Gtk.PRINT_SETTINGS_OUTPUT_URI, pdf_path.resolve().as_uri())
    settings.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
    settings.set(Gtk.PRINT_SETTINGS_OUTPUT_BASENAME, pdf_path.stem)

    operation = WebKit.PrintOperation.new(web_view)
    operation.set_print_settings(settings)

    def on_load_changed(view, load_event):
        if load_event != WebKit.LoadEvent.FINISHED:
            return

        try:
            operation.print_()
        except Exception as exc:
            error_holder["error"] = exc
            loop.quit()

    def on_load_failed(view, load_event, failing_uri, error):
        error_holder["error"] = RuntimeError(error.message)
        loop.quit()
        return False

    def on_print_failed(_operation, error):
        error_holder["error"] = RuntimeError(error.message)
        loop.quit()

    def on_print_finished(_operation):
        loop.quit()

    web_view.connect("load-changed", on_load_changed)
    web_view.connect("load-failed", on_load_failed)
    operation.connect("failed", on_print_failed)
    operation.connect("finished", on_print_finished)
    web_view.load_html(html)
    loop.run()

    error = error_holder.get("error")
    if error is not None:
        raise error

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(_("PDF export completed without writing an output file."))


def _build_quiz_html(quiz_data: dict, include_answer_key: bool) -> str:
    """Build the HTML markup used for printing."""
    question_sections = []
    answer_key_sections = []
    question_count = len(quiz_data["questions"])
    fallback_title = _("Quiz")
    title = escape((quiz_data.get("title") or fallback_title).strip() or fallback_title)
    no_answer_key_available = _("No answer key available")
    answer_key_title = _("Answer Key")
    question_label_template = _("Question {number}")
    answer_number_template = _("Q{number}:")
    subtitle = ngettext(
        "{count} question",
        "{count} questions",
        question_count,
    ).format(count=question_count)
    empty_state_message = _("No printable questions available.")

    for question_index, question in enumerate(quiz_data["questions"], start=1):
        options_markup = []
        correct_option_label = None
        question_title = escape(question["question"])
        image_markup = _build_question_image_markup(question.get("image"))

        for option_index, option_text in enumerate(question["options"], start=1):
            option_letter = chr(64 + option_index)
            options_markup.append(
                _build_option_markup(option_letter, option_text)
            )

            if question["correct_index"] == option_index - 1:
                correct_option_label = f"{option_letter}. {escape(option_text)}"

        question_sections.append(
            """
            <section class="question-card">
              <div class="question-label">{question_label}</div>
              <h2 class="question-title">{title}</h2>
              {image}
              {options}
            </section>
            """.format(
                number=question_index,
                question_label=escape(
                    question_label_template.format(number=question_index)
                ),
                title=question_title,
                image=image_markup,
                options=_build_options_layout_markup(options_markup, question["options"]),
            )
        )

        if include_answer_key:
            answer_key_sections.append(
                """
                <li class="answer-row">
                  <div class="answer-line">
                    <span class="answer-number">{answer_number}</span>
                    <span class="answer-value">{answer}</span>
                  </div>
                  <div class="answer-question">{title}</div>
                </li>
                """.format(
                    number=question_index,
                    answer_number=escape(
                        answer_number_template.format(number=question_index)
                    ),
                    title=question_title,
                    answer=correct_option_label or escape(no_answer_key_available),
                )
            )

    answer_key_markup = ""
    if include_answer_key:
        answer_key_markup = """
        <section class="answer-key">
          <div class="answer-key-header">
            <h2>{title}</h2>
          </div>
          <ol class="answer-key-list">
            {answers}
          </ol>
        </section>
        """.format(title=escape(answer_key_title), answers="".join(answer_key_sections))

    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <style>
          @page {{
            size: A4;
            margin: 12mm;
          }}

          :root {{
            color-scheme: light;
            --text: #141414;
            --secondary: rgba(33, 33, 33, 0.78);
            --divider: #d6d6d6;
            --card-bg: #fcfcfc;
            --accent: #007aff;
            --badge-border: #cfd2d7;
          }}

          body {{
            font-family: "Adwaita Sans", "Cantarell", sans-serif;
            color: var(--text);
            line-height: 1.35;
            font-size: 10.5pt;
            margin: 0;
          }}

          * {{
            box-sizing: border-box;
          }}

          header {{
            margin-bottom: 10mm;
          }}

          h1 {{
            font-size: 20pt;
            font-weight: 700;
            margin: 0;
            line-height: 1.15;
          }}

          h2 {{
            margin: 0;
          }}

          .subtitle {{
            color: var(--secondary);
            font-size: 9.5pt;
            margin-top: 3px;
          }}

          .header-divider {{
            height: 1px;
            background: var(--divider);
            margin-top: 9px;
          }}

          .question-card {{
            background: var(--card-bg);
            border: 0.5px solid var(--divider);
            border-radius: 12px;
            padding: 10px 12px 12px;
            margin-bottom: 8px;
            page-break-inside: avoid;
          }}

          .question-label {{
            color: var(--secondary);
            font-size: 8pt;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 4px;
          }}

          .question-title {{
            font-size: 12pt;
            font-weight: 700;
            line-height: 1.24;
            margin-bottom: 7px;
          }}

          .question-image-wrap {{
            display: inline-block;
            margin: 0 0 9px;
            padding: 6px;
            border: 0.5px solid var(--divider);
            border-radius: 10px;
            background: white;
            max-width: 96mm;
            vertical-align: top;
          }}

          .question-image {{
            display: block;
            width: auto;
            height: auto;
            max-width: 84mm;
            max-height: 46mm;
            object-fit: contain;
          }}

          .options-list {{
            list-style: none;
            margin: 0;
            padding: 0;
          }}

          .options-grid-row {{
            display: table;
            width: 100%;
            table-layout: fixed;
            margin: 0 0 5px;
          }}

          .options-grid-row:last-child {{
            margin-bottom: 0;
          }}

          .option-cell {{
            display: table-cell;
            width: 50%;
            vertical-align: top;
            padding-right: 10px;
          }}

          .option-cell:last-child {{
            padding-right: 0;
            padding-left: 10px;
          }}

          .option-cell-empty {{
            padding-left: 0;
          }}

          .option-row {{
            display: table;
            width: 100%;
            margin: 0 0 5px;
          }}

          .option-row:last-child {{
            margin-bottom: 0;
          }}

          .option-badge {{
            display: table-cell;
            width: 18px;
            height: 18px;
            border: 1px solid var(--badge-border);
            border-radius: 999px;
            text-align: center;
            vertical-align: top;
            font-size: 8.5pt;
            line-height: 16px;
            font-weight: 600;
            color: var(--secondary);
          }}

          .option-text {{
            display: table-cell;
            padding-left: 8px;
            font-size: 10.5pt;
            line-height: 1.3;
            vertical-align: top;
          }}

          .answer-key {{
            margin-top: 12px;
            page-break-before: always;
          }}

          .answer-key-header {{
            padding-top: 2px;
            margin-bottom: 10px;
            border-bottom: 1px solid var(--divider);
          }}

          .answer-key-header h2 {{
            color: var(--accent);
            font-size: 13pt;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 6px;
          }}

          .answer-key-list {{
            list-style: none;
            padding: 0;
            margin: 0;
          }}

          .answer-row {{
            margin-bottom: 7px;
            page-break-inside: avoid;
          }}

          .answer-line {{
            margin-bottom: 2px;
          }}

          .answer-number {{
            font-weight: 700;
            color: var(--text);
            margin-right: 4px;
          }}

          .answer-value {{
            color: var(--text);
          }}

          .answer-question {{
            color: var(--secondary);
            font-size: 9.5pt;
            line-height: 1.25;
          }}

          .empty-state {{
            color: var(--secondary);
            font-size: 9.5pt;
          }}

          @media print {{
            .question-card {{
              break-inside: avoid;
            }}

            .answer-row {{
              break-inside: avoid;
            }}
          }}
        </style>
      </head>
      <body>
        <header>
          <h1>{title}</h1>
          <div class="subtitle">{subtitle}</div>
          <div class="header-divider"></div>
        </header>
        {questions}
        {empty_state}
        {answer_key}
      </body>
    </html>
    """.format(
        title=title,
        subtitle=escape(subtitle),
        questions="".join(question_sections),
        empty_state=""
        if question_sections
        else "<p class='empty-state'>{message}</p>".format(
            message=escape(empty_state_message)
        ),
        answer_key=answer_key_markup,
    )


def _build_question_image_markup(image: dict | None) -> str:
    """Build an `<img>` block for an optional question image."""
    if image is None:
        return ""

    question_image_alt = _("Question image")
    image_src = "data:{media_type};base64,{data}".format(
        media_type=image["media_type"],
        data=image["data"],
    )
    return """
    <div class="question-image-wrap">
      <img class="question-image" src="{src}" alt="{alt}" />
    </div>
    """.format(
        src=escape(image_src, quote=True),
        alt=escape(question_image_alt, quote=True),
    )


def _build_option_markup(option_letter: str, option_text: str) -> str:
    """Build markup for one option row."""
    return """
    <div class="option-row">
      <span class="option-badge">{letter}</span>
      <span class="option-text">{text}</span>
    </div>
    """.format(
        letter=option_letter,
        text=escape(option_text),
    )


def _build_options_layout_markup(
    option_markup: list[str],
    option_texts: list[str],
) -> str:
    """Choose list or two-column layout for options."""
    if not _should_use_option_grid(option_texts):
        return """
        <div class="options-list">
          {options}
        </div>
        """.format(options="".join(option_markup))

    grid_rows = []
    for option_index in range(0, len(option_markup), 2):
        row_markup = option_markup[option_index : option_index + 2]
        cells = [
            '<div class="option-cell">{option}</div>'.format(option=cell_markup)
            for cell_markup in row_markup
        ]
        if len(cells) == 1:
            cells.append('<div class="option-cell option-cell-empty"></div>')

        grid_rows.append(
            """
            <div class="options-grid-row">
              {cells}
            </div>
            """.format(cells="".join(cells))
        )

    return """
    <div class="options-list">
      {rows}
    </div>
    """.format(rows="".join(grid_rows))


def _should_use_option_grid(option_texts: list[str]) -> bool:
    """Return True if options fit well in a two-column grid."""
    return all(_option_is_short(option_text) for option_text in option_texts)


def _option_is_short(option_text: str) -> bool:
    """Heuristic for short, single-line option text."""
    normalized_text = " ".join(option_text.split())
    return (
        bool(normalized_text)
        and "\n" not in option_text
        and len(normalized_text) <= OPTION_GRID_MAX_CHARS
    )
