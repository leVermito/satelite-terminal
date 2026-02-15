"""Locations popup overlay widget."""

from textual.app import ComposeResult
from textual.widgets import Static, Label
from config_manager import config

from .popup_base import CrudPopupBase
from .messages import PopupClosed, CenterOnLocation, GlobeRedrawNeeded


class LocationsPopup(CrudPopupBase):
    """Locations management popup with add/edit/delete/center functionality."""

    CLOSE_KEY = "l"
    POPUP_NAME = "locations"
    ESC_CLOSES = False  # ESC behavior varies by mode
    ROW_COUNT = 12
    ROW_ID_PREFIX = "loc_row"
    ROW_CSS_CLASS = "loc-row"

    DEFAULT_CSS = """
    LocationsPopup {
        layer: overlay;
        width: auto;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid #7ecbff;
        border-title-color: #7ecbff;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .loc-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.border_title = "LOCATIONS (L to close)"
        self._edit_field = 0  # 0=name, 1=color, 2=lat, 3=lon, 4=hide
        self._edit_buffers = {"name": "", "color": "", "lat": "", "lon": "", "hide": ""}
        self._editing_new = False
        self._field_active = False  # True when actively editing a field
        self._field_was_cleared = {"name": False, "color": False, "lat": False, "lon": False}

    def on_mount(self):
        pass  # Content rendered when shown

    def _get_item_count(self) -> int:
        return len(config.locations)

    def _get_search_text(self, index: int) -> str:
        locations = config.locations
        if index < len(locations):
            loc = locations[index]
            return f"{loc['name']} {loc['lat']} {loc['lon']}"
        return ""

    def _render_content(self):
        if self._mode == "list":
            self._render_list()
        elif self._mode == "edit":
            self._render_edit()
        elif self._mode == "delete_confirm":
            self._render_delete_confirm("Want to delete")

    def _render_list(self):
        lines = []
        locations = config.locations

        # Build filtered indices
        filtered = [i for i in range(len(locations)) if self._match_search(self._get_search_text(i))]
        self._filtered_indices = filtered if self._search_query else None

        # Clamp selection to filtered set
        if filtered and self._selected_index not in filtered:
            self._selected_index = filtered[0]

        if not locations:
            lines.append("[dim]No locations defined[/dim]")
            lines.append("")
        elif not filtered:
            lines.append("[dim]No matches[/dim]")
            lines.append("")
        else:
            # Calculate column widths from filtered data
            shown = [locations[i] for i in filtered]
            max_name_len = max(len(loc["name"]) for loc in shown)
            max_name_len = max(max_name_len, 4)

            lat_width = 10
            lon_width = 11
            color_width = 9

            header = f"   {'Name':<{max_name_len}}  {'Lat':<{lat_width}}  {'Lon':<{lon_width}}  {'Color':<{color_width}}  Hide  Default"
            lines.append(header)

            sep = f"   {'─' * max_name_len}  {'─' * lat_width}  {'─' * lon_width}  {'─' * color_width}  ────  ───────"
            lines.append(sep)

            for i in filtered:
                loc = locations[i]
                marker = ">" if i == self._selected_index else " "
                name = loc["name"]
                lat = loc["lat"]
                lon = loc["lon"]
                color = loc.get("color", "#ffffff")
                is_default = loc.get("default", False)
                is_hidden = loc.get("hide", False)

                hide_marker = "\\[x]" if is_hidden else "\\[ ]"
                default_marker = "\\[x]" if is_default else "\\[ ]"

                line = f"{marker}  {name:<{max_name_len}}  {lat:<{lat_width}.4f}  {lon:<{lon_width}.4f}  {color:<{color_width}}  {hide_marker}   {default_marker}"
                lines.append(line)

            lines.append("")

        lines.append(f"[dim]a:add  e:edit  x:del  h:hide  f:follow  Enter:center  Space:default  l:close[/dim]  {self._render_search_bar()}")

        while len(lines) < 12:
            lines.append("")

        self._update_labels(lines)

    def _render_edit(self):
        lines = []
        lines.append("")

        fields = ["name", "color", "lat", "lon", "hide"]
        labels = ["Name: ", "Color:", "Lat:  ", "Lon:  ", "Hide: "]

        for i, (field, label) in enumerate(zip(fields, labels)):
            marker = ">" if i == self._edit_field else " "

            if field == "hide":
                hide_checked = self._edit_buffers["hide"].lower() in ("true", "yes", "1", "t", "y")
                checkbox = "\\[x]" if hide_checked else "\\[ ]"
                if i == self._edit_field:
                    lines.append(f"{marker} {label} [reverse]{checkbox}[/reverse]")
                else:
                    lines.append(f"{marker} {label} {checkbox}")
            else:
                value = self._edit_buffers[field]
                if i == self._edit_field and self._field_active:
                    lines.append(f"{marker} {label} [reverse]\\[{value:<20}][/reverse]")
                else:
                    lines.append(f"{marker} {label} \\[{value:<20}]")

        lines.append("")
        if self._field_active and self._edit_field != 4:
            lines.append("[dim]Type to edit  Enter:confirm field  Esc:back[/dim]")
        else:
            lines.append("[dim]Up/Down:select  Enter:toggle/edit  s:save  Esc:cancel[/dim]")
        lines.append("[dim]Format: Lat/Lon signed decimal (-90 to 90, -180 to 180). Hide: Enter to toggle[/dim]")

        while len(lines) < 12:
            lines.append("")

        self._update_labels(lines)

    def handle_char(self, ch):
        """Handle character input in edit mode."""
        if self._mode != "edit" or not self._field_active:
            return

        if self._edit_field == 4:
            return

        field = ["name", "color", "lat", "lon", "hide"][self._edit_field]

        if field in ("name", "lat", "lon", "color") and not self._field_was_cleared.get(field, False):
            self._edit_buffers[field] = ch
            self._field_was_cleared[field] = True
        else:
            self._edit_buffers[field] += ch

        self._render_content()

    def handle_backspace(self):
        """Handle backspace in edit mode."""
        if self._mode != "edit" or not self._field_active:
            return

        if self._edit_field == 4:
            return

        field = ["name", "color", "lat", "lon", "hide"][self._edit_field]
        if self._edit_buffers[field]:
            self._edit_buffers[field] = self._edit_buffers[field][:-1]
            if field in self._field_was_cleared:
                self._field_was_cleared[field] = True
            self._render_content()

    def move_field(self, direction):
        """Move between fields in edit mode."""
        if self._mode != "edit":
            return

        if not self._field_active:
            self._edit_field = (self._edit_field + direction) % 5
            self._render_content()

    def confirm(self):
        """Handle Enter key based on current mode."""
        if self._mode == "list":
            self.center_on_selected()
        elif self._mode == "edit":
            if self._edit_field == 4:  # hide field
                current = self._edit_buffers["hide"].lower() in ("true", "yes", "1", "t", "y")
                self._edit_buffers["hide"] = "false" if current else "true"
                self._render_content()
            elif self._field_active:
                self._field_active = False
                self._render_content()
            else:
                self._field_active = True
                field_name = ["name", "color", "lat", "lon", "hide"][self._edit_field]
                if field_name in self._field_was_cleared:
                    self._field_was_cleared[field_name] = False
                self._render_content()

    def _save_edit(self):
        """Save edited location."""
        name = self._edit_buffers["name"].strip()
        color = self._edit_buffers["color"].strip()
        lat_str = self._edit_buffers["lat"].strip()
        lon_str = self._edit_buffers["lon"].strip()
        hide_str = self._edit_buffers["hide"].strip().lower()

        if not name:
            return

        hide = hide_str in ("true", "yes", "1", "t", "y")

        try:
            lat_parts = lat_str.upper().split()
            if len(lat_parts) == 2 and lat_parts[1] in ('N', 'S'):
                lat = float(lat_parts[0])
                if lat_parts[1] == 'S':
                    lat = -lat
            else:
                lat = float(lat_str)

            lon_parts = lon_str.upper().split()
            if len(lon_parts) == 2 and lon_parts[1] in ('E', 'W'):
                lon = float(lon_parts[0])
                if lon_parts[1] == 'W':
                    lon = -lon
            else:
                lon = float(lon_str)
        except ValueError:
            return

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return

        if not color.startswith("#") or len(color) != 7:
            color = "#ffffff"

        locations = list(config.locations)

        if self._editing_new:
            locations.append({
                "name": name,
                "color": color,
                "lat": lat,
                "lon": lon,
                "default": False,
                "hide": hide
            })
            self._selected_index = len(locations) - 1
        else:
            if 0 <= self._selected_index < len(locations):
                locations[self._selected_index]["name"] = name
                locations[self._selected_index]["color"] = color
                locations[self._selected_index]["lat"] = lat
                locations[self._selected_index]["lon"] = lon
                locations[self._selected_index]["hide"] = hide

        config.set_locations(locations)
        self._mode = "list"
        self._render_content()
        self.post_message(GlobeRedrawNeeded())

    def toggle_default(self):
        """Toggle default flag on selected location."""
        if self._mode != "list":
            return

        locations = list(config.locations)
        if not locations or self._selected_index >= len(locations):
            return

        current_default = locations[self._selected_index].get("default", False)

        if current_default:
            locations[self._selected_index]["default"] = False
        else:
            for loc in locations:
                loc["default"] = False
            locations[self._selected_index]["default"] = True

        config.set_locations(locations)
        self._render_content()

    def toggle_hide(self):
        """Toggle hide flag on selected location."""
        if self._mode != "list":
            return

        locations = list(config.locations)
        if not locations or self._selected_index >= len(locations):
            return

        current_hide = locations[self._selected_index].get("hide", False)
        locations[self._selected_index]["hide"] = not current_hide

        config.set_locations(locations)
        self._render_content()
        self.post_message(GlobeRedrawNeeded())

    def start_add(self):
        """Enter edit mode for new location."""
        self._mode = "edit"
        self._editing_new = True
        self._edit_field = 0
        self._field_active = False
        self._field_was_cleared = {"name": False, "color": False, "lat": False, "lon": False}
        self._edit_buffers = {"name": "", "color": "#ffffff", "lat": "48.8566", "lon": "2.3522", "hide": "false"}
        self._render_content()

    def start_edit(self):
        """Enter edit mode for existing location."""
        if self._mode != "list":
            return

        locations = config.locations
        if not locations or self._selected_index >= len(locations):
            return

        loc = locations[self._selected_index]
        self._mode = "edit"
        self._editing_new = False
        self._edit_field = 0
        self._field_active = False
        self._field_was_cleared = {"name": False, "color": False, "lat": False, "lon": False}
        self._edit_buffers = {
            "name": loc["name"],
            "color": loc.get("color", "#ffffff"),
            "lat": str(loc["lat"]),
            "lon": str(loc["lon"]),
            "hide": "true" if loc.get("hide", False) else "false"
        }
        self._render_content()

    def save_and_close(self):
        """Save location and return to list."""
        self._save_edit()

    def cancel_edit(self):
        """Cancel edit mode and return to list."""
        if self._field_active:
            self._field_active = False
            self._render_content()
        else:
            self._mode = "list"
            self._render_content()

    def start_delete_confirm(self):
        """Enter delete confirmation mode."""
        if self._mode != "list":
            return

        locations = config.locations
        if not locations or self._selected_index >= len(locations):
            return

        self._delete_target_name = locations[self._selected_index]["name"]
        self._mode = "delete_confirm"
        self._render_content()

    def confirm_delete(self):
        """Actually delete the location."""
        locations = list(config.locations)
        if not locations or self._selected_index >= len(locations):
            self._mode = "list"
            self._render_content()
            return

        del locations[self._selected_index]
        self._selected_index = min(self._selected_index, max(0, len(locations) - 1))

        config.set_locations(locations)
        self._mode = "list"
        self._render_content()

    def center_on_selected(self):
        """Center camera on selected location."""
        if self._mode != "list":
            return

        locations = config.locations
        if not locations or self._selected_index >= len(locations):
            return

        loc = locations[self._selected_index]
        self.post_message(CenterOnLocation(loc["lat"], loc["lon"], 1.8))

    def _handle_mode_key(self, event):
        key = event.key

        if self._mode == "edit":
            if key == "escape":
                self.cancel_edit()
                event.stop()
                event.prevent_default()
            elif key == "enter":
                self.confirm()
                event.stop()
                event.prevent_default()
            elif key == "up":
                if not self._field_active:
                    self.move_field(-1)
                event.stop()
                event.prevent_default()
            elif key == "down":
                if not self._field_active:
                    self.move_field(1)
                event.stop()
                event.prevent_default()
            elif key == "number_sign":
                self.handle_char('#')
                event.stop()
                event.prevent_default()
            elif key == "period" or key == "full_stop":
                self.handle_char('.')
                event.stop()
                event.prevent_default()
            elif key == "minus":
                self.handle_char('-')
                event.stop()
                event.prevent_default()
            elif key == "space":
                if self._field_active:
                    self.handle_char(' ')
                event.stop()
                event.prevent_default()
            elif key == "s":
                if self._field_active:
                    self.handle_char('s')
                else:
                    self.save_and_close()
                event.stop()
                event.prevent_default()
            elif key == "backspace":
                self.handle_backspace()
                event.stop()
                event.prevent_default()
            elif len(key) == 1 and (key.isalnum() or key in ('.', '-', '#', '_', ' ')):
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
        elif key == "e":
            self.start_edit()
            event.stop()
            event.prevent_default()
        elif key == "x":
            self.start_delete_confirm()
            event.stop()
            event.prevent_default()
        elif key == "space":
            self.toggle_default()
            event.stop()
            event.prevent_default()
        elif key == "h":
            self.toggle_hide()
            event.stop()
            event.prevent_default()
        elif key == "f":
            self.center_on_selected()
            self.request_close()
            event.stop()
            event.prevent_default()
