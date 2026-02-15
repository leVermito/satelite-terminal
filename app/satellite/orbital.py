"""
Orbital mechanics calculations for satellite/object positioning.
Optimized for rendering 15k+ objects with vectorized operations.
"""

import time
import numpy as np

try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

EARTH_RADIUS_KM = 6371.0

# Category index constants for color rendering
# These map to CATEGORY_COLORS in satellite.config
CAT_SPECIAL_INTEREST = 0  # green
CAT_WEATHER = 1           # magenta
CAT_COMMUNICATIONS = 2    # yellow
CAT_NAVIGATION = 3        # cyan
CAT_SCIENTIFIC = 4        # blue
CAT_MISCELLANEOUS = 5     # white
CAT_UNKNOWN = 99

# Pre-allocated buffers for grid rendering (reused across frames)
_grid_buffer = None
_grid_buffer_shape = None

# Timing storage for orbital rendering
_orbital_timings = {
    'frustum': 0.0,
    'project': 0.0,
    'stamp': 0.0,
    'total': 0.0,
    'objects_total': 0,
    'objects_visible': 0,
}

def get_orbital_timings():
    """Return current orbital render timing measurements."""
    return _orbital_timings.copy()


def _get_grid_buffer(pixel_height, pixel_width):
    """Get or create reusable grid buffer."""
    global _grid_buffer, _grid_buffer_shape
    shape = (pixel_height, pixel_width)
    if _grid_buffer is None or _grid_buffer_shape != shape:
        _grid_buffer = np.zeros(shape, dtype=np.uint8)
        _grid_buffer_shape = shape
    else:
        _grid_buffer.fill(0)
    return _grid_buffer


if HAS_NUMBA:
    @njit(cache=True, parallel=True)
    def _stamp_pixels_numba(grid, px, py, visible, pixel_width, pixel_height):
        """Numba-optimized pixel stamping for orbital objects."""
        n = len(px)
        for i in prange(n):
            if visible[i]:
                opx, opy = px[i], py[i]
                # Bounds check for single pixel
                if opx >= 0 and opx < pixel_width and opy >= 0 and opy < pixel_height:
                    grid[opy, opx] = 1


