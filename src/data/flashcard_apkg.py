"""APKG import/export helpers for flashcard decks.

The importer targets simple front/back cards and preserves text plus images.
The exporter writes a minimal Anki collection package that round-trips cleanly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import sqlite3
import tempfile
import time
import uuid
import zipfile
from gettext import gettext as _
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

FIELD_SEPARATOR = "\x1f"
ANKI_SCHEMA_VERSION = 11
ANKI_COLLECTION_FILES = (
    "collection.anki21",
    "collection.anki2",
)
ANKI_MODEL_CSS = """
.card {
  font-family: Arial;
  font-size: 20px;
  text-align: center;
  color: black;
  background-color: white;
}

img {
  max-width: 95%;
  height: auto;
}
""".strip()

SOUND_TAG_PATTERN = re.compile(r"\[sound:[^\]]+\]", re.IGNORECASE)


class _FlashcardFieldParser(HTMLParser):
    """Extract text and `<img>` references from Anki field HTML."""

    _BLOCK_TAGS = {
        "div",
        "p",
        "li",
        "ul",
        "ol",
        "section",
        "article",
        "table",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self.image_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            attributes = dict(attrs)
            image_source = attributes.get("src")
            if image_source:
                self.image_sources.append(image_source)
            return

        if tag in {"br", "hr"}:
            self._append_newline()
            return

        if tag in self._BLOCK_TAGS:
            self._append_newline()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self._append_newline()

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        """Return the extracted text content."""
        return "".join(self._parts)

    def _append_newline(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")


def load_apkg_file(path: str | Path) -> dict:
    """Load flashcard decks from an APKG package."""
    package_path = Path(path)

    with zipfile.ZipFile(package_path) as archive:
        collection_member = _find_collection_member(archive)
        media_lookup = _load_media_lookup(archive)

        with tempfile.TemporaryDirectory() as temp_dir:
            collection_path = Path(temp_dir) / collection_member
            collection_path.write_bytes(archive.read(collection_member))

            connection = sqlite3.connect(collection_path)
            connection.row_factory = sqlite3.Row
            try:
                return _load_decks_from_collection(connection, archive, media_lookup)
            finally:
                connection.close()


def save_apkg_file(path: str | Path, deck_data: dict) -> Path:
    """Write a flashcard deck to an `.apkg` package."""
    package_path = Path(path)
    if package_path.suffix != ".apkg":
        package_path = package_path.with_suffix(".apkg")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        collection_path = temp_root / "collection.anki2"
        id_base = _generate_anki_id()
        deck_id = id_base
        model_id = id_base + 1
        row_id_base = id_base + 100
        created_timestamp = int(time.time())
        created_millis = int(time.time() * 1000)

        media_manifest, media_entries = _write_collection_database(
            collection_path=collection_path,
            temp_root=temp_root,
            deck_data=deck_data,
            deck_id=deck_id,
            model_id=model_id,
            row_id_base=row_id_base,
            created_timestamp=created_timestamp,
            created_millis=created_millis,
        )

        with zipfile.ZipFile(
            package_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.write(collection_path, "collection.anki2")
            archive.writestr(
                "media",
                json.dumps(media_manifest, ensure_ascii=False, sort_keys=True),
            )

            for entry in media_entries:
                archive.write(entry["path"], entry["archive_name"])

    return package_path


def _find_collection_member(archive: zipfile.ZipFile) -> str:
    """Return the collection DB filename inside an APKG archive."""
    names = set(archive.namelist())
    for collection_name in ANKI_COLLECTION_FILES:
        if collection_name in names:
            return collection_name

    raise ValueError(_("APKG file does not contain a supported Anki collection."))


def _load_media_lookup(archive: zipfile.ZipFile) -> dict[str, tuple[str, str]]:
    """Return candidate media filenames mapped to zip members."""
    try:
        raw_manifest = archive.read("media")
    except KeyError:
        return {}

    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(_("APKG media manifest is invalid.")) from exc

    if not isinstance(manifest, dict):
        raise ValueError(_("APKG media manifest is invalid."))

    lookup: dict[str, tuple[str, str]] = {}
    for archive_name, original_name in manifest.items():
        if not isinstance(archive_name, str) or not isinstance(original_name, str):
            continue

        candidates = {
            original_name,
            unquote(original_name),
            PurePosixPath(original_name).name,
            PurePosixPath(unquote(original_name)).name,
        }
        for candidate in candidates:
            if candidate:
                lookup[candidate] = (archive_name, original_name)

    return lookup


def _load_decks_from_collection(
    connection: sqlite3.Connection,
    archive: zipfile.ZipFile,
    media_lookup: dict[str, tuple[str, str]],
) -> dict:
    """Build normalized flashcard decks from an Anki collection DB."""
    metadata = connection.execute("SELECT models, decks FROM col LIMIT 1").fetchone()
    if metadata is None:
        raise ValueError(_("APKG file does not contain collection metadata."))

    models = _parse_json_column(metadata["models"], _("APKG note models are invalid."))
    decks = _parse_json_column(metadata["decks"], _("APKG deck metadata is invalid."))

    rows = connection.execute(
        """
        SELECT n.id AS note_id, n.mid, n.flds, c.did
        FROM notes AS n
        JOIN cards AS c ON c.nid = n.id
        ORDER BY c.did, n.id, c.ord
        """
    ).fetchall()

    imported_decks: dict[int, dict] = {}
    imported_note_pairs: set[tuple[int, int]] = set()
    skipped_card_count = 0

    for row in rows:
        deck_note_key = (int(row["did"]), int(row["note_id"]))
        if deck_note_key in imported_note_pairs:
            continue

        imported_note_pairs.add(deck_note_key)
        model = models.get(str(row["mid"])) or models.get(row["mid"])
        if not isinstance(model, dict) or int(model.get("type", 0)) == 1:
            skipped_card_count += 1
            continue

        fields = str(row["flds"] or "").split(FIELD_SEPARATOR)
        if len(fields) < 2:
            skipped_card_count += 1
            continue

        card_payload = _build_flashcard_card(
            term_html=fields[0],
            definition_html=fields[1],
            archive=archive,
            media_lookup=media_lookup,
        )
        if not _card_has_visible_content(card_payload):
            skipped_card_count += 1
            continue

        deck_id = int(row["did"])
        deck_payload = imported_decks.setdefault(
            deck_id,
            {
                "title": _resolve_deck_title(decks, deck_id),
                "cards": [],
            },
        )
        deck_payload["cards"].append(card_payload)

    supported_decks = [
        deck_payload
        for deck_payload in imported_decks.values()
        if deck_payload["cards"]
    ]
    if not supported_decks:
        raise ValueError(_("No supported flashcards were found in the APKG file."))

    return {
        "decks": supported_decks,
        "skipped_card_count": skipped_card_count,
    }


def _build_flashcard_card(
    *,
    term_html: str,
    definition_html: str,
    archive: zipfile.ZipFile,
    media_lookup: dict[str, tuple[str, str]],
) -> dict:
    """Convert two Anki fields into one normalized flashcard card."""
    term_text, term_image = _parse_field_content(term_html, archive, media_lookup)
    definition_text, definition_image = _parse_field_content(
        definition_html,
        archive,
        media_lookup,
    )

    card_payload = {
        "term_text": term_text,
        "definition_text": definition_text,
    }
    if term_image is not None:
        card_payload["term_image"] = term_image
    if definition_image is not None:
        card_payload["definition_image"] = definition_image

    return card_payload


def _parse_field_content(
    field_html: str,
    archive: zipfile.ZipFile,
    media_lookup: dict[str, tuple[str, str]],
) -> tuple[str, dict | None]:
    """Extract printable text and one optional image from a field."""
    parser = _FlashcardFieldParser()
    parser.feed(str(field_html or ""))
    parser.close()

    normalized_text = _normalize_field_text(parser.get_text())
    image_payload = None

    for image_source in parser.image_sources:
        image_payload = _load_field_image(image_source, archive, media_lookup)
        if image_payload is not None:
            break

    return normalized_text, image_payload


def _normalize_field_text(text: str) -> str:
    """Normalize extracted HTML text to plain display text."""
    without_sound = SOUND_TAG_PATTERN.sub("", text.replace("\r", ""))
    normalized_lines = []

    for raw_line in without_sound.split("\n"):
        line = " ".join(raw_line.split()).strip()
        if line:
            normalized_lines.append(line)

    return "\n".join(normalized_lines)


def _load_field_image(
    source: str,
    archive: zipfile.ZipFile,
    media_lookup: dict[str, tuple[str, str]],
) -> dict | None:
    """Resolve an image reference from the APKG media map."""
    lookup_entry = _resolve_media_entry(source, media_lookup)
    if lookup_entry is None:
        return None

    archive_name, original_name = lookup_entry
    try:
        image_bytes = archive.read(archive_name)
    except KeyError:
        return None

    media_type = _guess_image_media_type(original_name, image_bytes)
    if media_type is None:
        return None

    return {
        "filename": PurePosixPath(original_name).name or "image",
        "media_type": media_type,
        "data": base64.b64encode(image_bytes).decode("ascii"),
    }


def _resolve_media_entry(
    source: str,
    media_lookup: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    """Find a manifest entry for a field image source."""
    source_candidates = {
        source,
        unquote(source),
        PurePosixPath(source).name,
        PurePosixPath(unquote(source)).name,
    }

    for candidate in source_candidates:
        if candidate in media_lookup:
            return media_lookup[candidate]

    return None


def _parse_json_column(raw_value: object, error_message: str) -> dict:
    """Parse a JSON text column from the Anki collection DB."""
    if not isinstance(raw_value, str):
        raise ValueError(error_message)

    try:
        parsed_value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(error_message) from exc

    if not isinstance(parsed_value, dict):
        raise ValueError(error_message)

    return parsed_value


def _resolve_deck_title(decks: dict, deck_id: int) -> str:
    """Return a human-friendly deck title from the collection metadata."""
    deck = decks.get(str(deck_id)) or decks.get(deck_id)
    if isinstance(deck, dict):
        title = str(deck.get("name") or "").strip()
        if title:
            return title

    return _("Imported Flashcards")


def _card_has_visible_content(card_payload: dict) -> bool:
    """Return True when the card has content on both study sides."""
    return (
        bool(card_payload["term_text"] or card_payload.get("term_image"))
        and bool(card_payload["definition_text"] or card_payload.get("definition_image"))
    )


def _write_collection_database(
    *,
    collection_path: Path,
    temp_root: Path,
    deck_data: dict,
    deck_id: int,
    model_id: int,
    row_id_base: int,
    created_timestamp: int,
    created_millis: int,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Create the SQLite collection and media files for APKG export."""
    media_manifest: dict[str, str] = {}
    media_entries: list[dict[str, str]] = []

    connection = sqlite3.connect(collection_path)
    try:
        _initialize_anki_schema(connection)
        _insert_collection_row(
            connection=connection,
            deck_title=str(deck_data["title"]).strip() or _("Flashcards"),
            deck_id=deck_id,
            model_id=model_id,
            card_count=len(deck_data["cards"]),
            created_timestamp=created_timestamp,
            created_millis=created_millis,
        )
        _insert_deck_cards(
            connection=connection,
            temp_root=temp_root,
            deck_data=deck_data,
            deck_id=deck_id,
            model_id=model_id,
            row_id_base=row_id_base,
            created_timestamp=created_timestamp,
            media_manifest=media_manifest,
            media_entries=media_entries,
        )
        connection.commit()
    finally:
        connection.close()

    return media_manifest, media_entries


