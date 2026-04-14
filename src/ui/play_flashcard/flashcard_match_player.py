"""Flashcard match-mode player."""

from __future__ import annotations

import base64
import random
from dataclasses import dataclass
from functools import partial
from gettext import gettext as _

from gi.repository import Adw, Gdk, GLib, Gtk

from .flashcard_quiz_builder import SIDE_DEFINITION, SIDE_TERM
from ..play_quiz.score_view import build_completion_page

MATCH_CARD_CSS = """
.match-card-button {
  padding: 0;
  min-width: 148px;
  min-height: 112px;
}

.match-card-surface {
  border-radius: 16px;
  border: 1px solid rgba(32, 32, 32, 0.16);
  background: rgba(32, 32, 32, 0.04);
}

.match-card-selected .match-card-surface {
  border-color: rgba(28, 113, 216, 0.95);
  background: rgba(28, 113, 216, 0.12);
}

.match-card-matched .match-card-surface {
  border-color: rgba(46, 194, 126, 0.92);
  background: rgba(46, 194, 126, 0.12);
}

.match-card-wrong .match-card-surface {
  border-color: rgba(192, 28, 40, 0.92);
  background: rgba(192, 28, 40, 0.12);
}

.match-card-picture {
  border-radius: 12px;
}
""".strip()

NEXT_BATCH_DELAY_MS = 320
COMPACT_PAIRS_PER_SCREEN = 4
DEFAULT_PAIRS_PER_SCREEN = 6
WIDE_PAIRS_PER_SCREEN = 8


@dataclass(slots=True)
class MatchCardItem:
    """One visible button in the match grid."""

    pair_id: int
    role: str
    side: str
    text: str
    image: dict | None
    button: Gtk.Button
    matched: bool = False


