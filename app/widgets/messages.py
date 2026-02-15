"""Textual Message subclasses for widget-to-app communication."""

from textual.message import Message


class PopupClosed(Message):
    """Posted when a popup requests to close itself."""

    def __init__(self, popup_name: str) -> None:
        super().__init__()
        self.popup_name = popup_name


class CenterOnLocation(Message):
    """Posted when the view should center on a lat/lon position."""

    def __init__(self, lat: float, lon: float, zoom: float = 1.8) -> None:
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.zoom = zoom


class TrackSatellite(Message):
    """Posted when a satellite should be tracked."""

    def __init__(self, idx: int, name: str, sat_type: str) -> None:
        super().__init__()
        self.idx = idx
        self.name = name
        self.sat_type = sat_type


class SatellitesChanged(Message):
    """Posted when loaded satellite data changes."""

    def __init__(self, satellite_data, satellite_types_list, type_indices) -> None:
        super().__init__()
        self.satellite_data = satellite_data
        self.satellite_types_list = satellite_types_list
        self.type_indices = type_indices


class OptionsChanged(Message):
    """Posted when an option value changes."""

    def __init__(self, key: str, value) -> None:
        super().__init__()
        self.key = key
        self.value = value


class TimeChanged(Message):
    """Posted when custom time or freeze state changes."""

    def __init__(self, dt, freeze: bool) -> None:
        super().__init__()
        self.dt = dt
        self.freeze = freeze


class TimeReset(Message):
    """Posted when time should be reset to current UTC."""
    pass


class TimeReverted(Message):
    """Posted when time should revert to saved state (ESC)."""
    pass


class GlobeRedrawNeeded(Message):
    """Posted when the globe needs a full redraw."""
    pass


class LoadSatelliteCategory(Message):
    """Posted when a satellite category should be loaded."""

    def __init__(self, sat_type: str) -> None:
        super().__init__()
        self.sat_type = sat_type


class RestoreView(Message):
    """Posted when the globe view should be restored to a saved state."""

    def __init__(self, lat: float, lon: float, zoom: float) -> None:
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.zoom = zoom


class AntennaStatusChanged(Message):
    """Posted when antenna client state changes (connect, disconnect, status update)."""
    pass


# Re-exported from menu_bar for convenience
from .menu_bar import MenuItemSelected, MenuItemHighlighted, MenuDismissed
