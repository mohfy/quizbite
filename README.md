# Quizbite

Quizbite is a small GNOME app to create and play quizzes.

It supports:
- Create quizzes with multiple choice questions.
- Optional question images.
- Import and export `.quiz` files.
- Export a quiz to PDF.

## Build And Run

Open the project in GNOME Builder and run it there.

GNOME Builder handles the build automatically for this project.

## Flatpak

The Flatpak manifest is `dev.mohfy.quizbite.json`.

```bash
flatpak-builder builddir dev.mohfy.quizbite.json --user --install --force-clean
flatpak run dev.mohfy.quizbite
```

## Translations
- Add `po/<lang>.po`
- Add `<lang>` to `po/LINGUAS`


## Quiz File Format

Quiz files are JSON.
The extension is usually `.quiz`.

Top level keys:
- `title`: string
- `questions`: list

Each question:
- `question`: string
- `options`: list of strings
- `correct_index`: int
- `image`: optional object 

Image object:
- `filename`: string
- `media_type`: string, starts with `image/`
- `data`: base64 string
