"""Interactive menu bar widget replacing the flat TopToolbar."""

from dataclasses import dataclass
from textual.widgets import Static, Label
from textual.message import Message
from textual.events import Key


@dataclass
class MenuItemDef:
    key: str
    label: str
    group: str
    group_color: str
    popup_name: str
    description: str
    action: str


MENU_ITEMS = [
    MenuItemDef("s", "Satellites", "", "cyan", "satellites",
                "Load/unload satellite categories, toggle visibility",
                "toggle_satellites"),
    MenuItemDef("b", "Favorites", "", "green", "favorites",
                "Bookmarked satellites, track, center",
                "toggle_favorites"),
    MenuItemDef("p", "Passes", "", "yellow", "passes",
                "Upcoming passes over default location",
                "toggle_passes"),
    MenuItemDef("/", "Search", "", "white", "search",
                "Find satellite by name",
                "search_satellite"),
    MenuItemDef("o", "Options", "", "dark_orange", "options",
                "LOD, rivers, cities, shadow settings",
                "toggle_options"),
    MenuItemDef("t", "Time", "", "magenta", "time",
                "Custom orbit time, freeze, reset",
                "toggle_time"),
    MenuItemDef("l", "Locations", "", "steel_blue", "locations",
                "Named locations, add/edit/delete",
                "toggle_locations"),
    MenuItemDef("a", "Antennas", "", "red", "antennas",
                "RPi antenna clients",
                "toggle_antennas"),
]


class MenuItemSelected(Message):
    """Posted when a menu item is activated."""

    def __init__(self, item: MenuItemDef) -> None:
        super().__init__()
        self.item = item


class MenuItemHighlighted(Message):
    """Posted when cursor moves to a menu item."""

    def __init__(self, item: MenuItemDef) -> None:
        super().__init__()
        self.item = item


class MenuDismissed(Message):
    """Posted when menu mode is exited."""
    pass


class MenuBar(Static):
    """Two-line interactive menu bar. Line 1: grouped items. Line 2: status or description."""

    can_focus = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._highlighted_index: int = -1  # -1 = globe mode
        self._active_popup: str = ""
        self._status_text: str = ""

    def compose(self):
        yield Label("", id="menu-items-row")
        yield Label("", id="menu-status-row")

    def on_mount(self):
        self._render_items()

    @property
    def in_menu_mode(self) -> bool:
        return self._highlighted_index >= 0

    def enter_menu_mode(self):
        self._highlighted_index = 0
        self._render_items()
        item = MENU_ITEMS[0]
        self.post_message(MenuItemHighlighted(item))

    def leave_menu_mode(self):
        self._highlighted_index = -1
        self._render_items()

    def move_highlight(self, direction: int):
        if self._highlighted_index < 0:
            return
        n = len(MENU_ITEMS)
        self._highlighted_index = (self._highlighted_index + direction) % n
        self._render_items()
        item = MENU_ITEMS[self._highlighted_index]
        self.post_message(MenuItemHighlighted(item))

    def set_active_popup(self, name: str):
        self._active_popup = name
        self._render_items()

    def clear_active(self):
        self._active_popup = ""
        self._render_items()

    def set_status(self, text: str):
        self._status_text = text
        try:
            row = self.query_one("#menu-status-row", Label)
            row.update(f" {text}")
        except Exception:
            pass

    def _render_items(self):
        """Build Rich markup for line 1."""
        parts = []

        for i, item in enumerate(MENU_ITEMS):
            if i > 0:
                parts.append(" ")

            c = item.group_color
            is_active = (self._active_popup == item.popup_name and self._active_popup != "")
            is_highlighted = (self._highlighted_index == i)

            if is_active:
                parts.append(f"[reverse {c}] {item.label} {item.key} [/reverse {c}] ")
            elif is_highlighted:
                parts.append(f"[{c} on #333333] {item.label} {item.key} [/{c} on #333333] ")
            else:
                parts.append(f"[{c}]{item.label}[/{c}] [dim]{item.key}[/dim] ")

        # Right-edge hint
        if self._highlighted_index >= 0:
            hint = "[dim]Esc:back[/dim]"
        else:
            hint = "[dim]Tab:menu[/dim]"
        parts.append(f"  {hint}  [dim]Quit[/dim] [dim]q[/dim]")

        markup = "".join(parts)
        try:
            row = self.query_one("#menu-items-row", Label)
            row.update(markup)
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        key = event.key

        if not self.in_menu_mode:
            return  # Globe mode -- let app handle keys

        # Menu mode key handling
        if key == "left":
            self.move_highlight(-1)
            event.stop()
            event.prevent_default()
        elif key == "right":
            self.move_highlight(1)
            event.stop()
            event.prevent_default()
        elif key == "enter":
            item = MENU_ITEMS[self._highlighted_index]
            self.post_message(MenuItemSelected(item))
            event.stop()
            event.prevent_default()
        elif key == "escape" or key == "tab":
            self.post_message(MenuDismissed())
            event.stop()
            event.prevent_default()
        elif key == "down":
            # Down-arrow commits focus to previewed popup (same as Enter)
            item = MENU_ITEMS[self._highlighted_index]
            self.post_message(MenuItemSelected(item))
            event.stop()
            event.prevent_default()
        elif key == "up":
            # Consume to prevent globe navigation in menu mode
            event.stop()
            event.prevent_default()
        else:
            # Check for direct hotkey
            char = key if len(key) == 1 else ""
            if key == "slash":
                char = "/"
            for item in MENU_ITEMS:
                if item.key == char:
                    self.post_message(MenuItemSelected(item))
                    event.stop()
                    event.prevent_default()
                    return