def render_orbital_grid(orbital_positions, pixel_width, pixel_height, center_lon, center_lat, zoom, orbital_altitudes=None):
    """Render orbital objects to a pixel grid.
    
    Optimized for 15k+ objects with:
    - Frustum culling before projection
    - Vectorized numpy operations
    - Numba JIT for pixel stamping
    - Buffer reuse across frames
    - Support for multiple altitude levels
    """
    global _grid_buffer, _grid_buffer_shape, _orbital_timings
    
    t_total_start = time.perf_counter()
    
    # Reuse buffer if same size, otherwise allocate new
    shape = (pixel_height, pixel_width)
    if _grid_buffer is None or _grid_buffer_shape != shape:
        _grid_buffer = np.zeros(shape, dtype=np.uint8)
        _grid_buffer_shape = shape
    else:
        _grid_buffer.fill(0)
    
    orbital_grid = _grid_buffer
    
    if orbital_positions is None or len(orbital_positions) == 0:
        _orbital_timings['total'] = (time.perf_counter() - t_total_start) * 1000
        _orbital_timings['objects_total'] = 0
        _orbital_timings['objects_visible'] = 0
        return orbital_grid
    
    _orbital_timings['objects_total'] = len(orbital_positions)
    
    # --- No frustum culling for satellites ---
    # Frustum culling has edge cases with polar views and longitude wraparound
    # For typical satellite counts (<10k), just process all and let visibility check handle it
    t_frustum_start = time.perf_counter()
    
    filtered_positions = orbital_positions
    if orbital_altitudes is None:
        raise ValueError("orbital_altitudes is required - real satellite altitudes must be provided")
    filtered_altitudes = orbital_altitudes
    
    _orbital_timings['frustum'] = (time.perf_counter() - t_frustum_start) * 1000
    
    # --- Projection math (vectorized) ---
    t_project_start = time.perf_counter()
    base_radius = min(pixel_width, pixel_height) // 2 - 2
    radius = int(base_radius * zoom)
    cx, cy = pixel_width // 2, pixel_height // 2
    
    center_lon_rad = np.radians(center_lon)
    center_lat_rad = np.radians(center_lat)
    sin_clat = np.sin(center_lat_rad)
    cos_clat = np.cos(center_lat_rad)
    
    # Calculate orbital radius for each satellite based on its altitude
    orbital_scales = (EARTH_RADIUS_KM + filtered_altitudes) / EARTH_RADIUS_KM
    orbital_radii = (radius * orbital_scales).astype(np.int32)
    
    obj_lons = np.radians(filtered_positions[:, 0])
    obj_lats = np.radians(filtered_positions[:, 1])
    
    sin_obj_lats = np.sin(obj_lats)
    cos_obj_lats = np.cos(obj_lats)
    delta_lon = obj_lons - center_lon_rad
    cos_delta = np.cos(delta_lon)
    
    # Calculate 3D position of satellites in Earth-centered coordinates
    # Satellite position = (R + h) * unit_vector_from_lat_lon
    sat_x = cos_obj_lats * np.cos(obj_lons)  # towards lon=0
    sat_y = cos_obj_lats * np.sin(obj_lons)  # towards lon=90
    sat_z = sin_obj_lats                      # towards north pole
    
    # View direction (from infinity towards Earth center, looking at center_lat, center_lon)
    # In orthographic projection, we need the z-component in view space
    # View space: z points towards viewer, x points right, y points up
    # Transform satellite position to view coordinates
    
    # Rotation: first rotate around z-axis by -center_lon, then around x-axis by -(90-center_lat)
    # Simplified: the z-component in view space (towards viewer) is:
    # z_view = sin(lat)*sin(center_lat) + cos(lat)*cos(center_lat)*cos(lon - center_lon)
    # This is exactly cos_c - the angle between satellite direction and view direction
    
    cos_c = sin_clat * sin_obj_lats + cos_clat * cos_obj_lats * cos_delta
    
    # For satellites at altitude, they're visible if their 3D position is in front of Earth's limb
    # The satellite is at distance (R+h) from Earth center
    # Earth's limb (as seen from infinity) is at distance R from center
    # A satellite is visible if its projection onto the view axis is positive
    # OR if it's above the Earth's limb even when behind the center
    
    # For orthographic projection from infinity:
    # - Satellite is always visible if cos_c >= 0 (in front hemisphere)
    # - Satellite at altitude h is also visible if it's above Earth's limb
    #   The limb condition: the satellite's perpendicular distance from view axis > R
    #   means it would appear outside Earth's disk
    
    # Perpendicular distance from view axis (normalized to unit sphere)
    perp_dist_sq = 1.0 - cos_c * cos_c  # sin^2(angle)
    
    # Satellite appears outside Earth disk if: (R+h) * sin(angle) > R
    # i.e., sin(angle) > R/(R+h)
    # i.e., sin^2(angle) > (R/(R+h))^2
    r_ratio = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + filtered_altitudes)
    r_ratio_sq = r_ratio * r_ratio
    
    # Satellite is visible if:
    # 1. It's in front hemisphere (cos_c >= 0), OR
    # 2. It's behind but appears outside Earth's disk (perp_dist_sq > r_ratio_sq)
    visible = (cos_c >= 0) | (perp_dist_sq > r_ratio_sq)
    
    # Project to screen coordinates (using per-satellite orbital radius)
    x = cos_obj_lats * np.sin(delta_lon)
    y = cos_clat * sin_obj_lats - sin_clat * cos_obj_lats * cos_delta
    
    px = (cx + x * orbital_radii).astype(np.int32)
    py = (cy - y * orbital_radii).astype(np.int32)
    
    _orbital_timings['project'] = (time.perf_counter() - t_project_start) * 1000
    _orbital_timings['objects_visible'] = int(np.sum(visible))
    
    # --- Pixel stamping ---
    t_stamp_start = time.perf_counter()
    if HAS_NUMBA:
        _stamp_pixels_numba(orbital_grid, px, py, visible, pixel_width, pixel_height)
    else:
        # Vectorized fallback: filter to visible and bounds-valid
        vis_px = px[visible]
        vis_py = py[visible]
        
        # Bounds check for single pixel
        valid = (vis_px >= 0) & (vis_px < pixel_width) & (vis_py >= 0) & (vis_py < pixel_height)
        vis_px = vis_px[valid]
        vis_py = vis_py[valid]
        
        # Stamp single pixel
        orbital_grid[vis_py, vis_px] = 1
    
    _orbital_timings['stamp'] = (time.perf_counter() - t_stamp_start) * 1000
    _orbital_timings['total'] = (time.perf_counter() - t_total_start) * 1000
    
    return orbital_grid


