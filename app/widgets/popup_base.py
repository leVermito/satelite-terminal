"""Base classes for popup widgets."""

from textual.app import ComposeResult
from textual.widgets import Static, Label

from .messages import PopupClosed


class PopupBase(Static):
    """Base class for all popup/overlay widgets.

    Provides:
    - can_focus for receiving key events
    - compose() generating ROW_COUNT Label rows
    - _update_labels(lines) to write into pre-allocated Labels
    - _render_content() hook (subclass override)
    - on_key() base: checks display, handles CLOSE_KEY
    - / search filtering (subclasses override _get_search_text)
    """

    ROW_COUNT: int = 12
    CLOSE_KEY: str = ""  # Override per widget, e.g. "d", "g", "p"
    POPUP_NAME: str = ""  # Override per widget for PopupClosed message
    ROW_ID_PREFIX: str = "popup_row"
    ROW_CSS_CLASS: str = "popup-row"
    ESC_CLOSES: bool = True  # Whether ESC closes this popup

    can_focus = True

    _search_active: bool = False
    _search_query: str = ""

    DEFAULT_CSS = """
    .popup-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def compose(self) -> ComposeResult:
        for i in range(self.ROW_COUNT):
            yield Label("", id=f"{self.ROW_ID_PREFIX}_{i}", classes=self.ROW_CSS_CLASS)

    def _update_labels(self, lines: list[str]) -> None:
        if not self.is_mounted:
            return
        while len(lines) < self.ROW_COUNT:
            lines.append("")
        for i in range(self.ROW_COUNT):
            try:
                label = self.query_one(f"#{self.ROW_ID_PREFIX}_{i}", Label)
                if i < len(lines) and lines[i]:
                    label.display = True
                    label.update(lines[i])
                else:
                    label.display = False
            except Exception:
                pass

    def _render_content(self) -> None:
        """Override in subclass to render popup content."""
        pass

    def request_close(self) -> None:
        self.display = False
        self.post_message(PopupClosed(self.POPUP_NAME))

    def _get_search_text(self, index: int) -> str:
        """Override in subclass: return searchable text for item at index."""
        return ""

    def _match_search(self, text: str) -> bool:
        if not self._search_query:
            return True
        return self._search_query.lower() in text.lower()

    def _search_allowed(self) -> bool:
        """Override to gate when search can activate (e.g. only in list mode)."""
        return True

    def _render_search_bar(self) -> str:
        if self._search_active:
            return f"[dim]search:[/dim] {self._search_query}_"
        if self._search_query:
            return f"[dim]/:search[/dim] [yellow]filter: {self._search_query}[/yellow]"
        return "[dim]/:search[/dim]"

    def on_key(self, event) -> None:
        if not self.display:
            return

        key = event.key

        # Search mode intercepts all keys
        if self._search_active:
            if key == "escape":
                self._search_active = False
                self._search_query = ""
            elif key == "enter":
                self._search_active = False
            elif key == "backspace":
                if self._search_query:
                    self._search_query = self._search_query[:-1]
                else:
                    self._search_active = False
            elif key == "space":
                self._search_query += " "
            elif key == "minus":
                self._search_query += "-"
            elif key in ("period", "full_stop"):
                self._search_query += "."
            elif key == "number_sign":
                self._search_query += "#"
            elif key == "slash":
                self._search_query += "/"
            elif len(key) == 1 and key.isprintable():
                self._search_query += key
            self._render_content()
            event.stop()
            event.prevent_default()
            return

        if self.CLOSE_KEY and key == self.CLOSE_KEY:
            self.request_close()
            event.stop()
            event.prevent_default()
            return

        if self.ESC_CLOSES and key == "escape":
            self.request_close()
            event.stop()
            event.prevent_default()
            return

        # Activate search on /
        if key == "slash" and self._search_allowed():
            self._search_active = True
            self._render_content()
            event.stop()
            event.prevent_default()
            return

        # Subclasses extend from here via _handle_key
        self._handle_key(event)

    def _handle_key(self, event) -> None:
        """Override in subclass for widget-specific key handling."""
        pass


class CrudPopupBase(PopupBase):
    """Base for popups with list/edit-or-add/delete_confirm modes.

    Provides shared:
    - _mode state machine
    - _selected_index
    - _delete_target_name
    - move_selection() for list mode
    - delete confirm rendering and Y/N key handling
    """

    ESC_CLOSES = False  # Subclasses handle ESC per mode

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mode = "list"
        self._selected_index = 0
        self._delete_target_name = ""
        self._filtered_indices: list[int] | None = None

    def _search_allowed(self) -> bool:
        return self._mode == "list"

    def _get_item_count(self) -> int:
        """Override: return number of items in list mode."""
        return 0

    def move_selection(self, direction: int) -> None:
        if self._filtered_indices is not None:
            if not self._filtered_indices:
                return
            try:
                pos = self._filtered_indices.index(self._selected_index)
            except ValueError:
                pos = 0
            pos = (pos + direction) % len(self._filtered_indices)
            self._selected_index = self._filtered_indices[pos]
        else:
            count = self._get_item_count()
            if count == 0:
                return
            self._selected_index = (self._selected_index + direction) % count
        self._render_content()

    def start_delete_confirm(self) -> None:
        """Override to set _delete_target_name then call super."""
        pass

    def confirm_delete(self) -> None:
        """Override to perform actual deletion."""
        pass

    def cancel_delete(self) -> None:
        self._mode = "list"
        self._render_content()

    def _render_delete_confirm(self, entity_label: str = "Remove") -> None:
        lines = []
        lines.append("")
        lines.append("")
        lines.append(f"  {entity_label}: [red]{self._delete_target_name}[/red]?")
        lines.append("")
        lines.append("  [green]Y[/green] - Yes")
        lines.append("  [red]N[/red] - No, cancel")
        lines.append("")
        self._update_labels(lines)

    def _handle_key(self, event) -> None:
        key = event.key

        if self._mode == "delete_confirm":
            if key == "y":
                self.confirm_delete()
                event.stop()
                event.prevent_default()
                return
            elif key == "n" or key == "escape":
                self.cancel_delete()
                event.stop()
                event.prevent_default()
                return
            # Block all other keys in delete confirm
            event.stop()
            event.prevent_default()
            return

        # Delegate to subclass for list/edit/add mode handling
        self._handle_mode_key(event)

    def _handle_mode_key(self, event) -> None:
        """Override in subclass for mode-specific key handling."""
        pass