def _initialize_anki_schema(connection: sqlite3.Connection) -> None:
    """Create the minimal collection schema Anki expects in a package."""
    connection.executescript(
        """
        CREATE TABLE col (
            id integer primary key,
            crt integer not null,
            mod integer not null,
            scm integer not null,
            ver integer not null,
            dty integer not null,
            usn integer not null,
            ls integer not null,
            conf text not null,
            models text not null,
            decks text not null,
            dconf text not null,
            tags text not null
        );
        CREATE TABLE notes (
            id integer primary key,
            guid text not null,
            mid integer not null,
            mod integer not null,
            usn integer not null,
            tags text not null,
            flds text not null,
            sfld integer not null,
            csum integer not null,
            flags integer not null,
            data text not null
        );
        CREATE TABLE cards (
            id integer primary key,
            nid integer not null,
            did integer not null,
            ord integer not null,
            mod integer not null,
            usn integer not null,
            type integer not null,
            queue integer not null,
            due integer not null,
            ivl integer not null,
            factor integer not null,
            reps integer not null,
            lapses integer not null,
            left integer not null,
            odue integer not null,
            odid integer not null,
            flags integer not null,
            data text not null
        );
        CREATE TABLE revlog (
            id integer primary key,
            cid integer not null,
            usn integer not null,
            ease integer not null,
            ivl integer not null,
            lastIvl integer not null,
            factor integer not null,
            time integer not null,
            type integer not null
        );
        CREATE TABLE graves (
            usn integer not null,
            oid integer not null,
            type integer not null
        );
        CREATE INDEX ix_notes_usn ON notes (usn);
        CREATE INDEX ix_cards_usn ON cards (usn);
        CREATE INDEX ix_revlog_usn ON revlog (usn);
        CREATE INDEX ix_cards_nid ON cards (nid);
        CREATE INDEX ix_cards_sched ON cards (did, queue, due);
        CREATE INDEX ix_revlog_cid ON revlog (cid);
        """
    )


