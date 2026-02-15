"""
Satellite type configuration.
Defines colors, display settings, and priority for each satellite type.
"""

# Category colors - used for category headers and as fallback for types
CATEGORY_COLORS = {
    'special-interest': 'green',      # Space stations, debris - high visibility
    'weather': 'magenta',             # Weather/Earth observation
    'communications': 'yellow',       # Communication satellites
    'navigation': 'cyan',             # GPS, GLONASS, etc.
    'scientific': 'blue',             # Science/research
    'miscellaneous': 'white',         # Military, CubeSats, other
}

# Satellite type definitions
# Priority order: lower index = higher priority (rendered on top when overlapping)
# Types are matched by filename prefix in app/data/ directory
SATELLITE_TYPES = {
    # === SPECIAL-INTEREST (green family) ===
    'stations': {
        'color': 'green',
        'category': 'special-interest',
        'priority': 0,       # Highest priority (space stations)
    },
    'analyst': {
        'color': 'bright_green',
        'category': 'special-interest',
        'priority': 1,
    },
    'russian-asat-debris': {
        'color': 'dark_green',
        'category': 'special-interest',
        'priority': 10,
    },
    'chinese-asat-debris': {
        'color': 'dark_green',
        'category': 'special-interest',
        'priority': 10,
    },
    'iridium-33-debris': {
        'color': 'dark_green',
        'category': 'special-interest',
        'priority': 10,
    },
    'cosmos-2251-debris': {
        'color': 'dark_green',
        'category': 'special-interest',
        'priority': 10,
    },
    
    # === WEATHER (magenta family) ===
    'noaa': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 2,
    },
    'goes': {
        'color': 'bright_magenta',
        'category': 'weather',
        'priority': 2,
    },
    'earth-resources': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 3,
    },
    'sarsat': {
        'color': 'bright_magenta',
        'category': 'weather',
        'priority': 3,
    },
    'disaster-monitoring': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 3,
    },
    'tdrss': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 3,
    },
    'argos': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 4,
    },
    'planet': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 4,
    },
    'spire': {
        'color': 'magenta',
        'category': 'weather',
        'priority': 4,
    },
    
    # === COMMUNICATIONS (yellow/orange family) ===
    'starlink': {
        'color': 'yellow',
        'category': 'communications',
        'priority': 5,
    },
    'oneweb': {
        'color': 'bright_yellow',
        'category': 'communications',
        'priority': 5,
    },
    'qianfan': {
        'color': 'yellow',
        'category': 'communications',
        'priority': 5,
    },
    'hulianwang-digui': {
        'color': 'yellow',
        'category': 'communications',
        'priority': 5,
    },
    'kuiper': {
        'color': 'bright_yellow',
        'category': 'communications',
        'priority': 5,
    },
    'iridium-next': {
        'color': 'orange1',
        'category': 'communications',
        'priority': 4,
    },
    'globalstar': {
        'color': 'orange1',
        'category': 'communications',
        'priority': 4,
    },
    'orbcomm': {
        'color': 'orange1',
        'category': 'communications',
        'priority': 4,
    },
    'intelsat': {
        'color': 'gold1',
        'category': 'communications',
        'priority': 3,
    },
    'ses': {
        'color': 'gold1',
        'category': 'communications',
        'priority': 3,
    },
    'eutelsat': {
        'color': 'gold1',
        'category': 'communications',
        'priority': 3,
    },
    'telesat': {
        'color': 'gold1',
        'category': 'communications',
        'priority': 3,
    },
    'active-geosynchronous': {
        'color': 'gold1',
        'category': 'communications',
        'priority': 3,
    },
    'movers': {
        'color': 'yellow',
        'category': 'communications',
        'priority': 4,
    },
    'geo-protected-zone-plus': {
        'color': 'gold1',
        'category': 'communications',
        'priority': 3,
    },
    'amateur': {
        'color': 'red',
        'category': 'communications',
        'priority': 6,
    },
    'satnogs': {
        'color': 'red',
        'category': 'communications',
        'priority': 6,
    },
    'experimental-comm': {
        'color': 'orange1',
        'category': 'communications',
        'priority': 5,
    },
    'other-comm': {
        'color': 'yellow',
        'category': 'communications',
        'priority': 6,
    },
    
    # === NAVIGATION (cyan family) ===
    'gps-ops': {
        'color': 'cyan',
        'category': 'navigation',
        'priority': 2,
    },
    'glonass-ops': {
        'color': 'bright_cyan',
        'category': 'navigation',
        'priority': 2,
    },
    'galileo': {
        'color': 'cyan',
        'category': 'navigation',
        'priority': 2,
    },
    'beidou': {
        'color': 'bright_cyan',
        'category': 'navigation',
        'priority': 2,
    },
    'sbas': {
        'color': 'cyan',
        'category': 'navigation',
        'priority': 3,
    },
    'nnss': {
        'color': 'cyan',
        'category': 'navigation',
        'priority': 4,
    },
    'russian-leo-navigation': {
        'color': 'bright_cyan',
        'category': 'navigation',
        'priority': 3,
    },
    
    # === SCIENTIFIC (blue family) ===
    'space-earth-science': {
        'color': 'blue',
        'category': 'scientific',
        'priority': 3,
    },
    'geodetic': {
        'color': 'bright_blue',
        'category': 'scientific',
        'priority': 3,
    },
    'engineering': {
        'color': 'blue',
        'category': 'scientific',
        'priority': 4,
    },
    'education': {
        'color': 'bright_blue',
        'category': 'scientific',
        'priority': 4,
    },
    
    # === MISCELLANEOUS (white/grey family) ===
    'military': {
        'color': 'grey70',
        'category': 'miscellaneous',
        'priority': 5,
    },
    'radar-calibration': {
        'color': 'grey50',
        'category': 'miscellaneous',
        'priority': 6,
    },
    'cubesats': {
        'color': 'white',
        'category': 'miscellaneous',
        'priority': 7,
    },
    'other': {
        'color': 'grey70',
        'category': 'miscellaneous',
        'priority': 8,
    },
}

# Color codes for rendering (maps to rich color names)
COLOR_MAP = {
    'green': 'green',
    'cyan': 'cyan',
    'yellow': 'yellow',
    'magenta': 'magenta',
    'red': 'red',
    'white': 'white',
    'blue': 'blue',
}

def get_type_priority(type_name: str) -> int:
    """Get priority for a satellite type. Lower = higher priority."""
    if type_name in SATELLITE_TYPES:
        return SATELLITE_TYPES[type_name]['priority']
    return 999  # Unknown types get lowest priority


def get_type_color(type_name: str) -> str:
    """Get color for a satellite type."""
    if type_name in SATELLITE_TYPES:
        return SATELLITE_TYPES[type_name]['color']
    return 'white'


def get_category_color(category: str) -> str:
    """Get color for a category."""
    return CATEGORY_COLORS.get(category, 'white')


def get_enabled_types() -> list[str]:
    """Get list of currently enabled satellite types."""
    return [t for t, cfg in SATELLITE_TYPES.items() if cfg.get('enabled', True)]


def set_type_enabled(type_name: str, enabled: bool) -> None:
    """Enable or disable a satellite type."""
    if type_name in SATELLITE_TYPES:
        SATELLITE_TYPES[type_name]['enabled'] = enabled


def get_types_by_priority() -> list[str]:
    """Get satellite types sorted by priority (highest first)."""
    return sorted(SATELLITE_TYPES.keys(), key=lambda t: SATELLITE_TYPES[t]['priority'])
