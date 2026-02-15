"""Options menu overlay widget."""

from textual.widgets import Static
from rich.text import Text
from config_manager import config

from .popup_base import PopupBase
from .messages import OptionsChanged


class OptionsMenu(PopupBase):
    """Options menu overlay with sliders and toggles."""

    CLOSE_KEY = "o"
    POPUP_NAME = "options"
    ESC_CLOSES = True
    ROW_COUNT = 12
    ROW_ID_PREFIX = "opt_row"
    ROW_CSS_CLASS = "opt-row"

    DEFAULT_CSS = """
    OptionsMenu {
        layer: overlay;
        width: auto;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid $primary;
        border-title-color: $primary;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .opt-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, satellite_types=None):
        super().__init__()
        self.border_title = "OPTIONS (O to close)"
        self.lod_ratio = config.get_option("lod_ratio")
        self.rivers_ratio = config.get_option("rivers_ratio")
        self.cities_ratio = config.get_option("cities_ratio")
        self.shadow_mode = config.get_option("shadow_mode")
        self.passes_per_sat = config.get_option("passes_per_sat")
        self.max_passes = config.get_option("max_passes")
        self.draw_pass_arcs = config.get_option("draw_pass_arcs")
        self.show_pass_names = config.get_option("show_pass_names")
        self._selected_index = 0
        self._slider_options = ['lod', 'rivers', 'cities']
        self._toggle_options = ['shadow']
        self._int_options = ['passes_per_sat', 'max_passes']
        self._bool_options = ['draw_pass_arcs', 'show_pass_names']
        self._options = self._slider_options + self._toggle_options + self._int_options + self._bool_options

    def on_show(self):
        self._render_menu()

    def _render_menu(self):
        lines = []

        # LOD slider
        idx = 0
        marker = ">" if self._selected_index == idx else " "
        bar = self._make_slider(self.lod_ratio)
        lines.append(f"{marker} {self._format_slider_line('LOD', bar, self.lod_ratio)}")

        # Rivers slider
        idx = 1
        marker = ">" if self._selected_index == idx else " "
        bar = self._make_slider(self.rivers_ratio)
        lines.append(f"{marker} {self._format_slider_line('Rivers', bar, self.rivers_ratio)}")

        # Cities slider
        idx = 2
        marker = ">" if self._selected_index == idx else " "
        bar = self._make_slider(self.cities_ratio)
        lines.append(f"{marker} {self._format_slider_line('Cities', bar, self.cities_ratio)}")

        # Shadow mode selector
        idx = 3
        marker = ">" if self._selected_index == idx else " "
        shadow_modes_text = self._format_shadow_modes(self.shadow_mode)
        lines.append(f"{marker} Shadow:  {shadow_modes_text}")

        # Passes header
        lines.append("  [bold]Passes[/bold]")

        # Passes per satellite
        idx = 4
        marker = ">" if self._selected_index == idx else " "
        lines.append(f"{marker}   Per sat: [cyan]{self.passes_per_sat:>3}[/cyan]")

        # Max passes total
        idx = 5
        marker = ">" if self._selected_index == idx else " "
        lines.append(f"{marker}   Max:     [cyan]{self.max_passes:>3}[/cyan]")

        # Draw arcs toggle
        idx = 6
        marker = ">" if self._selected_index == idx else " "
        check = "[green]X[/green]" if self.draw_pass_arcs else " "
        lines.append(f"{marker}   Arcs:    \\[{check}]")

        # Show pass names toggle
        idx = 7
        marker = ">" if self._selected_index == idx else " "
        check = "[green]X[/green]" if self.show_pass_names else " "
        lines.append(f"{marker}   Names:   \\[{check}]")

        lines.append("")
        lines.append("[dim]Up/Down:select  Left/Right:adjust[/dim]")

        self._update_labels(lines)

    def _make_slider(self, value):
        """Create a visual slider bar for value 0-1 with 0.05 step."""
        bar_width = 14
        pos = int(value * bar_width)
        pos = min(pos, bar_width)
        filled = '[cyan]' + '=' * pos + '[/cyan]'
        empty = '[dim]' + '-' * (bar_width - pos) + '[/dim]'
        return filled + empty

    def _format_slider_line(self, label, bar, value):
        label_text = f"{label}:"
        return f"{label_text:<8}{bar} {value:>4.2f}"

    def _format_shadow_modes(self, active_mode):
        modes = ["ALL", "BG", "BORDERS", "OFF"]
        parts = []
        for mode in modes:
            if mode == active_mode:
                style = "red bold" if mode == "OFF" else "white bold"
                parts.append(f"[{style}]{mode}[/{style}]")
            else:
                parts.append(f"[dim]{mode}[/dim]")
        return "  ".join(parts)

    def _visible_width(self, text):
        return len(Text.from_markup(text).plain)

    def _selected_option(self):
        return self._options[self._selected_index]

    def is_slider_selected(self):
        return self._selected_option() in self._slider_options

    def move_selection(self, direction):
        """Move selection up or down."""
        self._selected_index = (self._selected_index + direction) % len(self._options)
        self._render_menu()

    def adjust_value(self, direction):
        """Adjust the selected value."""
        option = self._selected_option()

        if option == 'lod':
            step = 0.05 * direction
            self.lod_ratio = max(0.0, min(1.0, round(self.lod_ratio + step, 2)))
            config.set_option("lod_ratio", self.lod_ratio)
        elif option == 'rivers':
            step = 0.05 * direction
            self.rivers_ratio = max(0.0, min(1.0, round(self.rivers_ratio + step, 2)))
            config.set_option("rivers_ratio", self.rivers_ratio)
        elif option == 'cities':
            step = 0.05 * direction
            self.cities_ratio = max(0.0, min(1.0, round(self.cities_ratio + step, 2)))
            config.set_option("cities_ratio", self.cities_ratio)
        elif option == 'shadow':
            self._cycle_shadow_mode(direction)
            config.set_option("shadow_mode", self.shadow_mode)
        elif option == 'passes_per_sat':
            self.passes_per_sat = max(1, min(10, self.passes_per_sat + direction))
            config.set_option("passes_per_sat", self.passes_per_sat)
        elif option == 'max_passes':
            self.max_passes = max(5, min(100, self.max_passes + direction * 5))
            config.set_option("max_passes", self.max_passes)
        elif option == 'draw_pass_arcs':
            self.draw_pass_arcs = not self.draw_pass_arcs
            config.set_option("draw_pass_arcs", self.draw_pass_arcs)
        elif option == 'show_pass_names':
            self.show_pass_names = not self.show_pass_names
            config.set_option("show_pass_names", self.show_pass_names)

        self._render_menu()
        self.post_message(OptionsChanged(option, getattr(self, option, None)))

    def toggle_selected(self):
        option = self._selected_option()
        if option in self._bool_options:
            self.adjust_value(0)

    def _cycle_shadow_mode(self, direction):
        modes = ["ALL", "BG", "BORDERS", "OFF"]
        try:
            idx = modes.index(self.shadow_mode)
        except ValueError:
            idx = 0
        next_idx = (idx + direction) % len(modes)
        self.shadow_mode = modes[next_idx]

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
            self.adjust_value(-1)
            event.stop()
            event.prevent_default()
        elif key == "right":
            self.adjust_value(1)
            event.stop()
            event.prevent_default()
        elif key == "enter":
            self.toggle_selected()
            event.stop()
            event.prevent_default()