def _insert_collection_row(
    *,
    connection: sqlite3.Connection,
    deck_title: str,
    deck_id: int,
    model_id: int,
    card_count: int,
    created_timestamp: int,
    created_millis: int,
) -> None:
    """Insert the single collection metadata row."""
    models = {
        str(model_id): {
            "css": ANKI_MODEL_CSS,
            "did": deck_id,
            "flds": [
                {
                    "font": "Arial",
                    "media": [],
                    "name": "Front",
                    "ord": 0,
                    "rtl": False,
                    "size": 20,
                    "sticky": False,
                },
                {
                    "font": "Arial",
                    "media": [],
                    "name": "Back",
                    "ord": 1,
                    "rtl": False,
                    "size": 20,
                    "sticky": False,
                },
            ],
            "id": model_id,
            "latexPost": "\\end{document}",
            "latexPre": (
                "\\documentclass[12pt]{article}\n"
                "\\special{papersize=3in,5in}\n"
                "\\usepackage[utf8]{inputenc}\n"
                "\\usepackage{amssymb,amsmath}\n"
                "\\pagestyle{empty}\n"
                "\\setlength{\\parindent}{0in}\n"
                "\\begin{document}"
            ),
            "mod": created_millis,
            "name": "Quizbite Basic",
            "req": [[0, "all", [0, 1]]],
            "sortf": 0,
            "tags": [],
            "tmpls": [
                {
                    "afmt": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}",
                    "bafmt": "",
                    "bqfmt": "",
                    "did": None,
                    "name": "Card 1",
                    "ord": 0,
                    "qfmt": "{{Front}}",
                }
            ],
            "type": 0,
            "usn": -1,
            "vers": [],
        }
    }
    decks = {
        str(deck_id): {
            "collapsed": False,
            "conf": 1,
            "desc": "",
            "dyn": 0,
            "extendNew": 0,
            "extendRev": 0,
            "id": deck_id,
            "lrnToday": [0, 0],
            "mod": created_millis,
            "name": deck_title,
            "newToday": [0, 0],
            "revToday": [0, 0],
            "timeToday": [0, 0],
            "usn": -1,
        }
    }
    conf = {
        "activeDecks": [deck_id],
        "addToCur": True,
        "curDeck": deck_id,
        "curModel": model_id,
        "dueCounts": True,
        "estTimes": True,
        "newBury": True,
        "nextPos": max(card_count, 1) + 1,
        "sortBackwards": False,
        "timeLim": 0,
    }
    dconf = {
        "1": {
            "autoplay": True,
            "dyn": False,
            "id": 1,
            "lapse": {
                "delays": [10],
                "leechAction": 0,
                "leechFails": 8,
                "minInt": 1,
                "mult": 0,
            },
            "maxTaken": 60,
            "mod": created_millis,
            "name": "Default",
            "new": {
                "bury": True,
                "delays": [1, 10],
                "initialFactor": 2500,
                "ints": [1, 4, 7],
                "order": 0,
                "perDay": 20,
                "separate": True,
            },
            "replayq": True,
            "rev": {
                "bury": True,
                "ease4": 1.3,
                "fuzz": 0.05,
                "ivlFct": 1,
                "maxIvl": 36500,
                "perDay": 200,
            },
            "timer": 0,
            "usn": -1,
        }
    }

    connection.execute(
        """
        INSERT INTO col (
            id, crt, mod, scm, ver, dty, usn, ls, conf, models, decks, dconf, tags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            int(created_timestamp / 86400),
            created_millis,
            created_millis,
            ANKI_SCHEMA_VERSION,
            0,
            -1,
            0,
            json.dumps(conf, ensure_ascii=False, separators=(",", ":")),
            json.dumps(models, ensure_ascii=False, separators=(",", ":")),
            json.dumps(decks, ensure_ascii=False, separators=(",", ":")),
            json.dumps(dconf, ensure_ascii=False, separators=(",", ":")),
            json.dumps({}, separators=(",", ":")),
        ),
    )


def _insert_deck_cards(
    *,
    connection: sqlite3.Connection,
    temp_root: Path,
    deck_data: dict,
    deck_id: int,
    model_id: int,
    row_id_base: int,
    created_timestamp: int,
    media_manifest: dict[str, str],
    media_entries: list[dict[str, str]],
) -> None:
    """Insert notes/cards and materialize media files for a deck."""
    media_counter = 0

    for card_index, card in enumerate(deck_data["cards"], start=1):
        front_field, media_counter = _build_anki_field_html(
            temp_root=temp_root,
            text=card.get("term_text") or "",
            image_payload=card.get("term_image"),
            media_counter=media_counter,
            media_manifest=media_manifest,
            media_entries=media_entries,
        )
        back_field, media_counter = _build_anki_field_html(
            temp_root=temp_root,
            text=card.get("definition_text") or "",
            image_payload=card.get("definition_image"),
            media_counter=media_counter,
            media_manifest=media_manifest,
            media_entries=media_entries,
        )

        sort_field = (card.get("term_text") or "").strip()
        if not sort_field:
            sort_field = _("Flashcard Image") if card.get("term_image") else _("Flashcard")

        note_id = row_id_base + card_index * 2
        card_id = row_id_base + card_index * 2 + 1
        fields = FIELD_SEPARATOR.join([front_field, back_field])

        connection.execute(
            """
            INSERT INTO notes (
                id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                _create_guid(),
                model_id,
                created_timestamp,
                -1,
                "",
                fields,
                sort_field,
                _anki_checksum(sort_field),
                0,
                "",
            ),
        )
        connection.execute(
            """
            INSERT INTO cards (
                id, nid, did, ord, mod, usn, type, queue, due, ivl, factor,
                reps, lapses, left, odue, odid, flags, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                note_id,
                deck_id,
                0,
                created_timestamp,
                -1,
                0,
                0,
                card_index,
                0,
                2500,
                0,
                0,
                0,
                0,
                0,
                0,
                "",
            ),
        )


def _build_anki_field_html(
    *,
    temp_root: Path,
    text: str,
    image_payload: dict | None,
    media_counter: int,
    media_manifest: dict[str, str],
    media_entries: list[dict[str, str]],
) -> tuple[str, int]:
    """Build Anki HTML for one side of a flashcard and materialize media."""
    html_parts = []

    normalized_text = (text or "").strip()
    if normalized_text:
        html_parts.append(escape(normalized_text).replace("\n", "<br>"))

    if image_payload is not None:
        media_filename, media_counter = _register_media_file(
            temp_root=temp_root,
            image_payload=image_payload,
            media_counter=media_counter,
            media_manifest=media_manifest,
            media_entries=media_entries,
        )
        if html_parts:
            html_parts.append("<br>")
        html_parts.append(
            '<img src="{filename}">'.format(
                filename=escape(media_filename, quote=True)
            )
        )

    return "".join(html_parts), media_counter


def _register_media_file(
    *,
    temp_root: Path,
    image_payload: dict,
    media_counter: int,
    media_manifest: dict[str, str],
    media_entries: list[dict[str, str]],
) -> tuple[str, int]:
    """Decode one image and register it for APKG export."""
    image_bytes = base64.b64decode(image_payload["data"])
    extension = _file_extension_for_media_type(
        image_payload.get("media_type") or "image/png"
    )
    original_filename = _unique_media_filename(
        filename=image_payload.get("filename") or f"image{extension}",
        media_counter=media_counter,
        extension=extension,
    )
    archive_name = str(media_counter)
    output_path = temp_root / archive_name
    output_path.write_bytes(image_bytes)

    media_manifest[archive_name] = original_filename
    media_entries.append(
        {
            "archive_name": archive_name,
            "path": str(output_path),
        }
    )
    return original_filename, media_counter + 1


def _unique_media_filename(filename: str, media_counter: int, extension: str) -> str:
    """Return a deterministic safe media filename for exported HTML."""
    candidate = PurePosixPath(filename).name.strip()
    if not candidate:
        candidate = f"quizbite-media-{media_counter}{extension}"

    stem = Path(candidate).stem.strip() or f"quizbite-media-{media_counter}"
    suffix = Path(candidate).suffix.strip() or extension
    return f"{stem}-{media_counter}{suffix}"


def _file_extension_for_media_type(media_type: str) -> str:
    """Return a sensible file extension for an image media type."""
    guessed_extension = mimetypes.guess_extension(media_type, strict=False)
    if guessed_extension:
        return guessed_extension

    fallback_extensions = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    return fallback_extensions.get(media_type, ".img")


def _guess_image_media_type(filename: str, image_bytes: bytes) -> str | None:
    """Infer an image MIME type from filename or bytes."""
    guessed_type, _encoding = mimetypes.guess_type(filename, strict=False)
    if guessed_type and guessed_type.startswith("image/"):
        return guessed_type

    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.lstrip().startswith(b"<svg"):
        return "image/svg+xml"

    return None


def _create_guid() -> str:
    """Create a stable-enough GUID value for Anki notes."""
    return uuid.uuid4().hex[:10]


def _generate_anki_id(*, offset: int = 0) -> int:
    """Generate a millisecond-based integer id for Anki rows."""
    return int(time.time() * 1000) + offset


def _anki_checksum(text: str) -> int:
    """Return the standard Anki note checksum for the sort field."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
