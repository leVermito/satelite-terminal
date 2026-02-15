"""Time control popup widget."""

import calendar
from datetime import datetime, timezone
from textual.app import ComposeResult
from textual.widgets import Static, Label

from .popup_base import PopupBase
from .messages import PopupClosed, TimeChanged, TimeReset, TimeReverted


class TimeBox(PopupBase):
    """Time control popup for custom orbit time."""

    CLOSE_KEY = "t"
    ESC_CLOSES = False  # Escape exits editing mode first, then closes
    POPUP_NAME = "time"
    ROW_COUNT = 4
    ROW_ID_PREFIX = "time_row"
    ROW_CSS_CLASS = "time-row"

    DEFAULT_CSS = """
    TimeBox {
        layer: overlay;
        width: auto;
        height: auto;
        background: $surface;
        border: solid #7ecbff;
        border-title-color: #7ecbff;
        border-title-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .time-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.border_title = "TIME (T to close)"
        self._rows = ["time", "controls"]
        self._selected_row = 0  # 0 = time row, 1 = controls row
        self._control_items = ["freeze", "reset"]
        self._selected_control = 0  # 0 = freeze, 1 = reset
        self._time_fields = ["year", "month", "day", "hour", "minute", "second"]
        self._selected_field = 0
        self._editing_time = False
        self._buffer = ""
        self._dt = datetime.now(timezone.utc)
        self._freeze = False
        self._is_custom = False
        self._dirty = False

    def compose(self) -> ComposeResult:
        yield Label("", id="time_row_0", classes="time-row")
        yield Label("", id="time_row_1", classes="time-row")
        yield Label("", id="time_row_2", classes="time-row")
        yield Label("", id="time_row_3", classes="time-row")

    def request_close(self):
        """Override: when closing via T key, apply time changes only if modified."""
        self.display = False
        if self._dirty:
            self.post_message(TimeChanged(self._dt, self._freeze))
        self.post_message(PopupClosed(self.POPUP_NAME))

    def set_custom(self, is_custom: bool):
        self._is_custom = bool(is_custom)
        self._render_content()

    def on_mount(self):
        self._render_content()

    def set_datetime(self, dt: datetime):
        self._dt = dt.astimezone(timezone.utc)
        self._buffer = ""
        self._dirty = False
        self._render_content()

    def set_freeze(self, freeze: bool):
        self._freeze = bool(freeze)
        self._render_content()

    def get_datetime(self) -> datetime:
        return self._dt

    def get_freeze(self) -> bool:
        return self._freeze

    def move_row(self, direction: int):
        if self._editing_time:
            self._dt = self._apply_delta(self._time_fields[self._selected_field], direction)
            self._dirty = True
            self._render_content()
            self.post_message(TimeChanged(self._dt, self._freeze))
        else:
            self._selected_row = (self._selected_row + direction) % len(self._rows)
            self._render_content()

    def move_field(self, direction: int):
        if self._rows[self._selected_row] == "time":
            if self._editing_time:
                self._selected_field = (self._selected_field + direction) % len(self._time_fields)
                self._buffer = ""
            else:
                self._editing_time = True
                if direction > 0:
                    self._selected_field = 0
                else:
                    self._selected_field = len(self._time_fields) - 1
            self._render_content()
        elif self._rows[self._selected_row] == "controls":
            self._selected_control = (self._selected_control + direction) % len(self._control_items)
            self._render_content()

    def handle_digit(self, digit: str):
        if not self._editing_time or self._rows[self._selected_row] != "time":
            return
        field = self._time_fields[self._selected_field]
        width = self._field_width(field)
        if width <= 0:
            return
        self._buffer += digit
        if len(self._buffer) >= width:
            value = int(self._buffer[:width])
            self._buffer = ""
            self._dt = self._set_field(field, value)
            self._dirty = True
            if self._selected_field < len(self._time_fields) - 1:
                self._selected_field += 1
            self._render_content()
            self.post_message(TimeChanged(self._dt, self._freeze))
        else:
            self._render_content()

    def backspace(self):
        if not self._buffer:
            return
        self._buffer = self._buffer[:-1]
        self._render_content()

    def _field_width(self, field: str) -> int:
        if field == "year":
            return 4
        if field in ("month", "day", "hour", "minute", "second"):
            return 2
        return 0

    def _max_day(self, year: int, month: int) -> int:
        return calendar.monthrange(year, month)[1]

    def _apply_delta(self, field: str, direction: int) -> datetime:
        dt = self._dt
        year = dt.year
        month = dt.month
        day = dt.day
        hour = dt.hour
        minute = dt.minute
        second = dt.second

        if field == "year":
            year = max(1, min(9999, year + direction))
        elif field == "month":
            month = ((month - 1 + direction) % 12) + 1
        elif field == "day":
            max_day = self._max_day(year, month)
            day = ((day - 1 + direction) % max_day) + 1
        elif field == "hour":
            hour = (hour + direction) % 24
        elif field == "minute":
            minute = (minute + direction) % 60
        elif field == "second":
            second = (second + direction) % 60

        max_day = self._max_day(year, month)
        day = min(day, max_day)

        return dt.replace(year=year, month=month, day=day,
                          hour=hour, minute=minute, second=second,
                          microsecond=0, tzinfo=timezone.utc)

    def _set_field(self, field: str, value: int) -> datetime:
        dt = self._dt
        year = dt.year
        month = dt.month
        day = dt.day
        hour = dt.hour
        minute = dt.minute
        second = dt.second

        if field == "year":
            year = max(1, min(9999, value))
        elif field == "month":
            month = max(1, min(12, value))
        elif field == "day":
            max_day = self._max_day(year, month)
            day = max(1, min(max_day, value))
        elif field == "hour":
            hour = max(0, min(23, value))
        elif field == "minute":
            minute = max(0, min(59, value))
        elif field == "second":
            second = max(0, min(59, value))

        max_day = self._max_day(year, month)
        day = min(day, max_day)

        return dt.replace(year=year, month=month, day=day,
                          hour=hour, minute=minute, second=second,
                          microsecond=0, tzinfo=timezone.utc)

    def _format_field(self, field: str, value_str: str, is_custom: bool) -> str:
        if self._editing_time and self._time_fields[self._selected_field] == field:
            if self._buffer:
                width = self._field_width(field)
                padded = self._buffer.ljust(width, "_")
                value_str = padded
            return f"[reverse]{value_str}[/reverse]"
        return value_str

    def _render_content(self):
        dt = self._dt

        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"
        day = f"{dt.day:02d}"
        hour = f"{dt.hour:02d}"
        minute = f"{dt.minute:02d}"
        second = f"{dt.second:02d}"
        tz = "UTC"

        year_s = self._format_field("year", year, False)
        month_s = self._format_field("month", month, False)
        day_s = self._format_field("day", day, False)
        hour_s = self._format_field("hour", hour, False)
        minute_s = self._format_field("minute", minute, False)
        second_s = self._format_field("second", second, False)

        time_str = f"{year_s}-{month_s}-{day_s} {hour_s}:{minute_s}:{second_s} {tz}"

        if self._freeze:
            label = "[#7ecbff]Custom Time:[/#7ecbff]"
        elif self._is_custom:
            label = "[yellow]Custom Time:[/yellow]"
        else:
            label = "Current Time:"

        if self._rows[self._selected_row] == "time" and not self._editing_time:
            value_line = f"[reverse]{label} {time_str}[/reverse]"
        else:
            value_line = f"{label} {time_str}"

        if self._freeze:
            freeze_check = "X"
        else:
            freeze_check = " "

        if self._rows[self._selected_row] == "controls" and self._control_items[self._selected_control] == "freeze":
            freeze_box = f"[reverse]\\[{freeze_check}] FREEZE[/reverse]"
        else:
            freeze_box = f"\\[{freeze_check}] FREEZE"

        if self._rows[self._selected_row] == "controls" and self._control_items[self._selected_control] == "reset":
            reset_btn = "[reverse]RESET[/reverse]"
        else:
            reset_btn = "RESET"

        controls_line = f"{freeze_box}   {reset_btn}"

        try:
            self.query_one("#time_row_0", Label).update(value_line)
            self.query_one("#time_row_1", Label).update(controls_line)
            self.query_one("#time_row_2", Label).update("")
            self.query_one("#time_row_3", Label).update("[dim]Up/Dn:row  Enter:edit  L/R:field[/dim]")
        except:
            pass

    def toggle_selected(self) -> str:
        row = self._rows[self._selected_row]
        if row == "time":
            if self._editing_time:
                self._editing_time = False
                self._buffer = ""
                self._render_content()
                return "edit_done"
            else:
                self._editing_time = True
                self._selected_field = 0
                self._render_content()
                return "edit"
        elif row == "controls":
            control = self._control_items[self._selected_control]
            if control == "freeze":
                self._freeze = not self._freeze
                self._dirty = True
                self._render_content()
                self.post_message(TimeChanged(self._dt, self._freeze))
                return "freeze"
            elif control == "reset":
                self.display = False
                self.post_message(TimeReset())
                self.post_message(PopupClosed(self.POPUP_NAME))
                return "reset"
        return ""

    def _handle_key(self, event):
        key = event.key

        if key == "escape":
            if self._editing_time:
                self._editing_time = False
                self._buffer = ""
                self._render_content()
            else:
                self.display = False
                self.post_message(TimeReverted())
                self.post_message(PopupClosed(self.POPUP_NAME))
            event.stop()
            event.prevent_default()
        elif key == "up":
            self.move_row(-1)
            event.stop()
            event.prevent_default()
        elif key == "down":
            self.move_row(1)
            event.stop()
            event.prevent_default()
        elif key == "left":
            self.move_field(-1)
            event.stop()
            event.prevent_default()
        elif key == "right":
            self.move_field(1)
            event.stop()
            event.prevent_default()
        elif key == "enter":
            self.toggle_selected()
            event.stop()
            event.prevent_default()
        elif len(key) == 1 and key.isdigit():
            self.handle_digit(key)
            event.stop()
            event.prevent_default()
        elif key == "backspace":
            self.backspace()
            event.stop()
            event.prevent_default()
