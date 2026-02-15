"""Antenna status popup: interactive list and detail view for RPi antenna clients."""

import time
from datetime import datetime, timezone

from config_manager import config
from .popup_base import PopupBase
from .messages import CenterOnLocation


STATE_COLORS = {
    "boot": "dim",
    "shutdown": "dim",
    "initializing": "cyan",
    "gps_wait": "cyan",
    "gps_acquired": "cyan",
    "ready": "green",
    "tracking": "yellow",
    "degraded": "dark_orange",
    "error": "red",
    "offline": "red",
}


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m:02d}m"


class AntennaStatusPopup(PopupBase):
    """Interactive antenna client list with detail view."""

    ROW_COUNT = 22
    CLOSE_KEY = "a"
    POPUP_NAME = "antennas"
    ESC_CLOSES = False

    DEFAULT_CSS = """
    AntennaStatusPopup {
        width: 72;
        height: auto;
        max-height: 24;
        background: $surface;
        border: solid green;
        border-title-color: green;
        border-title-style: bold;
        padding: 0 1;
        layer: overlay;
        dock: left;
        margin: 2 0 0 0;
    }
    .popup-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.border_title = "ANTENNAS (A to close)"
        self._antenna_manager = None
        self._mode = "list"  # "list", "detail", "passes", or "track"
        self._selected_index = 0
        self._clients_cache = []
        self._satellite_data = None
        self._passes = []
        self._passes_selected = 0
        self._passes_scroll = 0
        self._passes_source_mode = "list"
        self._passes_error = ""
        self._passes_client_id = ""
        self._passes_lat = 0.0
        self._passes_lon = 0.0
        self._track_sats = []
        self._track_selected = 0
        self._track_scroll = 0
        self._track_error = ""
        self._track_client_id = ""
        self._track_source_mode = "list"
        self._track_lat = 0.0
        self._track_lon = 0.0

    def set_manager(self, manager):
        self._antenna_manager = manager

    def set_satellite_data(self, satellite_data):
        """Set satellite data reference for pass computation."""
        self._satellite_data = satellite_data

    def _search_allowed(self) -> bool:
        return self._mode in ("list", "passes", "track")

    def _get_search_text(self, index: int) -> str:
        if self._mode == "track":
            if index < len(self._track_sats):
                return self._track_sats[index]["name"]
            return ""
        if self._mode == "passes":
            if index < len(self._passes):
                return self._passes[index]["name"]
            return ""
        if index < len(self._clients_cache):
            c = self._clients_cache[index]
            return f"{c.client_id} {self._get_state_str(c)} {c.hostname}"
        return ""

    def _get_state_str(self, client) -> str:
        if client.client_state_info:
            return client.client_state_info.state
        return client.status

    def _render_content(self):
        if not self._antenna_manager:
            lines = ["", "",
                      "  [dim]Server not running[/dim]"]
            self._update_labels(lines)
            return

        self._clients_cache = self._antenna_manager.get_all_clients()

        if self._mode == "track":
            self._render_track()
        elif self._mode == "passes":
            self._render_passes()
        elif self._mode == "detail":
            self._render_detail()
        else:
            self._render_list()

    def _render_list(self):
        lines = []
        lines.append("")
        lines.append("")

        clients = self._clients_cache
        if not clients:
            lines.append("  [dim]No clients connected[/dim]")
            lines.append("")
            lines.append(f"  {self._render_search_bar()}")
            self._update_labels(lines)
            return

        # Filter
        filtered = [i for i in range(len(clients))
                     if self._match_search(self._get_search_text(i))]

        if filtered and self._selected_index not in filtered:
            self._selected_index = filtered[0]

        if not filtered:
            lines.append("  [dim]No matches[/dim]")
            lines.append("")
            lines.append(f"  {self._render_search_bar()}")
            self._update_labels(lines)
            return

        # Header
        lines.append("[bold]  ID            State       GPS              Sats  Tracking[/bold]")
        lines.append("  " + "\u2500" * 64)

        for i in filtered:
            c = clients[i]
            marker = ">" if i == self._selected_index else " "
            state = self._get_state_str(c)
            color = STATE_COLORS.get(state, "white")
            state_str = f"[{color}]{state:<10}[/{color}]"

            if c.gps:
                gps_str = f"{c.gps.lat:7.3f},{c.gps.lon:7.3f}"
            else:
                gps_str = "[dim]--[/dim]             "

            sats = "--"
            if c.client_gps_info and c.client_gps_info.fix:
                sats = str(c.client_gps_info.satellites)
            elif c.gps:
                sats = str(c.gps.satellites)

            if c.tracking and c.tracking.active:
                track_str = f"[yellow]{c.tracking.name or c.tracking.norad_id}[/yellow]"
            else:
                track_str = "[dim]idle[/dim]"

            lines.append(f"{marker} {c.client_id:<13} {state_str}  {gps_str}  {sats:>4}  {track_str}")

        lines.append("")
        lines.append(f"[dim]Up/Down:navigate  Enter:detail  c:center  p:passes  t:track[/dim]")
        lines.append(f"[dim]r:refresh  s:stop[/dim]  {self._render_search_bar()}")

        self._update_labels(lines)

    def _render_detail(self):
        lines = []
        clients = self._clients_cache
        if self._selected_index >= len(clients):
            self._mode = "list"
            self._render_list()
            return

        c = clients[self._selected_index]
        state = self._get_state_str(c)
        color = STATE_COLORS.get(state, "white")

        # Duration since state change
        state_dur = ""
        if c.client_state_info and c.client_state_info.state_since > 0:
            elapsed = time.time() - c.client_state_info.state_since
            state_dur = f" ({_format_duration(elapsed)})"

        lines.append(f"[bold green]CLIENT: {c.client_id}[/bold green]  [dim]Esc:back[/dim]")
        lines.append("")
        lines.append(f"  State:     [{color}]{state}[/{color}]{state_dur}")
        lines.append(f"  Hostname:  {c.hostname}")

        if c.client_state_info and c.client_state_info.error_detail:
            lines.append(f"  Error:     [red]{c.client_state_info.error_detail}[/red]")

        # Read uptime from the client object directly
        client_full = self._antenna_manager.get_client(c.client_id)
        uptime_val = client_full.uptime_s if client_full else 0
        uptime_str = _format_duration(uptime_val) if uptime_val else "?"
        lines.append(f"  Uptime:    {uptime_str}")
        lines.append("")

        # GPS
        if c.gps:
            gps_extra = ""
            if c.client_gps_info:
                parts = []
                parts.append(f"{c.client_gps_info.satellites} sats")
                if c.client_gps_info.hdop is not None:
                    parts.append(f"HDOP {c.client_gps_info.hdop:.1f}")
                gps_extra = f"  ({', '.join(parts)})"
            lines.append(f"  GPS:       {c.gps.lat:.3f}, {c.gps.lon:.3f}{gps_extra}")
        else:
            lines.append("  GPS:       [dim]no fix[/dim]")

        # IMU
        if c.client_imu_info:
            imu = c.client_imu_info
            lines.append(f"  IMU:       R:{imu.roll:.1f}  P:{imu.pitch:.1f}  Y:{imu.yaw:.1f}")
        else:
            lines.append("  IMU:       [dim]--[/dim]")

        # Tracking
        if c.tracking and c.tracking.active:
            track_label = c.tracking.name or str(c.tracking.norad_id)
            extra = ""
            if client_full and (client_full.tracking_az or client_full.tracking_el):
                extra = f"  az:{client_full.tracking_az:.1f} el:{client_full.tracking_el:.1f}"
            lines.append(f"  Tracking:  [yellow]{track_label}[/yellow]{extra}")
        else:
            lines.append("  Tracking:  [dim]idle[/dim]")

        lines.append("")
        lines.append("  [dim]c:center  p:passes  t:track  r:refresh  s:stop[/dim]")

        self._update_labels(lines)

    def _center_on_selected(self):
        """Center globe on selected antenna's GPS position."""
        clients = self._clients_cache
        if not clients or self._selected_index >= len(clients):
            return
        c = clients[self._selected_index]
        if c.gps:
            self.post_message(CenterOnLocation(c.gps.lat, c.gps.lon, 1.8))

    def _show_passes(self):
        """Compute and show passes for favorites from selected antenna's GPS."""
        clients = self._clients_cache
        if not clients or self._selected_index >= len(clients):
            return
        c = clients[self._selected_index]
        self._passes_source_mode = self._mode
        self._passes = []
        self._passes_selected = 0
        self._passes_scroll = 0
        self._passes_error = ""
        self._passes_client_id = c.client_id

        if not c.gps:
            self._passes_error = "No GPS fix on this client."
            self._mode = "passes"
            self._render_content()
            return

        self._passes_lat = c.gps.lat
        self._passes_lon = c.gps.lon

        favorites = config.favorites
        if not favorites:
            self._passes_error = "No favorites. Use Favorites (B) to add satellites."
            self._mode = "passes"
            self._render_content()
            return

        satellite_data = self._satellite_data
        if not satellite_data or len(satellite_data) == 0:
            self._passes_error = "No satellites loaded. Press S to load first."
            self._mode = "passes"
            self._render_content()
            return

        from satellite.pass_prediction import predict_all_favorites
        self._passes = predict_all_favorites(
            favorites, satellite_data,
            c.gps.lat, c.gps.lon,
            max_per_sat=config.get_option("passes_per_sat"),
            max_total=config.get_option("max_passes"),
        )
        self._mode = "passes"
        self._render_content()

    def _render_passes(self):
        """Render pass prediction table for selected antenna."""
        lines = []

        if self._passes_error:
            lines.append(f"[bold green]PASSES FROM {self._passes_client_id}[/bold green]")
            lines.append("")
            lines.append(f"  [red]{self._passes_error}[/red]")
            lines.append("")
            lines.append("[dim]Esc:back[/dim]")
            self._update_labels(lines)
            return

        lines.append(
            f"[bold green]PASSES FROM {self._passes_client_id}[/bold green]  "
            f"({self._passes_lat:.2f}, {self._passes_lon:.2f})  Next 24h"
        )

        now = datetime.now(timezone.utc)

        filtered = [i for i in range(len(self._passes))
                     if self._match_search(self._get_search_text(i))]

        if filtered and self._passes_selected not in filtered:
            self._passes_selected = filtered[0]

        # Precompute ETA
        eta_plain = []
        eta_in_sight = []
        for p in self._passes:
            if p["rise"] <= now <= p["set"]:
                eta_plain.append("IN SIGHT")
                eta_in_sight.append(True)
            else:
                eta_plain.append(self._format_eta(p["rise"], now))
                eta_in_sight.append(False)

        # Column widths
        if filtered:
            name_w = max(min(len(self._passes[i]["name"]), 25) for i in filtered)
        else:
            name_w = 9
        name_w = max(name_w, 9)
        eta_w = max((len(eta_plain[i]) for i in filtered), default=3)
        eta_w = max(eta_w, 3)

        header = f"   {'Satellite':<{name_w}}  {'ETA':>{eta_w}}  {'Rise':>8}  {'MaxEl':>5}  {'Set':>8}  {'Dur':>5}"
        sep = f"   {'─' * name_w}  {'─' * eta_w}  {'─' * 8}  {'─' * 5}  {'─' * 8}  {'─' * 5}"
        lines.append(header)
        lines.append(sep)

        if not filtered:
            if self._passes:
                lines.append("  [dim]No matches[/dim]")
            else:
                lines.append("  [dim]No passes found in next 24h[/dim]")
        else:
            visible_rows = 14
            try:
                sel_pos = filtered.index(self._passes_selected)
            except ValueError:
                sel_pos = 0
            if sel_pos < self._passes_scroll:
                self._passes_scroll = sel_pos
            elif sel_pos >= self._passes_scroll + visible_rows:
                self._passes_scroll = sel_pos - visible_rows + 1

            window = filtered[self._passes_scroll:self._passes_scroll + visible_rows]
            for i in window:
                p = self._passes[i]
                marker = ">" if i == self._passes_selected else " "
                name = p["name"]
                if len(name) > 25:
                    name = name[:24] + "~"
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

                line = f"{marker}  {name:<{name_w}}  {display_eta}  {rise_str:>8}  {max_el:>5.1f}  {set_str:>8}  {dur_str:>5}"
                lines.append(line)

            if len(filtered) > visible_rows:
                lines.append(f"  [dim]{len(filtered)} passes total[/dim]")

        lines.append("")
        lines.append(f"[dim]Up/Down:scroll  Esc:back[/dim]  {self._render_search_bar()}")

        self._update_labels(lines)

    @staticmethod
    def _format_eta(rise_dt, now_dt):
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

    def _move_passes_selection(self, direction):
        if not self._passes:
            return
        filtered = [i for i in range(len(self._passes))
                     if self._match_search(self._get_search_text(i))]
        if not filtered:
            return
        try:
            pos = filtered.index(self._passes_selected)
        except ValueError:
            pos = 0
        pos = (pos + direction) % len(filtered)
        self._passes_selected = filtered[pos]
        self._render_content()

    def _do_refresh(self):
        clients = self._clients_cache
        if not clients or self._selected_index >= len(clients):
            return
        cid = clients[self._selected_index].client_id
        self._antenna_manager.request_status(cid)

    def _do_stop(self):
        clients = self._clients_cache
        if not clients or self._selected_index >= len(clients):
            return
        cid = clients[self._selected_index].client_id
        self._antenna_manager.push_stop(cid)

    def _show_track(self):
        """Compute and show satellites currently visible from selected antenna's GPS."""
        clients = self._clients_cache
        if not clients or self._selected_index >= len(clients):
            return
        c = clients[self._selected_index]
        self._track_source_mode = self._mode
        self._track_sats = []
        self._track_selected = 0
        self._track_scroll = 0
        self._track_error = ""
        self._track_client_id = c.client_id

        if not c.gps:
            self._track_error = "No GPS fix on this client."
            self._mode = "track"
            self._render_content()
            return

        self._track_lat = c.gps.lat
        self._track_lon = c.gps.lon

        satellite_data = self._satellite_data
        if not satellite_data or len(satellite_data) == 0:
            self._track_error = "No satellites loaded. Press S to load first."
            self._mode = "track"
            self._render_content()
            return

        from satellite.pass_prediction import find_visible_now
        self._track_sats = find_visible_now(
            satellite_data, c.gps.lat, c.gps.lon,
            favorites=config.favorites,
        )
        self._mode = "track"
        self._render_content()

    def _render_track(self):
        """Render list of satellites currently visible from selected antenna."""
        lines = []

        if self._track_error:
            lines.append(f"[bold green]TRACK FROM {self._track_client_id}[/bold green]")
            lines.append("")
            lines.append(f"  [red]{self._track_error}[/red]")
            lines.append("")
            lines.append("[dim]Esc:back[/dim]")
            self._update_labels(lines)
            return

        count = len(self._track_sats)
        lines.append(
            f"[bold green]TRACK FROM {self._track_client_id}[/bold green]  "
            f"({self._track_lat:.2f}, {self._track_lon:.2f})  {count} visible"
        )

        now = datetime.now(timezone.utc)

        filtered = [i for i in range(count)
                     if self._match_search(self._get_search_text(i))]

        if filtered and self._track_selected not in filtered:
            self._track_selected = filtered[0]

        # Column widths
        if filtered:
            name_w = max(min(len(self._track_sats[i]["name"]), 25) for i in filtered)
        else:
            name_w = 9
        name_w = max(name_w, 9)
        el_w = 5

        header = f"   {'Satellite':<{name_w}}  {'El':>{el_w}}  {'Rise':>8}  {'MaxEl':>5}  {'Set':>8}  {'Dur':>5}"
        sep = f"   {'─' * name_w}  {'─' * el_w}  {'─' * 8}  {'─' * 5}  {'─' * 8}  {'─' * 5}"
        lines.append(header)
        lines.append(sep)

        if not filtered:
            if self._track_sats:
                lines.append("  [dim]No matches[/dim]")
            else:
                lines.append("  [dim]No satellites in sight[/dim]")
        else:
            visible_rows = 10
            try:
                sel_pos = filtered.index(self._track_selected)
            except ValueError:
                sel_pos = 0
            if sel_pos < self._track_scroll:
                self._track_scroll = sel_pos
            elif sel_pos >= self._track_scroll + visible_rows:
                self._track_scroll = sel_pos - visible_rows + 1

            window = filtered[self._track_scroll:self._track_scroll + visible_rows]
            for i in window:
                s = self._track_sats[i]
                marker = ">" if i == self._track_selected else " "
                name = s["name"]
                if len(name) > 25:
                    name = name[:24] + "~"
                name_padded = f"{name:<{name_w}}"
                if s["is_favorite"]:
                    name_padded = f"[yellow]{name_padded}[/yellow]"
                rise_str = s["rise"].strftime("%H:%M:%S")
                set_str = s["set"].strftime("%H:%M:%S")
                remaining_s = max(0, int((s["set"] - now).total_seconds()))
                rem_m = remaining_s // 60
                rem_sec = remaining_s % 60
                rem_str = f"{rem_m}:{rem_sec:02d}"

                line = (
                    f"{marker}  {name_padded}  {s['el']:>{el_w}.1f}  {rise_str:>8}"
                    f"  {s['max_el']:>5.1f}  {set_str:>8}  {rem_str:>5}"
                )
                lines.append(line)

            if len(filtered) > visible_rows:
                lines.append(f"  [dim]{len(filtered)} total[/dim]")

        lines.append("")
        lines.append(f"[dim]Up/Down:scroll  Enter:track  Esc:back[/dim]  {self._render_search_bar()}")

        self._update_labels(lines)

    def _move_track_selection(self, direction):
        if not self._track_sats:
            return
        filtered = [i for i in range(len(self._track_sats))
                     if self._match_search(self._get_search_text(i))]
        if not filtered:
            return
        try:
            pos = filtered.index(self._track_selected)
        except ValueError:
            pos = 0
        pos = (pos + direction) % len(filtered)
        self._track_selected = filtered[pos]
        self._render_content()

    def _do_track_satellite(self):
        """Send track command for selected satellite to the antenna client."""
        if not self._track_sats:
            return
        filtered = [i for i in range(len(self._track_sats))
                     if self._match_search(self._get_search_text(i))]
        if self._track_selected not in filtered:
            return
        sat = self._track_sats[self._track_selected]
        omm = sat["omm"]
        rise_str = sat["rise"].isoformat()
        set_str = sat["set"].isoformat()
        self._antenna_manager.push_track(self._track_client_id, omm, rise_str, set_str)

    def _handle_key(self, event):
        key = event.key

        if self._mode == "track":
            if key == "escape":
                self._mode = self._track_source_mode
                self._render_content()
                event.stop()
                event.prevent_default()
            elif key == "up":
                self._move_track_selection(-1)
                event.stop()
                event.prevent_default()
            elif key == "down":
                self._move_track_selection(1)
                event.stop()
                event.prevent_default()
            elif key == "enter":
                self._do_track_satellite()
                event.stop()
                event.prevent_default()
            return

        if self._mode == "passes":
            if key == "escape":
                self._mode = self._passes_source_mode
                self._render_content()
                event.stop()
                event.prevent_default()
            elif key == "up":
                self._move_passes_selection(-1)
                event.stop()
                event.prevent_default()
            elif key == "down":
                self._move_passes_selection(1)
                event.stop()
                event.prevent_default()
            return

        if self._mode == "detail":
            if key == "escape":
                self._mode = "list"
                self._render_content()
                event.stop()
                event.prevent_default()
            elif key == "c":
                self._center_on_selected()
                event.stop()
                event.prevent_default()
            elif key == "p":
                self._show_passes()
                event.stop()
                event.prevent_default()
            elif key == "t":
                self._show_track()
                event.stop()
                event.prevent_default()
            elif key == "r":
                self._do_refresh()
                event.stop()
                event.prevent_default()
            elif key == "s":
                self._do_stop()
                event.stop()
                event.prevent_default()
            return

        # List mode
        if key == "escape":
            self.request_close()
            event.stop()
            event.prevent_default()
        elif key == "up":
            self._move_selection(-1)
            event.stop()
            event.prevent_default()
        elif key == "down":
            self._move_selection(1)
            event.stop()
            event.prevent_default()
        elif key == "enter":
            self._enter_detail()
            event.stop()
            event.prevent_default()
        elif key == "c":
            self._center_on_selected()
            event.stop()
            event.prevent_default()
        elif key == "p":
            self._show_passes()
            event.stop()
            event.prevent_default()
        elif key == "t":
            self._show_track()
            event.stop()
            event.prevent_default()
        elif key == "r":
            self._do_refresh()
            event.stop()
            event.prevent_default()
        elif key == "s":
            self._do_stop()
            event.stop()
            event.prevent_default()

    def _move_selection(self, direction: int):
        clients = self._clients_cache
        if not clients:
            return
        count = len(clients)
        self._selected_index = (self._selected_index + direction) % count
        self._render_content()

    def _enter_detail(self):
        clients = self._clients_cache
        if not clients or self._selected_index >= len(clients):
            return
        self._mode = "detail"
        self._render_content()
        self._do_refresh()