def render_orbital_grid_typed(orbital_positions, orbital_altitudes, orbital_types,
                               pixel_width, pixel_height, center_lon, center_lat, zoom,
                               enabled_types=None):
    """Render orbital objects to a pixel grid with type information for coloring.
    
    Args:
        orbital_positions: Array of [lon, lat] positions
        orbital_altitudes: Array of altitudes in km
        orbital_types: Array of category indices (0=special-interest, 1=weather, etc.)
        pixel_width, pixel_height: Grid dimensions
        center_lon, center_lat: View center
        zoom: Zoom level
        enabled_types: Set of enabled type indices (None = all enabled)
    
    Returns:
        Grid of category indices (0 = empty, 1-6 = category+1 for priority coloring)
        Higher priority types overwrite lower priority.
    """
    global _orbital_timings
    
    t_total_start = time.perf_counter()
    
    # Use uint8 grid where 0=empty, values 1-100 represent category_idx+1
    orbital_grid = np.zeros((pixel_height, pixel_width), dtype=np.uint8)
    
    if orbital_positions is None or len(orbital_positions) == 0:
        _orbital_timings['total'] = (time.perf_counter() - t_total_start) * 1000
        _orbital_timings['objects_total'] = 0
        _orbital_timings['objects_visible'] = 0
        return orbital_grid
    
    _orbital_timings['objects_total'] = len(orbital_positions)
    
    t_frustum_start = time.perf_counter()
    
    # Filter by enabled types if specified
    if enabled_types is not None:
        type_mask = np.isin(orbital_types, list(enabled_types))
        filtered_positions = orbital_positions[type_mask]
        filtered_altitudes = orbital_altitudes[type_mask]
        filtered_types = orbital_types[type_mask]
    else:
        filtered_positions = orbital_positions
        filtered_altitudes = orbital_altitudes
        filtered_types = orbital_types
    
    if len(filtered_positions) == 0:
        _orbital_timings['total'] = (time.perf_counter() - t_total_start) * 1000
        return orbital_grid
    
    _orbital_timings['frustum'] = (time.perf_counter() - t_frustum_start) * 1000
    
    # --- Projection math (vectorized) ---
    t_project_start = time.perf_counter()
    base_radius = min(pixel_width, pixel_height) // 2 - 2
    radius = int(base_radius * zoom)
    cx, cy = pixel_width // 2, pixel_height // 2
    
    center_lon_rad = np.radians(center_lon)
    center_lat_rad = np.radians(center_lat)
    sin_clat = np.sin(center_lat_rad)
    cos_clat = np.cos(center_lat_rad)
    
    orbital_scales = (EARTH_RADIUS_KM + filtered_altitudes) / EARTH_RADIUS_KM
    orbital_radii = (radius * orbital_scales).astype(np.int32)
    
    obj_lons = np.radians(filtered_positions[:, 0])
    obj_lats = np.radians(filtered_positions[:, 1])
    
    sin_obj_lats = np.sin(obj_lats)
    cos_obj_lats = np.cos(obj_lats)
    delta_lon = obj_lons - center_lon_rad
    cos_delta = np.cos(delta_lon)
    
    cos_c = sin_clat * sin_obj_lats + cos_clat * cos_obj_lats * cos_delta
    
    perp_dist_sq = 1.0 - cos_c * cos_c
    r_ratio = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + filtered_altitudes)
    r_ratio_sq = r_ratio * r_ratio
    
    visible = (cos_c >= 0) | (perp_dist_sq > r_ratio_sq)
    
    x = cos_obj_lats * np.sin(delta_lon)
    y = cos_clat * sin_obj_lats - sin_clat * cos_obj_lats * cos_delta
    
    px = (cx + x * orbital_radii).astype(np.int32)
    py = (cy - y * orbital_radii).astype(np.int32)
    
    _orbital_timings['project'] = (time.perf_counter() - t_project_start) * 1000
    _orbital_timings['objects_visible'] = int(np.sum(visible))
    
    # --- Pixel stamping with type priority ---
    t_stamp_start = time.perf_counter()
    
    # Vectorized stamping with type priority
    # Filter to visible and bounds-valid pixels
    valid = visible & (px >= 0) & (px < pixel_width) & (py >= 0) & (py < pixel_height)
    valid_px = px[valid]
    valid_py = py[valid]
    valid_types = filtered_types[valid]
    
    # Sort by type descending (high priority types stamped last to overwrite)
    order = np.argsort(-valid_types)
    orbital_grid[valid_py[order], valid_px[order]] = valid_types[order] + 1
    
    _orbital_timings['stamp'] = (time.perf_counter() - t_stamp_start) * 1000
    _orbital_timings['total'] = (time.perf_counter() - t_total_start) * 1000
    
    return orbital_grid


