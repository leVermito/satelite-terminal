"""Satellites popup widget for category-based satellite management."""

import os
import numpy as np
from pathlib import Path
from textual.app import ComposeResult
from textual.widgets import Static, Label
from config_manager import SATELLITE_TYPES, get_type_color, get_category_color

from .popup_base import PopupBase
from .messages import SatellitesChanged, GlobeRedrawNeeded


# Get data directory - handle both running from app/ and project root
_WIDGET_DIR = Path(__file__).parent.resolve()
_APP_DIR = _WIDGET_DIR.parent
DATA_DIR = _APP_DIR / "data"

# Fallback: check if we're running from project root
if not DATA_DIR.exists():
    _cwd = Path.cwd()
    if (_cwd / "app" / "data").exists():
        DATA_DIR = _cwd / "app" / "data"


def discover_satellite_categories() -> dict[str, list[str]]:
    """Discover satellite categories from data directory structure.

    Returns:
        Dict mapping category (subdirectory) to list of satellite type filenames.
        Root-level files are under '' (empty string) key.
    """
    if not DATA_DIR.exists():
        return {}

    categories = {}

    # Root level files
    root_files = []
    for f in DATA_DIR.glob("*.json"):
        name = f.stem
        parts = name.rsplit('_', 2)
        if len(parts) >= 3:
            sat_type = parts[0]
            root_files.append(sat_type)
    if root_files:
        categories[''] = sorted(set(root_files))

    # Subdirectories
    for subdir in DATA_DIR.iterdir():
        if subdir.is_dir() and subdir.name != 'backup':
            types = []
            for f in subdir.glob("*.json"):
                name = f.stem
                parts = name.rsplit('_', 2)
                if len(parts) >= 3:
                    sat_type = parts[0]
                    types.append(sat_type)
            if types:
                categories[subdir.name] = sorted(set(types))

    return categories


def find_latest_file(sat_type: str, category: str = '') -> str | None:
    """Find latest file for a satellite type in a category."""
    if category:
        search_dir = DATA_DIR / category
    else:
        search_dir = DATA_DIR

    if not search_dir.exists():
        return None

    pattern = f"{sat_type}_*.json"
    files = list(search_dir.glob(pattern))
    if not files:
        return None

    files.sort()
    return str(files[-1])


