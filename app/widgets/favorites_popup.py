"""Favorites popup overlay widget."""

import numpy as np
from textual.app import ComposeResult
from textual.widgets import Static, Label
from config_manager import config, SATELLITE_TYPES
from satellite.propagator import propagate_batch

from .popup_base import CrudPopupBase
from .messages import PopupClosed, CenterOnLocation, TrackSatellite, LoadSatelliteCategory


class FavoritesPopup(CrudPopupBase):
    """Favorites management popup with add/delete/center/track functionality."""

    CLOSE_KEY = "b"
    POPUP_NAME = "favorites"
    ESC_CLOSES = False  # ESC behavior varies by mode
    ROW_COUNT = 12
    ROW_ID_PREFIX = "fav_row"
    ROW_CSS_CLASS = "fav-row"

    DEFAULT_CSS = """
    FavoritesPopup {
        layer: overlay;
        width: auto;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid #ffaa00;
        border-title-color: #ffaa00;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .fav-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.border_title = "FAVORITES (B to close)"
        self._add_buffer = ""
        self._add_error = ""
        self._add_results = []  # [(index, sat, type)]
        self._add_selected = 0
        self._add_page_offset = 0
        self._delete_target_norad = 0
        self._satellite_data = None
        self._satellite_types_list = []
        self._type_indices = None
        self._time_provider = None

    def set_satellite_data(self, satellite_data, satellite_types_list, type_indices, time_provider):
        """Set satellite data references."""
        self._satellite_data = satellite_data
        self._satellite_types_list = satellite_types_list
        self._type_indices = type_indices
        self._time_provider = time_provider

    def on_mount(self):
        pass

    def _get_item_count(self) -> int:
        return len(config.favorites)

    def _get_search_text(self, index: int) -> str:
        favorites = config.favorites
        if index < len(favorites):
            f = favorites[index]
            return f"{f['name']} {f.get('type', '')} {f['norad_id']}"
        return ""

    def _render_content(self):
        if self._mode == "list":
            self._render_list()
        elif self._mode == "add":
            self._render_add()
        elif self._mode == "delete_confirm":
            self._render_delete_confirm("Remove from favorites")

    def _render_list(self):
        lines = []
        favorites = config.favorites

        # Build filtered indices
        filtered = [i for i in range(len(favorites)) if self._match_search(self._get_search_text(i))]
        self._filtered_indices = filtered if self._search_query else None

        # Clamp selection to filtered set
        if filtered and self._selected_index not in filtered:
            self._selected_index = filtered[0]

        if not favorites:
            lines.append("[dim]No favorites yet[/dim]")
            lines.append("")
        elif not filtered:
            lines.append("[dim]No matches[/dim]")
            lines.append("")
        else:
            # Compute column widths from filtered data
            shown = [favorites[i] for i in filtered]
            name_w = max((min(len(f["name"]), 35) for f in shown), default=4)
            name_w = max(name_w, 4)
            type_w = max((len(f.get("type", "unknown")) for f in shown), default=4)
            type_w = max(type_w, 4)
            norad_w = 8

            header = f"   {'Name':<{name_w}}  {'Type':<{type_w}}  {'NORAD ID':<{norad_w}}  Status"
            sep = f"   {'─' * name_w}  {'─' * type_w}  {'─' * norad_w}  {'─' * 10}"
            lines.append(header)
            lines.append(sep)

            for i in filtered:
                fav = favorites[i]
                marker = ">" if i == self._selected_index else " "
                name = fav["name"]
                norad_id = fav["norad_id"]
                sat_type = fav.get("type", "unknown")
                color = SATELLITE_TYPES.get(sat_type, {}).get('color', 'white')
                loaded = self._is_satellite_loaded(norad_id)
                status = "[green]LOADED[/green]" if loaded else "[dim]not loaded[/dim]"
                display_name = name[:35] if len(name) > 35 else name
                padded_name = f"{display_name:<{name_w}}"
                padded_type = f"{sat_type:<{type_w}}"
                line = f"{marker}  [{color}]{padded_name}[/{color}]  {padded_type}  {norad_id:<{norad_w}}  {status}"
                lines.append(line)

            lines.append("")

        lines.append(f"[dim]a:add  x:del  Enter:center  f:track  l:load  b:close[/dim]  {self._render_search_bar()}")

        while len(lines) < 12:
            lines.append("")

        self._update_labels(lines)

    def _search_loaded(self, query: str) -> list:
        """Substring search across loaded satellites."""
        if not query:
            return []
        satellites = self._satellite_data
        types_list = self._satellite_types_list
        if satellites is None:
            return []
        query_upper = query.upper()
        matches = []
        for i, sat in enumerate(satellites):
            name = sat.get('OBJECT_NAME', '').upper()
            if query_upper in name:
                sat_type = types_list[i] if i < len(types_list) else 'unknown'
                matches.append((i, sat, sat_type))
        return matches

    def _render_add(self):
        lines = []
        # Input line with count
        if self._add_buffer:
            input_text = f"  > {self._add_buffer}_"
            if self._add_results:
                count_text = f"[dim]{len(self._add_results)} found[/dim]"
                available = 66
                pad = available - len(f"  > {self._add_buffer}_") - len(f"{len(self._add_results)} found")
                if pad > 0:
                    lines.append(f"{input_text}{' ' * pad}{count_text}")
                else:
                    lines.append(input_text)
            elif self._add_error:
                lines.append(f"{input_text}  [red]{self._add_error}[/red]")
            else:
                lines.append(input_text)
        else:
            lines.append("  > [dim]Type name or NORAD ID...[/dim]")

        # Suggestion rows (5 per page)
        if self._add_results:
            page = self._add_results[self._add_page_offset:self._add_page_offset + 5]
            for i, (idx, sat, sat_type) in enumerate(page):
                global_i = self._add_page_offset + i
                name = sat.get('OBJECT_NAME', 'Unknown')
                color = SATELLITE_TYPES.get(sat_type, {}).get('color', 'white')
                if global_i == self._add_selected:
                    lines.append(f"[reverse]> [{color}]{name}[/{color}][/reverse]")
                else:
                    lines.append(f"  [{color}]{name}[/{color}]")
        elif self._add_buffer and not self._add_error:
            lines.append("[dim]No matches[/dim]")

        # Pad to at least 7 then add help
        while len(lines) < 7:
            lines.append("")
        lines.append("[dim]Up/Down:select  Enter:add selected  Esc:cancel[/dim]")

        while len(lines) < 12:
            lines.append("")

        self._update_labels(lines)

    def _is_satellite_loaded(self, norad_id: int) -> bool:
        satellites = self._satellite_data
        if satellites is None:
            return False
        for sat in satellites:
            if sat.get("NORAD_CAT_ID") == norad_id:
                return True
        return False

    def _find_satellite_by_norad(self, norad_id: int):
        satellites = self._satellite_data
        types_list = self._satellite_types_list
        if satellites is None:
            return None, None, None
        for i, sat in enumerate(satellites):
            if sat.get("NORAD_CAT_ID") == norad_id:
                sat_type = types_list[i] if i < len(types_list) else "unknown"
                return i, sat, sat_type
        return None, None, None

    def _find_satellite_by_name(self, name: str):
        satellites = self._satellite_data
        types_list = self._satellite_types_list
        if satellites is None:
            return None, None, None
        name_upper = name.upper()
        for i, sat in enumerate(satellites):
            if sat.get("OBJECT_NAME", "").upper() == name_upper:
                sat_type = types_list[i] if i < len(types_list) else "unknown"
                return i, sat, sat_type
        return None, None, None

    def handle_char(self, ch):
        if self._mode != "add":
            return
        self._add_error = ""
        self._add_buffer += ch
        self._add_results = self._search_loaded(self._add_buffer)
        self._add_selected = 0
        self._add_page_offset = 0
        self._render_content()

    def handle_backspace(self):
        if self._mode != "add":
            return
        if self._add_buffer:
            self._add_error = ""
            self._add_buffer = self._add_buffer[:-1]
            self._add_results = self._search_loaded(self._add_buffer)
            self._add_selected = 0
            self._add_page_offset = 0
            self._render_content()

    def move_add_selection(self, direction):
        if self._mode != "add" or not self._add_results:
            return
        self._add_selected = (self._add_selected + direction) % len(self._add_results)
        target_page = self._add_selected // 5
        self._add_page_offset = target_page * 5
        self._render_content()

    def start_add(self):
        self._mode = "add"
        self._add_buffer = ""
        self._add_error = ""
        self._add_results = []
        self._add_selected = 0
        self._add_page_offset = 0
        self._render_content()

    def confirm_add(self):
        # If suggestions exist, use the selected one
        if self._add_results and self._add_selected < len(self._add_results):
            idx, sat, sat_type = self._add_results[self._add_selected]
            config.add_favorite(sat["OBJECT_NAME"], sat["NORAD_CAT_ID"], sat_type)
            self._mode = "list"
            self._selected_index = len(config.favorites) - 1
            self._render_content()
            return

        query = self._add_buffer.strip()
        if not query:
            self._mode = "list"
            self._render_content()
            return

        # Try NORAD ID
        try:
            norad_id = int(query)
            idx, sat, sat_type = self._find_satellite_by_norad(norad_id)
            if sat is not None:
                config.add_favorite(sat["OBJECT_NAME"], norad_id, sat_type)
                self._mode = "list"
                self._selected_index = len(config.favorites) - 1
                self._render_content()
                return
        except ValueError:
            pass

        # Try exact name
        idx, sat, sat_type = self._find_satellite_by_name(query)
        if sat is not None:
            config.add_favorite(sat["OBJECT_NAME"], sat["NORAD_CAT_ID"], sat_type)
            self._mode = "list"
            self._selected_index = len(config.favorites) - 1
            self._render_content()
            return

        self._add_error = "NOT FOUND"
        self._render_content()

    def cancel_add(self):
        self._mode = "list"
        self._render_content()

    def start_delete_confirm(self):
        if self._mode != "list":
            return
        favorites = config.favorites
        if not favorites or self._selected_index >= len(favorites):
            return
        fav = favorites[self._selected_index]
        self._delete_target_name = fav["name"]
        self._delete_target_norad = fav["norad_id"]
        self._mode = "delete_confirm"
        self._render_content()

    def confirm_delete(self):
        config.remove_favorite(self._delete_target_norad)
        favorites = config.favorites
        self._selected_index = min(self._selected_index, max(0, len(favorites) - 1))
        self._mode = "list"
        self._render_content()

    def center_on_selected(self):
        if self._mode != "list":
            return
        favorites = config.favorites
        if not favorites or self._selected_index >= len(favorites):
            return
        fav = favorites[self._selected_index]
        idx, sat, sat_type = self._find_satellite_by_norad(fav["norad_id"])
        if idx is None:
            return
        satellites = self._satellite_data
        type_indices = self._type_indices
        now = self._time_provider() if self._time_provider else None
        if now is None:
            return
        results = propagate_batch(satellites, now, type_indices)
        if not np.isnan(results[idx, 0]):
            self.post_message(CenterOnLocation(results[idx, 0], results[idx, 1], 2.0))

    def load_selected_category(self):
        """Post message to load the satellite category for the selected favorite."""
        if self._mode != "list":
            return False
        favorites = config.favorites
        if not favorites or self._selected_index >= len(favorites):
            return False
        fav = favorites[self._selected_index]
        if self._is_satellite_loaded(fav["norad_id"]):
            return False
        sat_type = fav.get("type", "")
        if not sat_type:
            return False
        self.post_message(LoadSatelliteCategory(sat_type))
        return True

    def track_selected(self):
        if self._mode != "list":
            return False
        favorites = config.favorites
        if not favorites or self._selected_index >= len(favorites):
            return False
        fav = favorites[self._selected_index]
        idx, sat, sat_type = self._find_satellite_by_norad(fav["norad_id"])
        if idx is None:
            return False
        self.post_message(TrackSatellite(idx, fav["name"], sat_type))
        return True

    def _handle_mode_key(self, event):
        key = event.key

        if self._mode == "add":
            if key == "escape":
                self.cancel_add()
                event.stop()
                event.prevent_default()
            elif key == "enter":
                self.confirm_add()
                event.stop()
                event.prevent_default()
            elif key == "up":
                self.move_add_selection(-1)
                event.stop()
                event.prevent_default()
            elif key == "down":
                self.move_add_selection(1)
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
            elif key == "period" or key == "full_stop":
                self.handle_char('.')
                event.stop()
                event.prevent_default()
            elif key == "number_sign":
                self.handle_char('#')
                event.stop()
                event.prevent_default()
            elif key == "backspace":
                self.handle_backspace()
                event.stop()
                event.prevent_default()
            elif len(key) == 1 and key.isprintable():
                self.handle_char(key)
                event.stop()
                event.prevent_default()
            return

        # List mode
        if key == "escape":
            self.request_close()
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
        elif key == "enter":
            self.center_on_selected()
            event.stop()
            event.prevent_default()
        elif key == "a":
            self.start_add()
            event.stop()
            event.prevent_default()
        elif key == "x":
            self.start_delete_confirm()
            event.stop()
            event.prevent_default()
        elif key == "f":
            if self.track_selected():
                self.request_close()
            event.stop()
            event.prevent_default()
        elif key == "l":
            self.load_selected_category()
            event.stop()
            event.prevent_default()