class FlashcardMatchPlayer:
    """Controls match mode inside the shared navigation view."""

    _css_provider: Gtk.CssProvider | None = None
    _css_installed = False

    def __init__(self, navigation_view: Adw.NavigationView):
        """Create a match player bound to a navigation view."""
        self.navigation_view = navigation_view
        self.match_page: Adw.NavigationPage | None = None
        self.progress_bar: Gtk.ProgressBar | None = None
        self.batch_label: Gtk.Label | None = None
        self.flow_box: Gtk.FlowBox | None = None
        self.deck_data: dict | None = None
        self.prompt_side: str = SIDE_TERM
        self.card_batches: list[list[tuple[int, dict]]] = []
        self.current_batch_index = 0
        self.current_batch_pairs = 0
        self.items: list[MatchCardItem] = []
        self.selected_item: MatchCardItem | None = None
        self.matched_pairs = 0
        self._selection_locked = False
        self._advancing_batch = False

    def open_deck(self, deck_data: dict, prompt_side: str) -> None:
        """Start a new match session for a deck."""
        self._ensure_css()
        self._return_to_root_page()
        self._reset_state()

        self.deck_data = deck_data
        self.prompt_side = prompt_side
        self.card_batches = self._build_card_batches(deck_data)
        self.match_page = Adw.NavigationPage.new(
            self._build_match_shell(deck_data, prompt_side),
            _("{title} (Match Mode)").format(title=deck_data["title"]),
        )
        self.navigation_view.push(self.match_page)
        self._render_current_batch()

    def _ensure_css(self) -> None:
        """Install the match-card CSS once per process."""
        if FlashcardMatchPlayer._css_installed:
            return

        display = self.navigation_view.get_display()
        if display is None:
            return

        provider = Gtk.CssProvider()
        provider.load_from_string(MATCH_CARD_CSS)
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        FlashcardMatchPlayer._css_provider = provider
        FlashcardMatchPlayer._css_installed = True

    def _build_match_shell(
        self,
        deck_data: dict,
        prompt_side: str,
    ) -> Adw.ToolbarView:
        """Build the page shell for match mode."""
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=14,
            margin_bottom=14,
            margin_start=16,
            margin_end=16,
            vexpand=True,
        )

        self.batch_label = Gtk.Label(xalign=0)
        self.batch_label.add_css_class("caption")
        content_box.append(self.batch_label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        content_box.append(self.progress_bar)

        self.flow_box = Gtk.FlowBox()
        self.flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow_box.set_activate_on_single_click(False)
        self.flow_box.set_column_spacing(10)
        self.flow_box.set_row_spacing(10)
        self.flow_box.set_min_children_per_line(4)
        self.flow_box.set_max_children_per_line(4)
        self.flow_box.set_homogeneous(True)
        self.flow_box.set_valign(Gtk.Align.FILL)
        self.flow_box.set_vexpand(True)
        content_box.append(self.flow_box)

        toolbar_view.set_content(content_box)
        self._update_progress()
        return toolbar_view

    def _build_card_batches(self, deck_data: dict) -> list[list[tuple[int, dict]]]:
        """Split a deck into fixed-size match screens."""
        pairs_per_screen = self._determine_pairs_per_screen()
        indexed_cards = list(enumerate(deck_data["cards"], start=1))
        return [
            indexed_cards[start_index : start_index + pairs_per_screen]
            for start_index in range(0, len(indexed_cards), pairs_per_screen)
        ]

    def _determine_pairs_per_screen(self) -> int:
        """Choose how many pairs to show on one screen."""
        root = self.navigation_view.get_root()
        if not isinstance(root, Gtk.Widget):
            return DEFAULT_PAIRS_PER_SCREEN

        width = root.get_width() or 800
        height = root.get_height() or 600

        if width >= 1180 and height >= 760:
            return WIDE_PAIRS_PER_SCREEN
        if width <= 760 or height <= 620:
            return COMPACT_PAIRS_PER_SCREEN
        return DEFAULT_PAIRS_PER_SCREEN

    def _render_current_batch(self) -> None:
        """Render the current batch of pairs into the visible grid."""
        if self.flow_box is None or self.deck_data is None:
            return

        self._clear_flow_box()
        self.items.clear()
        self.selected_item = None
        self._selection_locked = False
        self._advancing_batch = False
        current_batch = self.card_batches[self.current_batch_index]
        self.current_batch_pairs = 0

        self.items = self._build_match_items(current_batch, self.prompt_side)
        for item in self.items:
            self.flow_box.insert(item.button, -1)

        if self.batch_label is not None:
            self.batch_label.set_label(
                _("Screen {current} of {total}").format(
                    current=self.current_batch_index + 1,
                    total=len(self.card_batches),
                )
            )

        self._update_progress()

    def _clear_flow_box(self) -> None:
        """Remove all existing children from the flow box."""
        if self.flow_box is None:
            return

        flow_child = self.flow_box.get_child_at_index(0)
        while flow_child is not None:
            child = flow_child.get_child()
            if child is not None:
                self.flow_box.remove(child)
            flow_child = self.flow_box.get_child_at_index(0)

    def _build_match_items(
        self,
        batch_cards: list[tuple[int, dict]],
        prompt_side: str,
    ) -> list[MatchCardItem]:
        """Create shuffled match-card items for one batch."""
        answer_side = SIDE_DEFINITION if prompt_side == SIDE_TERM else SIDE_TERM
        items = []

        for pair_id, card in batch_cards:
            items.append(
                self._create_match_item(
                    pair_id=pair_id,
                    role="prompt",
                    side=prompt_side,
                    text=(card.get(f"{prompt_side}_text") or "").strip(),
                    image=card.get(f"{prompt_side}_image"),
                )
            )
            items.append(
                self._create_match_item(
                    pair_id=pair_id,
                    role="answer",
                    side=answer_side,
                    text=(card.get(f"{answer_side}_text") or "").strip(),
                    image=card.get(f"{answer_side}_image"),
                )
            )

        random.shuffle(items)
        return items

    def _create_match_item(
        self,
        *,
        pair_id: int,
        role: str,
        side: str,
        text: str,
        image: dict | None,
    ) -> MatchCardItem:
        """Build one clickable match card button."""
        button = Gtk.Button()
        button.add_css_class("flat")
        button.add_css_class("match-card-button")
        item = MatchCardItem(
            pair_id=pair_id,
            role=role,
            side=side,
            text=text,
            image=image,
            button=button,
        )
        button.set_child(self._build_item_child(item))
        button.connect("clicked", self.on_match_item_clicked, item)
        return item

    def _build_item_child(self, item: MatchCardItem) -> Gtk.Widget:
        """Build the visible content inside a match card."""
        surface = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
            vexpand=True,
        )
        surface.add_css_class("match-card-surface")
        surface.set_valign(Gtk.Align.FILL)

        side_label = Gtk.Label(
            label=_("Term") if item.side == SIDE_TERM else _("Definition"),
            xalign=0,
        )
        side_label.add_css_class("caption")
        surface.append(side_label)

        if item.image is not None:
            picture = self._build_item_picture(item.image)
            if picture is not None:
                surface.append(picture)

        label_text = item.text or (
            _("Image")
            if item.image is not None
            else (_("Empty Term") if item.side == SIDE_TERM else _("Empty Definition"))
        )
        content_label = Gtk.Label(label=label_text, wrap=True, xalign=0, yalign=0)
        content_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        content_label.add_css_class("body")
        content_label.set_vexpand(True)
        content_label.set_max_width_chars(22)
        surface.append(content_label)

        return surface

    def _build_item_picture(self, image_payload: dict) -> Gtk.Picture | None:
        """Decode a base64 image into a small preview picture."""
        try:
            texture = Gdk.Texture.new_from_bytes(
                GLib.Bytes.new(base64.b64decode(image_payload["data"]))
            )
        except (GLib.Error, ValueError, TypeError):
            return None

        picture = Gtk.Picture.new_for_paintable(texture)
        picture.add_css_class("match-card-picture")
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.set_size_request(-1, 72)
        return picture

    def on_match_item_clicked(self, _button, item: MatchCardItem) -> None:
        """Handle a card selection inside the match grid."""
        if self._selection_locked or self._advancing_batch or item.matched:
            return

        if self.selected_item is item:
            self._set_item_selected(item, False)
            self.selected_item = None
            return

        if self.selected_item is None:
            self._set_item_selected(item, True)
            self.selected_item = item
            return

        previous_item = self.selected_item
        if item.role == previous_item.role:
            self._set_item_selected(previous_item, False)
            self._set_item_selected(item, True)
            self.selected_item = item
            return

        self._set_item_selected(item, True)
        if item.pair_id == previous_item.pair_id:
            self._mark_item_matched(previous_item)
            self._mark_item_matched(item)
            self.selected_item = None
            self.matched_pairs += 1
            self.current_batch_pairs += 1
            self._update_progress()
            self._maybe_advance_after_batch_completion()
            return

        self._selection_locked = True
        previous_item.button.add_css_class("match-card-wrong")
        item.button.add_css_class("match-card-wrong")
        GLib.timeout_add(
            220,
            self._clear_wrong_selection,
            previous_item,
            item,
        )

    def _clear_wrong_selection(
        self,
        first_item: MatchCardItem,
        second_item: MatchCardItem,
    ) -> bool:
        """Clear mismatch feedback after a short delay."""
        first_item.button.remove_css_class("match-card-wrong")
        second_item.button.remove_css_class("match-card-wrong")
        self._set_item_selected(first_item, False)
        self._set_item_selected(second_item, False)
        self.selected_item = None
        self._selection_locked = False
        return GLib.SOURCE_REMOVE

    def _mark_item_matched(self, item: MatchCardItem) -> None:
        """Persist the matched state for a card."""
        item.matched = True
        item.button.remove_css_class("match-card-selected")
        item.button.add_css_class("match-card-matched")
        item.button.set_sensitive(False)

    def _set_item_selected(self, item: MatchCardItem, is_selected: bool) -> None:
        """Toggle the selected CSS state for a card."""
        if item.matched:
            return

        if is_selected:
            item.button.add_css_class("match-card-selected")
        else:
            item.button.remove_css_class("match-card-selected")

    def _maybe_advance_after_batch_completion(self) -> None:
        """Advance to the next screen or finish when the current batch is done."""
        current_batch_size = len(self.card_batches[self.current_batch_index])
        if self.current_batch_pairs < current_batch_size:
            return

        self._selection_locked = True
        self._advancing_batch = True
        if self.current_batch_index == len(self.card_batches) - 1:
            GLib.timeout_add(NEXT_BATCH_DELAY_MS, self._finish_match_session)
            return

        GLib.timeout_add(NEXT_BATCH_DELAY_MS, self._advance_to_next_batch)

    def _advance_to_next_batch(self) -> bool:
        """Show the next screen of match pairs."""
        self.current_batch_index += 1
        self._render_current_batch()
        return GLib.SOURCE_REMOVE

    def _finish_match_session(self) -> bool:
        """Finish the session after the final screen is matched."""
        self._show_completion_page()
        return GLib.SOURCE_REMOVE

    def _update_progress(self) -> None:
        """Update the match progress bar."""
        if self.progress_bar is None or self.deck_data is None:
            return

        total_pairs = max(len(self.deck_data["cards"]), 1)
        self.progress_bar.set_fraction(self.matched_pairs / total_pairs)

    def _show_completion_page(self) -> None:
        """Show the completion page when all pairs are matched."""
        if self.deck_data is None:
            return

        completion_page = build_completion_page(
            title=_("Match Complete"),
            description=_("You matched all {count} flashcards.").format(
                count=len(self.deck_data["cards"])
            ),
            on_retry=partial(
                self.on_retry_clicked,
                deck_data=self.deck_data,
                prompt_side=self.prompt_side,
            ),
            on_go_home=self.on_go_home_clicked,
            retry_label=_("Play Again"),
        )
        self.navigation_view.push(completion_page)

    def on_retry_clicked(
        self,
        _button,
        *,
        deck_data: dict,
        prompt_side: str,
    ) -> None:
        """Restart the same match session."""
        self.open_deck(deck_data, prompt_side)

    def on_go_home_clicked(self, _button) -> None:
        """Return to the library and clear match state."""
        self._return_to_root_page()
        self._reset_state()

    def _reset_state(self) -> None:
        """Clear match-session state."""
        self.match_page = None
        self.progress_bar = None
        self.batch_label = None
        self.flow_box = None
        self.deck_data = None
        self.card_batches = []
        self.current_batch_index = 0
        self.current_batch_pairs = 0
        self.items = []
        self.selected_item = None
        self.matched_pairs = 0
        self._selection_locked = False
        self._advancing_batch = False

    def _get_root_page(self) -> Adw.NavigationPage | None:
        """Return the first page in the navigation stack."""
        navigation_stack = self.navigation_view.get_navigation_stack()
        if navigation_stack.get_n_items() == 0:
            return None

        page = navigation_stack.get_item(0)
        if not isinstance(page, Adw.NavigationPage):
            return None

        return page

    def _return_to_root_page(self) -> None:
        """Return the navigation stack to the library page."""
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
