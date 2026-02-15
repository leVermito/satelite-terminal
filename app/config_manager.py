"""
Unified configuration manager.
Loads defaults from satellite_config, overlays user TOML overrides, exposes read/write API.
"""

import copy
from pathlib import Path

import tomlkit

from satellite.config import (
    CATEGORY_COLORS as DEFAULT_CATEGORY_COLORS,
    SATELLITE_TYPES as DEFAULT_SATELLITE_TYPES,
    COLOR_MAP as DEFAULT_COLOR_MAP,
)

CONFIG_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = CONFIG_DIR / "config.toml"


class ConfigManager:

    def __init__(self):
        self._defaults_satellite_types = copy.deepcopy(DEFAULT_SATELLITE_TYPES)
        self._defaults_category_colors = copy.deepcopy(DEFAULT_CATEGORY_COLORS)
        self._defaults_color_map = copy.deepcopy(DEFAULT_COLOR_MAP)

        # Merged live state (defaults + user overrides)
        self._satellite_types = copy.deepcopy(DEFAULT_SATELLITE_TYPES)
        self._category_colors = copy.deepcopy(DEFAULT_CATEGORY_COLORS)
        self._color_map = copy.deepcopy(DEFAULT_COLOR_MAP)

        # User overrides only (what gets written to TOML)
        self._user_overrides = {}

        # Options (display settings)
        self._options = {
            "lod_ratio": 0.5,
            "rivers_ratio": 0.5,
            "cities_ratio": 0.5,
            "shadow_mode": "BORDERS",
            "passes_per_sat": 3,
            "max_passes": 20,
            "draw_pass_arcs": True,
            "show_pass_names": False,
        }

        # MQTT config
        self._mqtt = {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 1883,
            "username": "",
            "password": "",
        }

        # Future sections
        self._favorites = []
        self._home_location = None
        self._preset_locations = {}
        self._default_satellites = []
        self._locations = []

        # Raw tomlkit document (preserves formatting for round-trip)
        self._toml_doc = None

        self._load()

    # --- Loading ---

    def _load(self):
        if not CONFIG_FILE.exists():
            return

        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            self._toml_doc = tomlkit.parse(raw)
        except Exception:
            self._toml_doc = None
            return

        self._apply_toml(self._toml_doc)

    def _apply_toml(self, doc):
        if "satellite_types" in doc:
            for type_name, overrides in doc["satellite_types"].items():
                if type_name in self._satellite_types:
                    for key, val in overrides.items():
                        self._satellite_types[type_name][key] = val
                        self._user_overrides.setdefault("satellite_types", {})
                        self._user_overrides["satellite_types"].setdefault(type_name, {})
                        self._user_overrides["satellite_types"][type_name][key] = val

        if "category_colors" in doc:
            for cat, color in doc["category_colors"].items():
                if cat in self._category_colors:
                    self._category_colors[cat] = color
                    self._user_overrides.setdefault("category_colors", {})
                    self._user_overrides["category_colors"][cat] = color

        if "favorites" in doc:
            raw_favorites = doc["favorites"]
            self._favorites = []
            if isinstance(raw_favorites, list):
                for entry in raw_favorites:
                    if isinstance(entry, dict) and "name" in entry and "norad_id" in entry:
                        self._favorites.append({
                            "name": str(entry["name"]),
                            "norad_id": int(entry["norad_id"]),
                            "type": str(entry.get("type", "unknown"))
                        })

        if "home" in doc:
            h = doc["home"]
            if "lat" in h and "lon" in h:
                self._home_location = {
                    "lat": float(h["lat"]),
                    "lon": float(h["lon"]),
                    "name": str(h.get("name", "")),
                }

        if "presets" in doc:
            for key, val in doc["presets"].items():
                self._preset_locations[key] = {
                    "lat": float(val["lat"]),
                    "lon": float(val["lon"]),
                    "name": str(val.get("name", "")),
                }

        if "options" in doc:
            for key, val in doc["options"].items():
                if key in self._options:
                    self._options[key] = val
                    self._user_overrides.setdefault("options", {})
                    self._user_overrides["options"][key] = val

        if "defaults" in doc:
            raw_defaults = doc["defaults"].get("satellites", [])
            self._default_satellites = []
            for entry in raw_defaults:
                if isinstance(entry, dict) and "category" in entry and "type" in entry:
                    self._default_satellites.append((entry["category"], entry["type"]))

        if "mqtt" in doc:
            mqt = doc["mqtt"]
            for key in self._mqtt:
                if key in mqt:
                    self._mqtt[key] = mqt[key]

        if "locations" in doc:
            raw_locations = doc["locations"]
            self._locations = []
            if isinstance(raw_locations, list):
                for entry in raw_locations:
                    if isinstance(entry, dict) and "name" in entry and "lat" in entry and "lon" in entry:
                        self._locations.append({
                            "name": str(entry["name"]),
                            "color": str(entry.get("color", "#ffffff")),
                            "lat": float(entry["lat"]),
                            "lon": float(entry["lon"]),
                            "default": bool(entry.get("default", False))
                        })

    # --- Read API ---

    @property
    def SATELLITE_TYPES(self):
        return self._satellite_types

    @property
    def CATEGORY_COLORS(self):
        return self._category_colors

    @property
    def COLOR_MAP(self):
        return self._color_map

    def get_type_priority(self, type_name: str) -> int:
        if type_name in self._satellite_types:
            return self._satellite_types[type_name]["priority"]
        return 999

    def get_type_color(self, type_name: str) -> str:
        if type_name in self._satellite_types:
            return self._satellite_types[type_name]["color"]
        return "white"

    def get_category_color(self, category: str) -> str:
        return self._category_colors.get(category, "white")

    def get_enabled_types(self) -> list[str]:
        return [t for t, cfg in self._satellite_types.items() if cfg.get("enabled", True)]

    def set_type_enabled(self, type_name: str, enabled: bool) -> None:
        if type_name in self._satellite_types:
            self._satellite_types[type_name]["enabled"] = enabled

    def get_types_by_priority(self) -> list[str]:
        return sorted(
            self._satellite_types.keys(),
            key=lambda t: self._satellite_types[t]["priority"],
        )

    @property
    def favorites(self):
        return self._favorites

    @property
    def home_location(self):
        return self._home_location

    @property
    def preset_locations(self):
        return self._preset_locations

    @property
    def default_satellites(self):
        return self._default_satellites

    @property
    def locations(self):
        return self._locations

    def get_default_location(self):
        """Return first location with default=True, or None."""
        for loc in self._locations:
            if loc.get("default", False):
                return loc
        return None

    @property
    def mqtt(self):
        return self._mqtt

    @property
    def options(self):
        return self._options

    def get_option(self, key: str):
        return self._options.get(key)

    def set_option(self, key: str, value):
        if key not in self._options:
            return
        self._options[key] = value
        self._user_overrides.setdefault("options", {})
        self._user_overrides["options"][key] = value
        self.save()

    # --- Write API ---

    def set_type_color(self, type_name: str, color: str):
        if type_name not in self._satellite_types:
            return
        self._satellite_types[type_name]["color"] = color
        self._user_overrides.setdefault("satellite_types", {})
        self._user_overrides["satellite_types"].setdefault(type_name, {})
        self._user_overrides["satellite_types"][type_name]["color"] = color

    def set_home_location(self, lat: float, lon: float, name: str = ""):
        self._home_location = {"lat": lat, "lon": lon, "name": name}
        self._user_overrides["home"] = self._home_location

    def set_preset_location(self, key: str, lat: float, lon: float, name: str = ""):
        loc = {"lat": lat, "lon": lon, "name": name}
        self._preset_locations[key] = loc
        self._user_overrides.setdefault("presets", {})
        self._user_overrides["presets"][key] = loc

    def set_default_satellites(self, defaults: list[tuple[str, str]]):
        self._default_satellites = defaults
        self._user_overrides["defaults"] = {
            "satellites": [{"category": c, "type": t} for c, t in defaults]
        }
        self.save()

    def set_favorites(self, favorites: list):
        """Set favorites list."""
        self._favorites = favorites
        self._user_overrides["favorites"] = favorites
        self.save()

    def add_favorite(self, name: str, norad_id: int, sat_type: str):
        """Add a satellite to favorites. Skips if norad_id already exists."""
        for fav in self._favorites:
            if fav["norad_id"] == norad_id:
                return
        self._favorites.append({
            "name": name,
            "norad_id": norad_id,
            "type": sat_type
        })
        self._user_overrides["favorites"] = self._favorites
        self.save()

    def remove_favorite(self, norad_id: int):
        """Remove a satellite from favorites by NORAD ID."""
        self._favorites = [f for f in self._favorites if f["norad_id"] != norad_id]
        self._user_overrides["favorites"] = self._favorites
        self.save()

    def set_locations(self, locations: list):
        """Set locations list. Enforces single-default invariant."""
        # Ensure only one default
        default_count = sum(1 for loc in locations if loc.get("default", False))
        if default_count > 1:
            # Keep only first default
            seen_default = False
            for loc in locations:
                if loc.get("default", False):
                    if seen_default:
                        loc["default"] = False
                    else:
                        seen_default = True

        self._locations = locations
        self._user_overrides["locations"] = locations
        self.save()

    def save(self):
        if self._toml_doc is None:
            self._toml_doc = tomlkit.document()
            self._toml_doc.add(tomlkit.comment("SDR user configuration"))
            self._toml_doc.add(tomlkit.comment("Only user-modified values are stored here."))
            self._toml_doc.add(tomlkit.nl())

        for section, values in self._user_overrides.items():
            if section == "favorites" and isinstance(values, list):
                if section in self._toml_doc:
                    del self._toml_doc[section]
                aot = tomlkit.aot()
                for fav in values:
                    table = tomlkit.table()
                    table["name"] = fav["name"]
                    table["norad_id"] = fav["norad_id"]
                    table["type"] = fav["type"]
                    aot.append(table)
                self._toml_doc.add(section, aot)
            elif section == "locations" and isinstance(values, list):
                # Handle locations as array-of-tables
                if section in self._toml_doc:
                    del self._toml_doc[section]
                aot = tomlkit.aot()
                for loc in values:
                    table = tomlkit.table()
                    for k, v in loc.items():
                        table[k] = v
                    aot.append(table)
                self._toml_doc.add(section, aot)
            elif section not in self._toml_doc:
                self._toml_doc.add(section, tomlkit.table())
            if isinstance(values, dict):
                for key, val in values.items():
                    if isinstance(val, dict):
                        if key not in self._toml_doc[section]:
                            self._toml_doc[section].add(key, tomlkit.table())
                        for k2, v2 in val.items():
                            self._toml_doc[section][key][k2] = v2
                    else:
                        self._toml_doc[section][key] = val

        CONFIG_FILE.write_text(tomlkit.dumps(self._toml_doc), encoding="utf-8")

    def reload(self):
        self._satellite_types.clear()
        self._satellite_types.update(copy.deepcopy(DEFAULT_SATELLITE_TYPES))
        self._category_colors.clear()
        self._category_colors.update(copy.deepcopy(DEFAULT_CATEGORY_COLORS))
        self._color_map.clear()
        self._color_map.update(copy.deepcopy(DEFAULT_COLOR_MAP))
        self._user_overrides = {}
        self._options = {
            "lod_ratio": 0.5,
            "rivers_ratio": 0.5,
            "cities_ratio": 0.5,
            "shadow_mode": "BORDERS",
            "passes_per_sat": 3,
            "max_passes": 20,
            "draw_pass_arcs": True,
        }
        self._favorites = []
        self._home_location = None
        self._preset_locations = {}
        self._default_satellites = []
        self._locations = []
        self._toml_doc = None
        self._load()


# Module-level singleton
config = ConfigManager()

# Backward-compatible aliases
SATELLITE_TYPES = config.SATELLITE_TYPES
CATEGORY_COLORS = config.CATEGORY_COLORS
COLOR_MAP = config.COLOR_MAP
get_type_priority = config.get_type_priority
get_type_color = config.get_type_color
get_category_color = config.get_category_color
get_enabled_types = config.get_enabled_types
set_type_enabled = config.set_type_enabled
get_types_by_priority = config.get_types_by_priority