class SatellitesPopup(PopupBase):
    """Satellites popup for loading and managing satellite categories."""

    CLOSE_KEY = "s"
    POPUP_NAME = "satellites"
    ROW_COUNT = 22
    ROW_ID_PREFIX = "sat_row"
    ROW_CSS_CLASS = "sat-row"

    DEFAULT_CSS = """
    SatellitesPopup {
        layer: overlay;
        width: auto;
        height: auto;
        max-height: 30;
        background: $surface;
        border: solid $primary;
        border-title-color: $primary;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .sat-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.border_title = "SATELLITES (S to close)"

        # Category structure: {category: [types]}
        self.categories = {}

        # Loaded satellites: {(category, type): {'data': [...], 'visible': True}}
        self.loaded = {}

        # UI state
        self._selected_index = 0
        self._items = []  # Flat list of (category, type) or (category, None) for headers
        self._scroll_offset = 0
        self._visible_rows = 20

    def on_mount(self):
        pass  # Content rendered when shown

    def refresh_categories(self):
        """Refresh category list from filesystem."""
        self.categories = discover_satellite_categories()
        self._rebuild_items()

    def _rebuild_items(self):
        """Rebuild flat item list for navigation."""
        self._items = []

        # Add LOADED section at top if there are loaded satellites
        if self.loaded:
            self._items.append(('__loaded__', None))  # LOADED header
            for (cat, sat_type), info in self.loaded.items():
                # Add loaded items with special marker
                self._items.append(('__loaded__', sat_type, cat))  # (marker, type, original_category)

        # Sort categories: empty string (root) first, then alphabetically
        sorted_cats = sorted(self.categories.keys(), key=lambda x: (x != '', x))

        for cat in sorted_cats:
            types = self.categories[cat]
            # Add category header (not selectable, just for display)
            if cat:
                self._items.append((cat, None))  # Header
            for t in types:
                self._items.append((cat, t))

        # Clamp selection
        if self._items:
            # Skip headers for initial selection
            self._selected_index = 0
            while self._selected_index < len(self._items) and self._is_header(self._selected_index):
                self._selected_index += 1
            if self._selected_index >= len(self._items):
                self._selected_index = 0

    def _is_header(self, idx):
        """Check if item at index is a header (non-selectable)."""
        if idx >= len(self._items):
            return False
        item = self._items[idx]
        # Headers have None as second element and exactly 2 elements
        return len(item) == 2 and item[1] is None

    def _get_search_text(self, index: int) -> str:
        if index >= len(self._items):
            return ""
        item = self._items[index]
        if len(item) == 2 and item[1] is None:
            return ""  # Header
        if len(item) == 3:
            _, sat_type, original_cat = item
            return f"{sat_type} {original_cat}"
        cat, sat_type = item
        return f"{sat_type} {cat}"

    def _get_selectable_items(self):
        """Get indices of selectable items (non-headers), respecting search filter."""
        result = []
        for i, item in enumerate(self._items):
            if len(item) == 2 and item[1] is None:
                continue  # Header
            if not self._match_search(self._get_search_text(i)):
                continue
            result.append(i)
        return result

    def move_selection(self, direction: int):
        """Move selection up/down, skipping headers."""
        selectable = self._get_selectable_items()
        if not selectable:
            return

        try:
            current_pos = selectable.index(self._selected_index)
        except ValueError:
            current_pos = 0

        new_pos = (current_pos + direction) % len(selectable)
        self._selected_index = selectable[new_pos]

        # Adjust scroll to keep selection visible
        if self._selected_index < self._scroll_offset:
            self._scroll_offset = self._selected_index
        elif self._selected_index >= self._scroll_offset + self._visible_rows:
            self._scroll_offset = self._selected_index - self._visible_rows + 1

        self._render_content()

    def toggle_selected(self):
        """Toggle load/visibility of selected item."""
        if not self._items or self._selected_index >= len(self._items):
            return

        item = self._items[self._selected_index]
        if len(item) == 2 and item[1] is None:
            return  # Header, not selectable

        # Handle loaded items (3-element tuple) vs regular items (2-element tuple)
        if len(item) == 3:
            # Loaded item: ('__loaded__', sat_type, original_category)
            _, sat_type, original_cat = item
            key = (original_cat, sat_type)
        else:
            # Regular item: (category, sat_type)
            cat, sat_type = item
            key = (cat, sat_type)

        if key in self.loaded:
            # Already loaded - toggle visibility
            self.loaded[key]['visible'] = not self.loaded[key]['visible']
            self._sync_to_app()
        else:
            # Not loaded - load it
            self._load_satellite_type(key[0], sat_type)

        # Remember the sat_type we just acted on
        target_sat_type = sat_type
        target_cat = key[0]
        was_in_loaded_section = (len(item) == 3)

        self._rebuild_items()

        # Keep cursor in the same section it was in
        if was_in_loaded_section:
            # Was in LOADED section - stay there if still loaded
            if key in self.loaded:
                for i, it in enumerate(self._items):
                    if len(it) == 3 and it[1] == target_sat_type and it[2] == target_cat:
                        self._selected_index = i
                        break
            else:
                # No longer loaded - find in original category
                for i, it in enumerate(self._items):
                    if len(it) == 2 and it[0] == target_cat and it[1] == target_sat_type:
                        self._selected_index = i
                        break
        else:
            # Was in original category - stay there
            for i, it in enumerate(self._items):
                if len(it) == 2 and it[0] == target_cat and it[1] == target_sat_type:
                    self._selected_index = i
                    break

        # Adjust scroll to keep selection visible
        if self._selected_index < self._scroll_offset:
            self._scroll_offset = self._selected_index
        elif self._selected_index >= self._scroll_offset + self._visible_rows:
            self._scroll_offset = self._selected_index - self._visible_rows + 1

        self._render_content()

    def _load_satellite_type(self, category: str, sat_type: str):
        """Load a satellite type from file."""
        import json

        filepath = find_latest_file(sat_type, category)
        if not filepath:
            return

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            key = (category, sat_type)
            self.loaded[key] = {
                'data': data,
                'visible': True,
                'category': category,
                'type': sat_type,
            }

            self._sync_to_app()
            self._persist_loaded()
        except (json.JSONDecodeError, IOError):
            pass

    def _persist_loaded(self):
        """Write current loaded satellite keys to config."""
        from config_manager import config
        config.set_default_satellites(list(self.loaded.keys()))

    def _sync_to_app(self):
        """Sync loaded satellites by posting a message."""
        from satellite.orbital import get_type_index, TYPE_NAME_TO_INDEX

        all_satellites = []
        all_types = []

        # Register any new satellite types dynamically
        for key, info in self.loaded.items():
            cat, sat_type = key
            if sat_type not in TYPE_NAME_TO_INDEX:
                new_idx = 10 + len([k for k in TYPE_NAME_TO_INDEX.keys() if TYPE_NAME_TO_INDEX[k] >= 10])
                TYPE_NAME_TO_INDEX[sat_type] = new_idx

        for key, info in self.loaded.items():
            if info['visible']:
                cat, sat_type = key
                data = info['data']
                all_satellites.extend(data)
                all_types.extend([sat_type] * len(data))

        # Build type_indices
        if all_satellites:
            type_indices = np.array([get_type_index(t) for t in all_types])
        else:
            type_indices = None

        self.post_message(SatellitesChanged(
            satellite_data=all_satellites if all_satellites else None,
            satellite_types_list=all_types,
            type_indices=type_indices,
        ))

    def set_visibility(self, direction: int):
        """Cycle visibility mode for selected item: POSITION -> NAME -> N."""
        if not self._items or self._selected_index >= len(self._items):
            return

        item = self._items[self._selected_index]
        if len(item) == 2 and item[1] is None:
            return  # Header

        # Handle loaded items (3-element tuple) vs regular items (2-element tuple)
        if len(item) == 3:
            _, sat_type, original_cat = item
            key = (original_cat, sat_type)
        else:
            cat, sat_type = item
            key = (cat, sat_type)

        if key not in self.loaded:
            return

        # Get current mode
        current_mode = self.loaded[key].get('mode', 'POSITION')
        modes = ['POSITION', 'NAME', 'N']
        try:
            idx = modes.index(current_mode)
        except ValueError:
            idx = 0

        new_idx = (idx + direction) % len(modes)
        self.loaded[key]['mode'] = modes[new_idx]
        self.loaded[key]['visible'] = modes[new_idx] != 'N'

        self._sync_to_app()
        self._render_content()

    def get_display_modes(self) -> dict[str, str]:
        """Get display modes for all loaded types."""
        modes = {}
        for (cat, sat_type), info in self.loaded.items():
            mode = info.get('mode', 'POSITION' if info['visible'] else 'N')
            modes[sat_type] = mode
        return modes

    def load_defaults(self):
        """Load default satellite types if available."""
        from config_manager import config

        if not self.categories:
            self.refresh_categories()

        defaults = config.default_satellites
        if not defaults:
            defaults = [
                ('special-interest', 'stations'),
                ('weather', 'noaa'),
                ('navigation', 'gps-ops'),
            ]

        for cat, sat_type in defaults:
            if cat in self.categories and sat_type in self.categories.get(cat, []):
                self._load_satellite_type(cat, sat_type)

        self._render_content()

    def _render_content(self):
        """Render the popup content."""
        lines = []

        if not self._items:
            lines.append(f"[dim]No satellite data found[/dim]")
            lines.append(f"[dim]DATA_DIR: {DATA_DIR}[/dim]")
            lines.append(f"[dim]exists: {DATA_DIR.exists()}[/dim]")
            lines.append(f"[dim]categories: {len(self.categories)}[/dim]")
            lines.append("[dim]Run ./app/scripts/pull_data.sh to download[/dim]")
        else:
            # Build set of matching selectable indices for filtering
            selectable = self._get_selectable_items()
            if self._search_query:
                matching_set = set(selectable)
                # Determine which headers to show (those with at least one matching child)
                visible_indices = []
                for idx, item in enumerate(self._items):
                    if len(item) == 2 and item[1] is None:
                        # Header: include if any following items (until next header) match
                        has_child = False
                        for j in range(idx + 1, len(self._items)):
                            next_item = self._items[j]
                            if len(next_item) == 2 and next_item[1] is None:
                                break
                            if j in matching_set:
                                has_child = True
                                break
                        if has_child:
                            visible_indices.append(idx)
                    elif idx in matching_set:
                        visible_indices.append(idx)
            else:
                visible_indices = list(range(len(self._items)))

            # Clamp selection to selectable filtered items
            if selectable and self._selected_index not in selectable:
                self._selected_index = selectable[0]

            # Adjust scroll to keep selection visible
            if visible_indices:
                try:
                    sel_pos = visible_indices.index(self._selected_index)
                except ValueError:
                    sel_pos = 0
                if sel_pos < self._scroll_offset:
                    self._scroll_offset = sel_pos
                elif sel_pos >= self._scroll_offset + self._visible_rows:
                    self._scroll_offset = sel_pos - self._visible_rows + 1
            else:
                self._scroll_offset = 0

            # Visible window from filtered list
            window = visible_indices[self._scroll_offset:self._scroll_offset + self._visible_rows]

            for global_idx in window:
                item = self._items[global_idx]
                is_selected = global_idx == self._selected_index
                marker = ">" if is_selected else " "

                if len(item) == 2:
                    cat, sat_type = item
                    original_cat = cat
                else:
                    cat, sat_type, original_cat = item

                if sat_type is None:
                    if cat == '__loaded__':
                        lines.append(f"  [bold white]── LOADED ──[/bold white]")
                    else:
                        cat_color = get_category_color(cat)
                        lines.append(f"  [bold {cat_color}]── {cat.upper()} ──[/bold {cat_color}]")
                else:
                    if cat == '__loaded__':
                        key = (original_cat, sat_type)
                        color = get_category_color(original_cat) if original_cat else 'white'
                    else:
                        key = (cat, sat_type)
                        color = get_category_color(cat) if cat else 'white'

                    is_loaded = key in self.loaded

                    if is_loaded:
                        info = self.loaded[key]
                        mode = info.get('mode', 'POSITION' if info['visible'] else 'N')
                        count = len(info['data'])
                        mode_display = self._format_mode(mode)
                        lines.append(f"{marker} [{color}]{sat_type:<25}[/{color}] [green]LOADED[/green] ({count:>5})  {mode_display}")
                    else:
                        lines.append(f"{marker} [{color}]{sat_type:<25}[/{color}] [white bold]LOAD[/white bold]")

            # Footer
            lines.append("")
            total_loaded = sum(len(info['data']) for info in self.loaded.values() if info['visible'])
            lines.append(f"[dim]Enter:load  x:unload  left/right:mode  {total_loaded} visible  s:close[/dim]  {self._render_search_bar()}")

        # Pad to 22 lines
        while len(lines) < 22:
            lines.append("")

        # Update labels
        try:
            for i in range(22):
                label = self.query_one(f"#sat_row_{i}", Label)
                if i < len(lines) and lines[i]:
                    label.display = True
                    label.update(lines[i])
                else:
                    label.display = False
        except Exception:
            pass

    def _format_mode(self, mode: str) -> str:
        """Format mode display with highlighting."""
        modes = ['POSITION', 'NAME', 'N']
        parts = []
        for m in modes:
            if m == mode:
                style = "red bold" if m == "N" else "white bold"
                parts.append(f"[{style}]{m}[/{style}]")
            else:
                parts.append(f"[dim]{m}[/dim]")
        return " ".join(parts)

    def unload_selected(self):
        """Unload the selected satellite type."""
        if not self._items or self._selected_index >= len(self._items):
            return

        item = self._items[self._selected_index]
        if len(item) == 2 and item[1] is None:
            return  # Header

        if len(item) == 3:
            _, sat_type, original_cat = item
            key = (original_cat, sat_type)
        else:
            cat, sat_type = item
            key = (cat, sat_type)

        if key not in self.loaded:
            return

        old_index = self._selected_index
        del self.loaded[key]
        self._sync_to_app()
        self._persist_loaded()
        self._rebuild_items()

        # Keep cursor near the same position, clamped to selectable items
        selectable = self._get_selectable_items()
        if selectable:
            # Pick the nearest selectable item at or before the old position
            best = selectable[0]
            for idx in selectable:
                if idx <= old_index:
                    best = idx
                else:
                    break
            self._selected_index = best
        elif self._items:
            self._selected_index = 0

        if self._selected_index < self._scroll_offset:
            self._scroll_offset = self._selected_index
        elif self._selected_index >= self._scroll_offset + self._visible_rows:
            self._scroll_offset = self._selected_index - self._visible_rows + 1

        self._render_content()

    def _handle_key(self, event):
        key = event.key
        if key == "up":
            self.move_selection(-1)
            event.stop()
            event.prevent_default()
        elif key == "down":
            self.move_selection(1)
            event.stop()
            event.prevent_default()
        elif key == "left":
            self.set_visibility(-1)
            event.stop()
            event.prevent_default()
        elif key == "right":
            self.set_visibility(1)
            event.stop()
            event.prevent_default()
        elif key == "enter":
            self.toggle_selected()
            event.stop()
            event.prevent_default()
        elif key == "x":
            self.unload_selected()
            event.stop()
            event.prevent_default()
