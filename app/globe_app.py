"""Main GlobeApp Textual application."""

import time
from datetime import datetime, timezone, timedelta
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.containers import Container

from widgets import (
    OptionsMenu,
    TimeBox,
    MenuBar,
    GlobeDisplay,
    SearchPopup,
    SatellitesPopup,
    LocationsPopup,
    FavoritesPopup,
    PassesPopup,
    AntennaStatusPopup,
)
from widgets.messages import (
    PopupClosed,
    CenterOnLocation,
    TrackSatellite,
    SatellitesChanged,
    OptionsChanged,
    TimeChanged,
    TimeReset,
    TimeReverted,
    GlobeRedrawNeeded,
    RestoreView,
    LoadSatelliteCategory,
    AntennaStatusChanged,
)
from widgets.menu_bar import MenuItemSelected, MenuItemHighlighted, MenuDismissed, MENU_ITEMS
from config_manager import SATELLITE_TYPES


class GlobeApp(App):
    """Textual TUI application for interactive globe viewer."""

    CSS = """
    Screen {
        background: $surface;
        layers: base overlay;
    }

    MenuBar {
        dock: top;
        height: 2;
        width: 100%;
        layer: overlay;
        background: transparent;
        color: $text;
    }

    #main-area {
        height: 1fr;
        width: 100%;
        layer: base;
    }

    OptionsMenu {
        dock: left;
        margin: 2 0 0 0;
    }

    TimeBox {
        dock: left;
        margin: 2 0 0 0;
    }

    SearchPopup {
        dock: left;
        margin: 2 0 0 0;
    }

    #globe-container {
        width: 100%;
        height: 100%;
        layer: base;
        border: solid green;
        margin: 2 0 0 0;
    }

    GlobeDisplay {
        width: 100%;
        height: 100%;
    }

    SatellitesPopup {
        dock: left;
        margin: 2 0 0 0;
    }

    LocationsPopup {
        dock: left;
        margin: 2 0 0 0;
    }

    FavoritesPopup {
        dock: left;
        margin: 2 0 0 0;
    }

    PassesPopup {
        dock: left;
        margin: 2 0 0 0;
    }

    AntennaStatusPopup {
        dock: left;
        margin: 2 0 0 0;
    }

    """

    TITLE = "Interactive Globe - Natural Earth Data"
    BINDINGS = [
        ("up", "navigate_up", "Up"),
        ("down", "navigate_down", "Down"),
        ("left", "navigate_left", "Left"),
        ("right", "navigate_right", "Right"),
        ("plus,equals", "zoom_in", "Zoom+"),
        ("minus", "zoom_out", "Zoom-"),
        ("r", "reset", "Reset"),
        ("o", "toggle_options", "Options"),
        ("s", "toggle_satellites", "Satellites"),
        ("l", "toggle_locations", "Locations"),
        ("b", "toggle_favorites", "Favorites"),
        ("p", "toggle_passes", "Passes"),
        ("t", "toggle_time", "Time"),
        ("slash", "search_satellite", "Search"),
        ("a", "toggle_antennas", "Antennas"),
        ("q", "quit", "Quit"),
    ]

    options_visible = reactive(False)
    time_visible = reactive(False)
    search_visible = reactive(False)
    satellites_visible = reactive(False)
    locations_visible = reactive(False)
    favorites_visible = reactive(False)
    passes_visible = reactive(False)
    antennas_visible = reactive(False)

    @property
    def _any_popup_visible(self) -> bool:
        return (self.search_visible or self.satellites_visible or
                self.locations_visible or self.favorites_visible or
                self.passes_visible or self.antennas_visible)

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _get_effective_time(self) -> datetime:
        if not self.custom_time_active or self.custom_time is None:
            return self._utc_now()
        if self.custom_time_freeze:
            return self.custom_time
        if self.custom_time_anchor_epoch is None:
            return self.custom_time
        delta = time.time() - self.custom_time_anchor_epoch
        return self.custom_time + timedelta(seconds=delta)

    def _set_custom_time(self, dt: datetime, freeze: bool):
        self.custom_time_active = True
        self.custom_time = dt.astimezone(timezone.utc)
        self.custom_time_freeze = bool(freeze)
        self.custom_time_anchor_epoch = time.time()

    def _format_time(self, dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y %m %d %H:%M:%S UTC")

    def _build_status_line(self):
        utc_now = self._utc_now()
        current_str = self._format_time(utc_now)
        line = f"Time: {current_str}"
        if self.custom_time_active and self.custom_time is not None:
            custom_dt = self._get_effective_time()
            custom_str = self._format_time(custom_dt)
            if self.custom_time_freeze:
                custom_str = f"[#7ecbff]{custom_str}[/#7ecbff]"
            else:
                custom_str = f"[yellow]{custom_str}[/yellow]"
            line = f"{line}  Custom: {custom_str}"

        if hasattr(self, 'globe_display') and self.globe_display.is_tracking():
            sat_name = self.globe_display.tracked_satellite_name
            sat_type = self.globe_display.tracked_satellite_type
            sat_color = SATELLITE_TYPES.get(sat_type, {}).get('color', 'yellow')
            line = f"{line}  [orange1]Focused:[/orange1] [{sat_color}]{sat_name}[/{sat_color}]"

        return line

    def _refresh_toolbar(self):
        if hasattr(self, "menu_bar"):
            self.menu_bar.set_status(self._build_status_line())

    def _refresh_passes_display(self):
        if self.passes_visible:
            self.passes_popup._render_content()

    def _refresh_top_right_panel(self):
        if hasattr(self, "options_menu"):
            self.options_menu.display = self.options_visible
        if hasattr(self, "time_box"):
            self.time_box.display = self.time_visible

    def __init__(self, segments, segment_bounds, river_segments, river_bounds,
                 city_coords, city_names,
                 segments_coarse=None, segment_bounds_coarse=None,
                 satellite_framerate=1, antenna_manager=None):
        super().__init__()

        self.segments = segments
        self.segment_bounds = segment_bounds
        self.river_segments = river_segments
        self.river_bounds = river_bounds
        self.city_coords = city_coords
        self.city_names = city_names
        self.segments_coarse = segments_coarse
        self.segment_bounds_coarse = segment_bounds_coarse
        self.satellite_framerate = satellite_framerate
        self.antenna_manager = antenna_manager

        self.base_rotation_step = 10.0
        self.zoom_factor = 0.2
        self.custom_time_active = False
        self.custom_time = None
        self.custom_time_freeze = False
        self.custom_time_anchor_epoch = None
        self._saved_time_state = None
        self._menu_previewing: str = ""  # popup_name of currently previewed popup

    # ── Popup name -> (flag_name, widget_attr) mapping ──

    _POPUP_MAP = {
        "satellites": ("satellites_visible", "satellites_popup"),
        "favorites": ("favorites_visible", "favorites_popup"),
        "passes": ("passes_visible", "passes_popup"),
        "search": ("search_visible", "search_popup"),
        "options": ("options_visible", "options_menu"),
        "time": ("time_visible", "time_box"),
        "locations": ("locations_visible", "locations_popup"),
        "antennas": ("antennas_visible", "antenna_popup"),
    }

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        frame_interval = 1.0 / max(1, self.satellite_framerate)

        self.globe_display = GlobeDisplay(
            self.segments, self.segment_bounds,
            self.river_segments, self.river_bounds,
            self.city_coords, self.city_names,
            segments_coarse=self.segments_coarse,
            segment_bounds_coarse=self.segment_bounds_coarse,
            frame_interval=frame_interval,
            satellite_data=None,
        )
        self.menu_bar = MenuBar()
        self.options_menu = OptionsMenu()
        self.options_menu.display = False

        self.satellites_popup = SatellitesPopup()
        self.satellites_popup.display = False

        # Pass references to globe display
        self.globe_display._options_menu = self.options_menu
        self.globe_display._satellites_popup = self.satellites_popup
        self.globe_display._antenna_manager = self.antenna_manager
        self.globe_display.time_provider = self._get_effective_time
        self.time_box = TimeBox()
        self.time_box.display = False
        self.search_popup = SearchPopup([], [])
        self.search_popup.display = False

        self.locations_popup = LocationsPopup()
        self.locations_popup.display = False

        self.favorites_popup = FavoritesPopup()
        self.favorites_popup.display = False

        self.passes_popup = PassesPopup()
        self.passes_popup.display = False

        self.antenna_popup = AntennaStatusPopup()
        self.antenna_popup.display = False
        if self.antenna_manager:
            self.antenna_popup.set_manager(self.antenna_manager)

        yield self.menu_bar
        with Container(id="main-area"):
            with Container(id="globe-container"):
                yield self.globe_display
        yield self.options_menu
        yield self.time_box
        yield self.satellites_popup
        yield self.locations_popup
        yield self.favorites_popup
        yield self.passes_popup
        yield self.antenna_popup
        yield self.search_popup

    def on_mount(self):
        """Set up periodic updates for animation."""
        self.set_interval(0.01, self.animate_orbitals)
        self.set_interval(1.0, self._refresh_toolbar)
        self.set_interval(1.0, self._refresh_passes_display)
        if hasattr(self, "time_box"):
            self.time_box.set_datetime(self._utc_now())
            self.time_box.set_freeze(self.custom_time_freeze)
        self._refresh_toolbar()
        self._refresh_top_right_panel()

        self.call_later(self._load_default_satellites)
        self._apply_default_location()

    def _load_default_satellites(self):
        if hasattr(self, 'satellites_popup'):
            self.satellites_popup.load_defaults()

    def _apply_default_location(self):
        from config_manager import config
        default_loc = config.get_default_location()
        if default_loc is not None:
            self.globe_display.center_lat = default_loc["lat"]
            self.globe_display.center_lon = default_loc["lon"]
            self.globe_display.zoom = 1.8

    def animate_orbitals(self):
        self.globe_display.animate_frame()

    # ── Popup visibility helpers ──

    def _show_popup(self, popup, flag_name):
        setattr(self, flag_name, True)
        popup.display = True
        popup.focus()

    def _hide_popup(self, popup, flag_name):
        setattr(self, flag_name, False)
        popup.display = False
        self.globe_display.focus()

    # ── Menu preview helpers ──

    def _open_popup_no_focus(self, popup_name: str) -> bool:
        """Open a popup without focusing it. Returns True if opened successfully."""
        entry = self._POPUP_MAP.get(popup_name)
        if not entry:
            return False
        flag_name, widget_attr = entry
        widget = getattr(self, widget_attr, None)
        if widget is None:
            return False

        # Already visible -- treat as success (idempotent)
        if getattr(self, flag_name, False):
            return True

        # Per-popup setup (mirrors the action_toggle_* open paths, minus .focus())
        if popup_name == "satellites":
            self.satellites_popup.refresh_categories()
            self.satellites_popup._render_content()

        elif popup_name == "favorites":
            self.favorites_popup.set_satellite_data(
                self.globe_display.satellite_data,
                getattr(self.globe_display, 'satellite_types_list', []),
                getattr(self.globe_display, 'type_indices', None),
                self._get_effective_time,
            )
            self.favorites_popup._render_content()

        elif popup_name == "passes":
            self.passes_popup.set_satellite_data(self.globe_display.satellite_data)
            self.passes_popup.compute_passes()
            self.globe_display._passes_data = self.passes_popup._passes
            self.passes_popup._render_content()

        elif popup_name == "search":
            satellite_data = self.globe_display.satellite_data
            if satellite_data is None or len(satellite_data) == 0:
                return False
            self.search_popup.satellites = satellite_data
            self.search_popup.satellite_types_list = getattr(self.globe_display, 'satellite_types_list', [])
            self.search_popup.query = ""
            self.search_popup.results = []
            self.search_popup.selected_index = 0
            self.search_popup.set_globe_state(
                self.globe_display.center_lat,
                self.globe_display.center_lon,
                self.globe_display.zoom,
                getattr(self.globe_display, 'type_indices', None),
                self._get_effective_time,
            )
            self.search_popup.save_view()
            self.search_popup._render_content()

        elif popup_name == "options":
            pass  # No special setup needed

        elif popup_name == "time":
            if not hasattr(self, "time_box") or self.time_box is None or not self.time_box.is_mounted:
                return False
            self._saved_time_state = {
                'active': self.custom_time_active,
                'time': self.custom_time,
                'freeze': self.custom_time_freeze,
                'anchor': self.custom_time_anchor_epoch,
            }
            if self.custom_time_active and self.custom_time is not None:
                dt = self._get_effective_time()
                freeze = self.custom_time_freeze
            else:
                dt = self._utc_now()
                freeze = False
            self.time_box._editing_time = False
            self.time_box._buffer = ""
            self.time_box._selected_row = 0
            self.time_box._selected_field = 0
            self.time_box.set_datetime(dt)
            self.time_box.set_freeze(freeze)
            self.time_box.set_custom(self.custom_time_active and self.custom_time is not None)

        elif popup_name == "locations":
            self.locations_popup._render_content()

        elif popup_name == "antennas":
            self.antenna_popup.set_satellite_data(self.globe_display.satellite_data)
            self.antenna_popup._render_content()

        setattr(self, flag_name, True)
        widget.display = True
        self._refresh_top_right_panel()
        self._refresh_toolbar()
        return True

    def _preview_popup(self, popup_name: str) -> None:
        """Open a popup as a menu preview (no focus transfer)."""
        if self._menu_previewing == popup_name:
            return  # Already previewing this one
        if self._menu_previewing:
            self._close_preview()
        if self._open_popup_no_focus(popup_name):
            self._menu_previewing = popup_name
            self.menu_bar.set_active_popup(popup_name)

    def _close_preview(self) -> None:
        """Close the currently previewed popup."""
        if not self._menu_previewing:
            return
        entry = self._POPUP_MAP.get(self._menu_previewing)
        if entry:
            flag_name, widget_attr = entry
            widget = getattr(self, widget_attr, None)
            if widget is not None:
                setattr(self, flag_name, False)
                widget.display = False
        self._menu_previewing = ""
        self.menu_bar.clear_active()
        self._refresh_top_right_panel()
        self._refresh_toolbar()

    def _commit_preview(self) -> None:
        """Transfer focus to the currently previewed popup (Enter from menu)."""
        if not self._menu_previewing:
            return
        entry = self._POPUP_MAP.get(self._menu_previewing)
        if entry:
            _, widget_attr = entry
            widget = getattr(self, widget_attr, None)
            if widget is not None:
                widget.focus()
        # No longer a preview -- it's committed. Keep menu_bar active style.
        self._menu_previewing = ""

    def _close_all_popups(self) -> None:
        """Close every open popup. Does not touch menu mode or focus."""
        self._menu_previewing = ""
        for popup_name, (flag_name, widget_attr) in self._POPUP_MAP.items():
            if getattr(self, flag_name, False):
                setattr(self, flag_name, False)
                widget = getattr(self, widget_attr, None)
                if widget is not None:
                    widget.display = False
        self.menu_bar.clear_active()
        self._refresh_top_right_panel()
        self._refresh_toolbar()

    # ── Message handlers ──

    def on_popup_closed(self, message: PopupClosed) -> None:
        name = message.popup_name
        mapping = {
            "options": ("options_visible", self.options_menu),
            "satellites": ("satellites_visible", self.satellites_popup),
            "locations": ("locations_visible", self.locations_popup),
            "favorites": ("favorites_visible", self.favorites_popup),
            "passes": ("passes_visible", self.passes_popup),
            "antennas": ("antennas_visible", self.antenna_popup),
            "search": ("search_visible", self.search_popup),
            "time": ("time_visible", self.time_box),
        }
        if name in mapping:
            flag_name, popup = mapping[name]
            setattr(self, flag_name, False)
            popup.display = False
        self._menu_previewing = ""
        self._refresh_toolbar()
        self._refresh_top_right_panel()

        if hasattr(self, "menu_bar") and self.menu_bar.in_menu_mode:
            # Popup was opened via menu Enter -- return to menu bar
            self.menu_bar.clear_active()
            self.menu_bar.focus()
            item = MENU_ITEMS[self.menu_bar._highlighted_index]
            self.menu_bar.set_status(f"[dim]{item.group}[/dim]  {item.description}")
            self._preview_popup(item.popup_name)
        else:
            if hasattr(self, "menu_bar"):
                self.menu_bar.clear_active()
                self.menu_bar.leave_menu_mode()
            self.globe_display.focus()

    def on_menu_item_selected(self, message: MenuItemSelected) -> None:
        item = message.item
        if self._menu_previewing == item.popup_name:
            # Preview is already open -- commit focus to it
            self._commit_preview()
        elif self._menu_previewing:
            # Different popup previewed -- close it, open + commit the new one
            self._close_preview()
            if self._open_popup_no_focus(item.popup_name):
                self.menu_bar.set_active_popup(item.popup_name)
                entry = self._POPUP_MAP.get(item.popup_name)
                if entry:
                    widget = getattr(self, entry[1], None)
                    if widget:
                        widget.focus()
        else:
            # No preview active (e.g. hotkey from menu mode) -- open + focus
            if self._open_popup_no_focus(item.popup_name):
                self.menu_bar.set_active_popup(item.popup_name)
                entry = self._POPUP_MAP.get(item.popup_name)
                if entry:
                    widget = getattr(self, entry[1], None)
                    if widget:
                        widget.focus()

    def on_menu_item_highlighted(self, message: MenuItemHighlighted) -> None:
        item = message.item
        self.menu_bar.set_status(f"[dim]{item.group}[/dim]  {item.description}")
        self._preview_popup(item.popup_name)

    def on_menu_dismissed(self, message: MenuDismissed) -> None:
        self._close_preview()
        self.menu_bar.leave_menu_mode()
        self._refresh_toolbar()
        self.globe_display.focus()

    def on_center_on_location(self, message: CenterOnLocation) -> None:
        self.globe_display.center_lat = message.lat
        self.globe_display.center_lon = message.lon
        self.globe_display.zoom = message.zoom

    def on_track_satellite(self, message: TrackSatellite) -> None:
        self.globe_display.set_tracked_satellite(message.idx, message.name, message.sat_type)
        self._refresh_toolbar()

    def on_satellites_changed(self, message: SatellitesChanged) -> None:
        from satellite.propagator import build_satrec_array, clear_satrec_cache

        self.globe_display.satellite_data = message.satellite_data
        self.globe_display.satellite_types_list = message.satellite_types_list
        self.globe_display.type_indices = message.type_indices

        # Clear stale cache and rebuild SatrecArray for fast vectorized propagation
        clear_satrec_cache()
        if message.satellite_data:
            build_satrec_array(message.satellite_data, message.type_indices)

        # Update search popup data
        if hasattr(self, 'search_popup') and self.search_popup:
            self.search_popup.satellites = message.satellite_data if message.satellite_data else []
            self.search_popup.satellite_types_list = message.satellite_types_list

        # Update favorites popup data
        if hasattr(self, 'favorites_popup') and self.favorites_popup:
            self.favorites_popup.set_satellite_data(
                message.satellite_data,
                message.satellite_types_list,
                message.type_indices,
                self._get_effective_time,
            )
            if self.favorites_popup.display:
                self.favorites_popup._render_content()

        # Update passes popup data
        if hasattr(self, 'passes_popup') and self.passes_popup:
            self.passes_popup.set_satellite_data(message.satellite_data)

        # Update antenna popup data
        if hasattr(self, 'antenna_popup') and self.antenna_popup:
            self.antenna_popup.set_satellite_data(message.satellite_data)

        # Force redraw
        self.globe_display._needs_redraw = True
        self.globe_display._cached_output = None
        self.globe_display.render_globe()

    def on_load_satellite_category(self, message: LoadSatelliteCategory) -> None:
        sat_type = message.sat_type
        sp = self.satellites_popup
        for cat, types in sp.categories.items():
            if sat_type in types:
                sp._load_satellite_type(cat, sat_type)
                sp._rebuild_items()
                if sp.display:
                    sp._render_content()
                if self.favorites_popup.display:
                    self.favorites_popup._render_content()
                break

    def on_options_changed(self, message: OptionsChanged) -> None:
        self.globe_display.lod_ratio = self.options_menu.lod_ratio
        self.globe_display.rivers_ratio = self.options_menu.rivers_ratio
        self.globe_display.cities_ratio = self.options_menu.cities_ratio
        self.globe_display._needs_redraw = True
        self.globe_display._cached_output = None
        self.globe_display.render_globe()

    def on_time_changed(self, message: TimeChanged) -> None:
        self._set_custom_time(message.dt, message.freeze)
        self._refresh_toolbar()

    def on_time_reset(self, message: TimeReset) -> None:
        self.custom_time_active = False
        self.custom_time = None
        self.custom_time_freeze = False
        self.custom_time_anchor_epoch = None
        self._saved_time_state = None
        self._refresh_toolbar()
        self._refresh_top_right_panel()

    def on_time_reverted(self, message: TimeReverted) -> None:
        if self._saved_time_state is not None:
            self.custom_time_active = self._saved_time_state['active']
            self.custom_time = self._saved_time_state['time']
            self.custom_time_freeze = self._saved_time_state['freeze']
            self.custom_time_anchor_epoch = self._saved_time_state['anchor']
            self._saved_time_state = None
        self._refresh_toolbar()
        self._refresh_top_right_panel()

    def on_globe_redraw_needed(self, message: GlobeRedrawNeeded) -> None:
        self.globe_display._needs_redraw = True
        self.globe_display._cached_output = None
        self.globe_display.render_globe()

    def on_restore_view(self, message: RestoreView) -> None:
        self.globe_display.center_lat = message.lat
        self.globe_display.center_lon = message.lon
        self.globe_display.zoom = message.zoom

    # ── Action handlers (BINDINGS) ──

    def action_focus_next(self):
        """Override Textual's default Tab -> focus_next to drive menu bar instead."""
        if hasattr(self, "menu_bar") and self.menu_bar.in_menu_mode:
            if self._any_popup_visible or self.options_visible or self.time_visible :
                # Committed popup is open -- close it and return to menu bar
                self._close_all_popups()
                self.menu_bar.focus()
                item = MENU_ITEMS[self.menu_bar._highlighted_index]
                self.menu_bar.set_status(f"[dim]{item.group}[/dim]  {item.description}")
                self._preview_popup(item.popup_name)
                return
            # Menu bar focused, preview open -- full dismiss
            self.menu_bar.post_message(MenuDismissed())
            return
        if self._any_popup_visible or self.options_visible or self.time_visible :
            return
        self.menu_bar.enter_menu_mode()
        self.menu_bar.focus()

    def action_toggle_favorites(self):
        if self._any_popup_visible and not self.favorites_visible:
            return
        self.favorites_visible = not self.favorites_visible
        self.favorites_popup.display = self.favorites_visible
        if self.favorites_visible:
            self.favorites_popup.set_satellite_data(
                self.globe_display.satellite_data,
                getattr(self.globe_display, 'satellite_types_list', []),
                getattr(self.globe_display, 'type_indices', None),
                self._get_effective_time,
            )
            self.favorites_popup._render_content()
            self.favorites_popup.focus()
        else:
            self.globe_display.focus()
        self._refresh_toolbar()

    def action_toggle_passes(self):
        if self._any_popup_visible and not self.passes_visible:
            return
        self.passes_visible = not self.passes_visible
        self.passes_popup.display = self.passes_visible
        if self.passes_visible:
            self.passes_popup.set_satellite_data(self.globe_display.satellite_data)
            self.passes_popup.compute_passes()
            self.globe_display._passes_data = self.passes_popup._passes
            self.passes_popup._render_content()
            self.passes_popup.focus()
        else:
            self.globe_display.focus()
        self._refresh_toolbar()

    def action_toggle_options(self):
        if self._any_popup_visible:
            return
        self.options_visible = not self.options_visible
        self.options_menu.display = self.options_visible
        if self.options_visible:
            self.options_menu.focus()
        else:
            self.globe_display.focus()
        self._refresh_toolbar()
        self._refresh_top_right_panel()

    def action_toggle_satellites(self):
        if self._any_popup_visible and not self.satellites_visible:
            return
        self.satellites_visible = not self.satellites_visible
        self.satellites_popup.display = self.satellites_visible
        if self.satellites_visible:
            self.satellites_popup.refresh_categories()
            self.satellites_popup._render_content()
            self.satellites_popup.focus()
        else:
            self.globe_display.focus()
        self._refresh_toolbar()

    def action_toggle_locations(self):
        if self._any_popup_visible and not self.locations_visible:
            return
        self.locations_visible = not self.locations_visible
        self.locations_popup.display = self.locations_visible
        if self.locations_visible:
            self.locations_popup._render_content()
            self.locations_popup.focus()
        else:
            self.globe_display.focus()
        self._refresh_toolbar()

    def action_toggle_antennas(self):
        if self._any_popup_visible and not self.antennas_visible:
            return
        self.antennas_visible = not self.antennas_visible
        self.antenna_popup.display = self.antennas_visible
        if self.antennas_visible:
            self.antenna_popup.set_satellite_data(self.globe_display.satellite_data)
            self.antenna_popup._render_content()
            self.antenna_popup.focus()
        else:
            self.globe_display.focus()
        self._refresh_toolbar()

    def action_navigate_up(self):
        if self._any_popup_visible or self.options_visible or self.time_visible:
            return  # Handled by focused popup's on_key
        if self.globe_display.is_tracking():
            self.globe_display.unlock_camera()
        rotation_step = self.base_rotation_step / max(1.0, self.globe_display.zoom)
        self.globe_display.center_lat = min(90, self.globe_display.center_lat + rotation_step)

    def action_navigate_down(self):
        if self._any_popup_visible or self.options_visible or self.time_visible:
            return
        if self.globe_display.is_tracking():
            self.globe_display.unlock_camera()
        rotation_step = self.base_rotation_step / max(1.0, self.globe_display.zoom)
        self.globe_display.center_lat = max(-90, self.globe_display.center_lat - rotation_step)

    def action_navigate_left(self):
        if self._any_popup_visible or self.options_visible or self.time_visible:
            return
        if self.globe_display.is_tracking():
            self.globe_display.unlock_camera()
        rotation_step = self.base_rotation_step / max(1.0, self.globe_display.zoom)
        new_lon = (self.globe_display.center_lon - rotation_step) % 360
        if new_lon > 180:
            new_lon -= 360
        self.globe_display.center_lon = new_lon

    def action_navigate_right(self):
        if self._any_popup_visible or self.options_visible or self.time_visible:
            return
        if self.globe_display.is_tracking():
            self.globe_display.unlock_camera()
        rotation_step = self.base_rotation_step / max(1.0, self.globe_display.zoom)
        new_lon = (self.globe_display.center_lon + rotation_step) % 360
        if new_lon > 180:
            new_lon -= 360
        self.globe_display.center_lon = new_lon

    def action_zoom_in(self):
        if self._any_popup_visible:
            return
        self.globe_display.zoom = self.globe_display.zoom * (1 + self.zoom_factor)

    def action_zoom_out(self):
        if self._any_popup_visible:
            return
        self.globe_display.zoom = max(0.1, self.globe_display.zoom * (1 - self.zoom_factor))

    def action_reset(self):
        self.globe_display.center_lon = 0.0
        self.globe_display.center_lat = 0.0
        self.globe_display.zoom = 1.0

    def action_toggle_time(self):
        if self._any_popup_visible:
            return
        if not hasattr(self, "time_box") or self.time_box is None or not self.time_box.is_mounted:
            return
        self.time_visible = not self.time_visible
        if self.time_visible:
            # Save current state for escape key
            self._saved_time_state = {
                'active': self.custom_time_active,
                'time': self.custom_time,
                'freeze': self.custom_time_freeze,
                'anchor': self.custom_time_anchor_epoch
            }

            if self.custom_time_active and self.custom_time is not None:
                dt = self._get_effective_time()
                freeze = self.custom_time_freeze
                is_custom = True
            else:
                dt = self._utc_now()
                freeze = False
                is_custom = False

            self.time_box._editing_time = False
            self.time_box._buffer = ""
            self.time_box._selected_row = 0
            self.time_box._selected_field = 0

            self.time_box.set_datetime(dt)
            self.time_box.set_freeze(freeze)
            self.time_box.set_custom(is_custom)
            self.time_box.focus()
        else:
            # Closing via T key: apply time only if user modified it
            if self.time_box._dirty:
                self._set_custom_time(self.time_box.get_datetime(), self.time_box.get_freeze())
            elif self._saved_time_state:
                self.custom_time_active = self._saved_time_state['active']
                self.custom_time = self._saved_time_state['time']
                self.custom_time_freeze = self._saved_time_state['freeze']
                self.custom_time_anchor_epoch = self._saved_time_state['anchor']
            self._saved_time_state = None
            self.globe_display.focus()
        self.time_box.display = self.time_visible
        self._refresh_toolbar()
        self._refresh_top_right_panel()

    def action_select_option(self):
        # Enter key: only handle globe-level behavior if no popup is focused
        pass

    def action_search_satellite(self):
        if self._any_popup_visible:
            return

        satellite_data = self.globe_display.satellite_data
        if satellite_data is None or len(satellite_data) == 0:
            self.notify("No satellite data loaded. Press 's' to load satellites.", severity="warning")
            return

        self.search_visible = True
        self.search_popup.display = True
        self.search_popup.satellites = satellite_data
        self.search_popup.satellite_types_list = getattr(self.globe_display, 'satellite_types_list', [])
        self.search_popup.query = ""
        self.search_popup.results = []
        self.search_popup.selected_index = 0
        self.search_popup.set_globe_state(
            self.globe_display.center_lat,
            self.globe_display.center_lon,
            self.globe_display.zoom,
            getattr(self.globe_display, 'type_indices', None),
            self._get_effective_time,
        )
        self.search_popup.save_view()
        self.search_popup._render_content()
        self.search_popup.focus()
        self._refresh_toolbar()

    def on_key(self, event):
        """Minimal on_key: only handle F key for focus toggle outside popups."""
        key = event.key
        if self._any_popup_visible or self.options_visible or self.time_visible:
            return  # Popups handle their own keys

        if key == "f":
            if self.globe_display.is_tracking():
                if self.globe_display.is_camera_locked():
                    self.globe_display.clear_tracking()
                else:
                    self.globe_display.refocus_camera()
                self._refresh_toolbar()
            event.stop()
            return
