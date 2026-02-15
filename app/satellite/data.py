"""
Satellite TLE/OMM data loading and caching.
Loads orbital data from CelesTrak JSON files (OMM format).
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

# Default cache directory (legacy)
ORBITS_DIR = Path(__file__).parent.parent / "files" / "orbits"

# Primary data directory for satellite data
DATA_DIR = Path(__file__).parent.parent / "data"


def load_stations(filepath: Optional[str] = None) -> list[dict]:
    """Load station orbital data from JSON file.
    
    Args:
        filepath: Path to JSON file. If None, loads most recent stations file.
    
    Returns:
        List of satellite OMM records.
    """
    if filepath is None:
        filepath = _find_latest_file("stations")
    
    if filepath is None:
        raise FileNotFoundError(f"No stations file found in {ORBITS_DIR}")
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    return data


def load_group(group_name: str, filepath: Optional[str] = None) -> list[dict]:
    """Load orbital data for a satellite group.
    
    Args:
        group_name: Name of satellite group (e.g., 'stations', 'starlink', 'gps-ops')
        filepath: Path to JSON file. If None, loads most recent file for group.
    
    Returns:
        List of satellite OMM records.
    """
    if filepath is None:
        filepath = _find_latest_file(group_name)
    
    if filepath is None:
        raise FileNotFoundError(f"No {group_name} file found in {ORBITS_DIR}")
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    return data


def _find_latest_file(group_name: str) -> Optional[str]:
    """Find the most recent file for a satellite group.
    
    Files are expected to be named: {group_name}_{date}_{time}.json
    Example: stations_2026-01-31_191500.json
    """
    if not ORBITS_DIR.exists():
        return None
    
    pattern = f"{group_name}_*.json"
    files = list(ORBITS_DIR.glob(pattern))
    
    if not files:
        return None
    
    # Sort by filename (which includes timestamp) - latest last
    files.sort()
    return str(files[-1])


def list_available_files() -> dict[str, list[str]]:
    """List all available orbit data files grouped by satellite group.
    
    Returns:
        Dict mapping group names to list of file paths.
    """
    if not ORBITS_DIR.exists():
        return {}
    
    result = {}
    for f in ORBITS_DIR.glob("*.json"):
        # Extract group name from filename (everything before first underscore with date)
        name = f.stem
        parts = name.rsplit('_', 2)  # Split from right to get group_date_time
        if len(parts) >= 3:
            group = parts[0]
        else:
            group = name
        
        if group not in result:
            result[group] = []
        result[group].append(str(f))
    
    # Sort files within each group
    for group in result:
        result[group].sort()
    
    return result


def get_satellite_by_norad_id(satellites: list[dict], norad_id: int) -> Optional[dict]:
    """Find a satellite by its NORAD catalog ID.
    
    Args:
        satellites: List of satellite OMM records
        norad_id: NORAD catalog ID (e.g., 25544 for ISS)
    
    Returns:
        Satellite record or None if not found.
    """
    for sat in satellites:
        if sat.get('NORAD_CAT_ID') == norad_id:
            return sat
    return None


def get_satellite_by_name(satellites: list[dict], name: str, exact: bool = False) -> Optional[dict]:
    """Find a satellite by name.
    
    Args:
        satellites: List of satellite OMM records
        name: Satellite name to search for
        exact: If True, require exact match. If False, substring match.
    
    Returns:
        First matching satellite record or None.
    """
    name_upper = name.upper()
    for sat in satellites:
        obj_name = sat.get('OBJECT_NAME', '').upper()
        if exact:
            if obj_name == name_upper:
                return sat
        else:
            if name_upper in obj_name:
                return sat
    return None


def parse_epoch(epoch_str: str) -> datetime:
    """Parse OMM epoch string to datetime.
    
    Args:
        epoch_str: ISO format epoch string (e.g., "2026-01-31T09:40:46.607808")
    
    Returns:
        datetime object
    """
    # Handle both with and without microseconds
    try:
        return datetime.fromisoformat(epoch_str)
    except ValueError:
        # Try without microseconds
        return datetime.fromisoformat(epoch_str.split('.')[0])


def discover_satellite_types() -> list[str]:
    """Discover available satellite types from app/data/ directory.
    
    Scans DATA_DIR for JSON files and extracts type from filename prefix.
    Type is the part before the first underscore (e.g., 'stations' from 'stations_2026-01-31_193504.json').
    
    Returns:
        List of unique satellite type names found.
    """
    if not DATA_DIR.exists():
        return []
    
    types = set()
    for f in DATA_DIR.glob("*.json"):
        name = f.stem
        # Extract type: everything before first underscore followed by date pattern
        parts = name.split('_')
        if len(parts) >= 3:
            # Assume format: type_YYYY-MM-DD_HHMMSS
            sat_type = parts[0]
            types.add(sat_type)
    
    return sorted(types)


def _find_latest_data_file(type_name: str) -> Optional[str]:
    """Find the most recent file for a satellite type in DATA_DIR.
    
    Args:
        type_name: Satellite type (e.g., 'stations', 'gps', 'starlink')
    
    Returns:
        Path to latest file or None if not found.
    """
    if not DATA_DIR.exists():
        return None
    
    pattern = f"{type_name}_*.json"
    files = list(DATA_DIR.glob(pattern))
    
    if not files:
        return None
    
    # Sort by filename (timestamp in name) - latest last
    files.sort()
    return str(files[-1])


def load_satellite_types(types: list[str]) -> dict[str, list[dict]]:
    """Load satellite data for multiple types.
    
    Args:
        types: List of satellite type names to load.
               Use ['all'] to load all available types.
    
    Returns:
        Dict mapping type name to list of satellite OMM records.
        Types that fail to load are omitted from result.
    """
    if types == ['all'] or 'all' in types:
        types = discover_satellite_types()
    
    result = {}
    for sat_type in types:
        filepath = _find_latest_data_file(sat_type)
        if filepath is None:
            continue
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            result[sat_type] = data
        except (json.JSONDecodeError, IOError):
            continue
    
    return result


def load_all_satellites_with_types(types: list[str]) -> tuple[list[dict], list[str]]:
    """Load satellites from multiple types and return flat list with type info.
    
    Args:
        types: List of satellite type names to load.
    
    Returns:
        Tuple of (satellites, type_list) where:
        - satellites: Flat list of all satellite OMM records
        - type_list: Parallel list of type names for each satellite
    """
    type_data = load_satellite_types(types)
    
    satellites = []
    type_list = []
    
    for sat_type, sats in type_data.items():
        satellites.extend(sats)
        type_list.extend([sat_type] * len(sats))
    
    return satellites, type_list