# Map satellite type name to category index
# This determines the color used for rendering on the map
TYPE_NAME_TO_INDEX = {
    # Special-interest (green)
    'stations': CAT_SPECIAL_INTEREST,
    'analyst': CAT_SPECIAL_INTEREST,
    'russian-asat-debris': CAT_SPECIAL_INTEREST,
    'chinese-asat-debris': CAT_SPECIAL_INTEREST,
    'iridium-33-debris': CAT_SPECIAL_INTEREST,
    'cosmos-2251-debris': CAT_SPECIAL_INTEREST,
    
    # Weather (magenta)
    'noaa': CAT_WEATHER,
    'goes': CAT_WEATHER,
    'earth-resources': CAT_WEATHER,
    'sarsat': CAT_WEATHER,
    'disaster-monitoring': CAT_WEATHER,
    'tdrss': CAT_WEATHER,
    'argos': CAT_WEATHER,
    'planet': CAT_WEATHER,
    'spire': CAT_WEATHER,
    
    # Communications (yellow)
    'starlink': CAT_COMMUNICATIONS,
    'oneweb': CAT_COMMUNICATIONS,
    'qianfan': CAT_COMMUNICATIONS,
    'hulianwang-digui': CAT_COMMUNICATIONS,
    'kuiper': CAT_COMMUNICATIONS,
    'iridium-next': CAT_COMMUNICATIONS,
    'globalstar': CAT_COMMUNICATIONS,
    'orbcomm': CAT_COMMUNICATIONS,
    'intelsat': CAT_COMMUNICATIONS,
    'ses': CAT_COMMUNICATIONS,
    'eutelsat': CAT_COMMUNICATIONS,
    'telesat': CAT_COMMUNICATIONS,
    'active-geosynchronous': CAT_COMMUNICATIONS,
    'movers': CAT_COMMUNICATIONS,
    'geo-protected-zone-plus': CAT_COMMUNICATIONS,
    'amateur': CAT_COMMUNICATIONS,
    'satnogs': CAT_COMMUNICATIONS,
    'experimental-comm': CAT_COMMUNICATIONS,
    'other-comm': CAT_COMMUNICATIONS,
    
    # Navigation (cyan)
    'gps-ops': CAT_NAVIGATION,
    'glonass-ops': CAT_NAVIGATION,
    'galileo': CAT_NAVIGATION,
    'beidou': CAT_NAVIGATION,
    'sbas': CAT_NAVIGATION,
    'nnss': CAT_NAVIGATION,
    'russian-leo-navigation': CAT_NAVIGATION,
    'gps': CAT_NAVIGATION,  # Legacy alias
    
    # Scientific (blue)
    'space-earth-science': CAT_SCIENTIFIC,
    'geodetic': CAT_SCIENTIFIC,
    'engineering': CAT_SCIENTIFIC,
    'education': CAT_SCIENTIFIC,
    
    # Miscellaneous (white)
    'military': CAT_MISCELLANEOUS,
    'radar-calibration': CAT_MISCELLANEOUS,
    'cubesats': CAT_MISCELLANEOUS,
    'other': CAT_MISCELLANEOUS,
    
    # Legacy aliases
    'weather': CAT_WEATHER,
}

def get_type_index(type_name: str) -> int:
    """Convert type name to category index."""
    return TYPE_NAME_TO_INDEX.get(type_name, CAT_UNKNOWN)
