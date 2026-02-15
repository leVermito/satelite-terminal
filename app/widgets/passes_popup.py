"""Pass prediction popup overlay widget."""

from datetime import datetime, timezone
from textual.app import ComposeResult
from textual.widgets import Static, Label
from config_manager import config

from .popup_base import PopupBase


class PassesPopup(PopupBase):
    """Pass prediction popup showing when favorites pass over default location."""

    CLOSE_KEY = "p"
    POPUP_NAME = "passes"
    ESC_CLOSES = True
    ROW_COUNT = 20
    ROW_ID_PREFIX = "pass_row"
    ROW_CSS_CLASS = "pass-row"

    DEFAULT_CSS = """
    PassesPopup {
        layer: overlay;
        width: auto;
        height: auto;
        max-height: 24;
        background: $surface;
        border: solid #aa88ff;
        border-title-color: #aa88ff;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .pass-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.border_title = "PASSES (P to close)"
        self._passes = []
        self._selected_index = 0
        self._scroll_offset = 0
        self._error = ""
        self._observer_name = ""
        self._observer_lat = 0.0
        self._observer_lon = 0.0
        self._satellite_data = None

    def set_satellite_data(self, satellite_data):
        """Set satellite data reference for pass computation."""
        self._satellite_data = satellite_data

    def on_mount(self):
        pass

    def compute_passes(self):
        """Compute passes on demand. Called when popup is opened."""
        self._passes = []
        self._error = ""
        self._selected_index = 0
        self._scroll_offset = 0

        default_loc = config.get_default_location()
        if default_loc is None:
            self._error = "No default location set. Use Locations (L) to set one."
            return

        self._observer_name = default_loc["name"]
        self._observer_lat = default_loc["lat"]
        self._observer_lon = default_loc["lon"]

        favorites = config.favorites
        if not favorites:
            self._error = "No favorites. Use Favorites (B) to add satellites."
            return

        satellite_data = self._satellite_data
        if satellite_data is None or len(satellite_data) == 0:
            self._error = "No satellites loaded. Press S to load satellites first."
            return

        from satellite.pass_prediction import predict_all_favorites
        self._passes = predict_all_favorites(
            favorites, satellite_data,
            self._observer_lat, self._observer_lon,
            max_per_sat=config.get_option("passes_per_sat"),
            max_total=config.get_option("max_passes"),
        )

    def _get_search_text(self, index: int) -> str:
        if index < len(self._passes):
            return self._passes[index]["name"]
        return ""

    def _render_content(self):
        lines = []

        if self._error:
            lines.append("")
            lines.append(f"  [red]{self._error}[/red]")
            lines.append("")
            lines.append("[dim]p:close[/dim]")
            self._update_labels(lines)
            return

        # Header
        lines.append(
            f"  Observer: [#7ecbff]{self._observer_name}[/#7ecbff]  "
            f"({self._observer_lat:.2f}, {self._observer_lon:.2f})  Next 24h"
        )

        now = datetime.now(timezone.utc)

        # Build filtered indices
        filtered = [i for i in range(len(self._passes)) if self._match_search(self._get_search_text(i))]

        # Clamp selection
        if filtered and self._selected_index not in filtered:
            self._selected_index = filtered[0] if filtered else 0

        # Precompute ETA plain text and in-sight flag per pass
        eta_plain = []
        eta_in_sight = []
        for p in self._passes:
            if p["rise"] <= now <= p["set"]:
                eta_plain.append("IN SIGHT")
                eta_in_sight.append(True)
            else:
                eta_plain.append(self._format_eta(p["rise"], now))
                eta_in_sight.append(False)

        # Compute column widths from filtered data
        if filtered:
            name_w = max(min(len(self._passes[i]["name"]), 35) for i in filtered)
        else:
            name_w = 9
        name_w = max(name_w, 9)
        rise_w = 8
        el_w = 5
        set_w = 8
        dur_w = 5
        eta_w = max((len(eta_plain[i]) for i in filtered), default=3)
        eta_w = max(eta_w, 3)

        header = f"   {'Satellite':<{name_w}}  {'ETA':>{eta_w}}  {'Rise UTC':<{rise_w}}  {'MaxEl':>{el_w}}  {'Set UTC':<{set_w}}  {'Dur':>{dur_w}}"
        sep = f"   {'─' * name_w}  {'─' * eta_w}  {'─' * rise_w}  {'─' * el_w}  {'─' * set_w}  {'─' * dur_w}"
        lines.append(header)
        lines.append(sep)

        if not filtered:
            if self._passes:
                lines.append("  [dim]No matches[/dim]")
            else:
                lines.append("  [dim]No passes found in next 24h[/dim]")
        else:
            visible_rows = 14
            # Scroll within filtered list
            try:
                sel_pos = filtered.index(self._selected_index)
            except ValueError:
                sel_pos = 0
            if sel_pos < self._scroll_offset:
                self._scroll_offset = sel_pos
            elif sel_pos >= self._scroll_offset + visible_rows:
                self._scroll_offset = sel_pos - visible_rows + 1

            window = filtered[self._scroll_offset:self._scroll_offset + visible_rows]
            for i in window:
                p = self._passes[i]
                marker = ">" if i == self._selected_index else " "
                name = p["name"]
                if len(name) > 35:
                    name = name[:34] + "~"
                padded_eta = f"{eta_plain[i]:>{eta_w}}"
                if eta_in_sight[i]:
                    display_eta = f"[green]{padded_eta}[/green]"
                else:
                    display_eta = padded_eta
                rise_str = p["rise"].strftime("%H:%M:%S")
                set_str = p["set"].strftime("%H:%M:%S")
                max_el = p["max_el"]
                if eta_in_sight[i]:
                    dur_s = max(0, int((p["set"] - now).total_seconds()))
                else:
                    dur_s = int(p["duration_s"])
                dur_m = dur_s // 60
                dur_sec = dur_s % 60
                dur_str = f"{dur_m}:{dur_sec:02d}"

                line = f"{marker}  {name:<{name_w}}  {display_eta}  {rise_str:<{rise_w}}  {max_el:>{el_w}.1f}  {set_str:<{set_w}}  {dur_str:>{dur_w}}"
                lines.append(line)

            if len(filtered) > visible_rows:
                lines.append(f"  [dim]{len(filtered)} passes shown[/dim]")

        lines.append("")
        lines.append(f"[dim]Up/Down:scroll  p/Esc:close[/dim]  {self._render_search_bar()}")

        self._update_labels(lines)

    @staticmethod
    def _format_eta(rise_dt, now_dt):
        """Format ETA as compact DD:HH:MM:SS, omitting leading zero units."""
        delta = rise_dt - now_dt
        total = int(delta.total_seconds())
        if total < 0:
            return "0:00"
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        if days > 0:
            return f"{days}:{hours:02d}:{mins:02d}:{secs:02d}"
        if hours > 0:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    def move_selection(self, direction):
        if not self._passes:
            return
        filtered = [i for i in range(len(self._passes)) if self._match_search(self._get_search_text(i))]
        if not filtered:
            return
        try:
            pos = filtered.index(self._selected_index)
        except ValueError:
            pos = 0
        pos = (pos + direction) % len(filtered)
        self._selected_index = filtered[pos]
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
