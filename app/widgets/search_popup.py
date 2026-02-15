"""Search popup widget for satellite search."""

import numpy as np
from textual.app import ComposeResult
from textual.widgets import Static, Label
from config_manager import SATELLITE_TYPES
from satellite.propagator import propagate_batch

from .popup_base import PopupBase
from .messages import PopupClosed, CenterOnLocation, TrackSatellite, RestoreView


class SearchPopup(PopupBase):
    """Search popup for satellite search with live results."""

    CLOSE_KEY = ""  # No toggle-close key; ESC handled specially
    ESC_CLOSES = False  # cancel_search() handles ESC with view restoration
    POPUP_NAME = "search"
    ROW_COUNT = 7
    ROW_ID_PREFIX = "search_row"
    ROW_CSS_CLASS = "search-row"

    DEFAULT_CSS = """
    SearchPopup {
        layer: overlay;
        width: auto;
        height: auto;
        background: $surface;
        border: solid $primary;
        border-title-color: $primary;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .search-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, satellites, satellite_types_list):
        super().__init__()
        self.border_title = "SEARCH SATELLITE (Esc to close)"
        self.satellites = satellites
        self.satellite_types_list = satellite_types_list
        self.query = ""
        self.results = []
        self.selected_index = 0
        self.page_offset = 0  # For pagination
        self._saved_view = None
        self._time_provider = None  # Callable returning effective time
        self._globe_center_lat = 0.0
        self._globe_center_lon = 0.0
        self._globe_zoom = 1.0
        self._type_indices = None

    def compose(self) -> ComposeResult:
        yield Label("", id="search_row_0", classes="search-row")
        yield Label("", id="search_row_1", classes="search-row")
        yield Label("", id="search_row_2", classes="search-row")
        yield Label("", id="search_row_3", classes="search-row")
        yield Label("", id="search_row_4", classes="search-row")
        yield Label("", id="search_row_5", classes="search-row")
        yield Label("", id="search_row_6", classes="search-row")

    def set_globe_state(self, center_lat, center_lon, zoom, type_indices, time_provider):
        """Set globe state references for preview and save/restore."""
        self._globe_center_lat = center_lat
        self._globe_center_lon = center_lon
        self._globe_zoom = zoom
        self._type_indices = type_indices
        self._time_provider = time_provider

    def save_view(self):
        """Save current view state for Escape key."""
        self._saved_view = {
            'lat': self._globe_center_lat,
            'lon': self._globe_center_lon,
            'zoom': self._globe_zoom
        }

    def _search_satellites(self, query: str) -> list[tuple[int, dict, str]]:
        """Search satellites by name, return all matching results."""
        if not query:
            return []

        query_upper = query.upper()
        matches = []

        for i, sat in enumerate(self.satellites):
            name = sat.get('OBJECT_NAME', '').upper()
            if query_upper in name:
                sat_type = self.satellite_types_list[i] if i < len(self.satellite_types_list) else 'unknown'
                matches.append((i, sat, sat_type))

        return matches

    def handle_char(self, char: str):
        """Handle character input."""
        self.query += char
        self.results = self._search_satellites(self.query)
        self.selected_index = 0
        self.page_offset = 0
        self._update_preview()
        self._render_content()

    def handle_backspace(self):
        """Handle backspace."""
        if self.query:
            self.query = self.query[:-1]
            self.results = self._search_satellites(self.query)
            self.selected_index = 0
            self.page_offset = 0
            self._update_preview()
            self._render_content()

    def move_selection(self, direction: int):
        """Move selection up/down in results with pagination."""
        if not self.results:
            return

        self.selected_index = (self.selected_index + direction) % len(self.results)

        # Update page offset to keep selected item visible (5 items per page)
        items_per_page = 5
        target_page = self.selected_index // items_per_page
        self.page_offset = target_page * items_per_page

        self._update_preview()
        self._render_content()

    def _update_preview(self):
        """Update globe view to show selected satellite by posting CenterOnLocation."""
        if not self.results or self.selected_index >= len(self.results):
            return

        idx, sat, sat_type = self.results[self.selected_index]

        # Get satellite position
        now = self._time_provider() if self._time_provider else None
        if now is None:
            return
        results = propagate_batch(self.satellites, now, self._type_indices)

        if not np.isnan(results[idx, 0]):
            lat = results[idx, 0]
            lon = results[idx, 1]
            self.post_message(CenterOnLocation(lat, lon, 2.0))

    def confirm_selection(self):
        """Confirm selection and close popup (Enter key)."""
        self.request_close()
        return True

    def focus_selection(self):
        """Focus on selected satellite and start tracking (F key)."""
        if not self.results or self.selected_index >= len(self.results):
            return False

        idx, sat, sat_type = self.results[self.selected_index]
        name = sat.get('OBJECT_NAME', 'Unknown')
        self.post_message(TrackSatellite(idx, name, sat_type))
        self.request_close()
        return True

    def bookmark_selection(self):
        """Add selected satellite to favorites."""
        if not self.results or self.selected_index >= len(self.results):
            return False
        idx, sat, sat_type = self.results[self.selected_index]
        name = sat.get('OBJECT_NAME', 'Unknown')
        norad_id = sat.get('NORAD_CAT_ID')
        if norad_id is None:
            return False
        from config_manager import config
        config.add_favorite(name, norad_id, sat_type)
        return True

    def cancel_search(self):
        """Cancel search and restore view (Escape key)."""
        if self._saved_view:
            self.post_message(RestoreView(
                self._saved_view['lat'],
                self._saved_view['lon'],
                self._saved_view['zoom']
            ))
        self.request_close()
        return True

    def _render_content(self):
        """Render search popup content."""
        # Input line with cursor, placeholder, and result count
        if self.query:
            if self.results:
                count_text = f"[dim]{len(self.results)} found[/dim]"
                input_text = f"Search: {self.query}_"
                available_width = 56
                padding = available_width - len(input_text) - len(f"{len(self.results)} found")
                if padding > 0:
                    input_line = f"{input_text}{' ' * padding}{count_text}"
                else:
                    input_line = input_text
            else:
                input_line = f"Search: {self.query}_"
        else:
            input_line = "Search: [dim]Type to search...[/dim]"

        # Result lines (up to 5 per page) - only show if we have results
        result_lines = []
        if self.results:
            page_results = self.results[self.page_offset:self.page_offset + 5]

            for i, (idx, sat, sat_type) in enumerate(page_results):
                global_index = self.page_offset + i
                name = sat.get('OBJECT_NAME', 'Unknown')
                color = SATELLITE_TYPES.get(sat_type, {}).get('color', 'white')

                if global_index == self.selected_index:
                    result_lines.append(f"[reverse]> [{color}]{name}[/{color}][/reverse]")
                else:
                    result_lines.append(f"  [{color}]{name}[/{color}]")
        elif self.query:
            result_lines.append("[red]No results found[/red]")

        # Pad to 5 lines
        while len(result_lines) < 5:
            result_lines.append("")

        try:
            self.query_one("#search_row_0", Label).update(input_line)

            for i in range(5):
                label = self.query_one(f"#search_row_{i + 1}", Label)
                if result_lines[i]:
                    label.display = True
                    label.update(result_lines[i])
                else:
                    label.display = False

            self.query_one("#search_row_6", Label).update(
                "[dim]Enter:view  f:focus  b:fav  Esc:cancel[/dim]"
            )
        except:
            pass

    def _handle_key(self, event):
        key = event.key

        if key == "escape":
            self.cancel_search()
            event.stop()
            event.prevent_default()
        elif key == "enter":
            self.confirm_selection()
            event.stop()
            event.prevent_default()
        elif key == "f":
            self.focus_selection()
            event.stop()
            event.prevent_default()
        elif key == "b":
            self.bookmark_selection()
            event.stop()
            event.prevent_default()
        elif key == "up":
            self.move_selection(-1)
            event.stop()
            event.prevent_default()
        elif key == "down":
            self.move_selection(1)
            event.stop()
            event.prevent_default()
        elif key == "space":
            self.handle_char(' ')
            event.stop()
            event.prevent_default()
        elif key == "minus":
            self.handle_char('-')
            event.stop()
            event.prevent_default()
        elif key == "plus":
            self.handle_char('+')
            event.stop()
            event.prevent_default()
        elif key == "backspace":
            self.handle_backspace()
            event.stop()
            event.prevent_default()
        elif len(key) == 1 and key.isalnum():
            self.handle_char(key)
            event.stop()
            event.prevent_default()
