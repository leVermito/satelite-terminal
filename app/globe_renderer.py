"""
Globe rendering functions for braille terminal output.
Optimized with Numba JIT compilation for line drawing.
"""

import time
import numpy as np
from rich.text import Text
from datetime import datetime, timezone

try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

# Global timing storage for debug overlay
_render_timings = {
    'frustum': 0.0,
    'project': 0.0,
    'lines': 0.0,
    'braille': 0.0,
    'total': 0.0,
    'segments_total': 0,
    'segments_drawn': 0,
}

def get_render_timings():
    """Return current render timing measurements."""
    return _render_timings.copy()

BRAILLE_BASE = 0x2800

BRAILLE_WEIGHTS = np.array([
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
], dtype=np.uint8)

COLOR_LIGHT_BLUE = 'cyan'
COLOR_WHITE = 'white'
COLOR_YELLOW = 'yellow'
COLOR_GREEN = 'green'
COLOR_MAGENTA = 'magenta'
COLOR_RED = 'red'
COLOR_BLUE = 'blue'

# Category colors for satellite rendering (indexed by category from orbital.py)
# Must match CAT_* constants: 0=special-interest, 1=weather, 2=communications, 3=navigation, 4=scientific, 5=miscellaneous
SATELLITE_TYPE_COLORS = [
    COLOR_GREEN,    # 0: special-interest (stations, debris)
    COLOR_MAGENTA,  # 1: weather
    COLOR_YELLOW,   # 2: communications (starlink, etc.)
    COLOR_LIGHT_BLUE,  # 3: navigation (GPS, GLONASS, etc.)
    COLOR_BLUE,     # 4: scientific
    COLOR_WHITE,    # 5: miscellaneous
]

DETAILED_VIEW_RATIO = 0.5
MAP_RESOLUTION_RATIO = 0.5  # 0=use 110m (coarse), 1=use 50m (detailed)
RIVERS_DETAIL_RATIO = 0.5   # 0=rivers at high zoom only, 1=rivers always visible
CITIES_DETAIL_RATIO = 0.5   # 0=cities at high zoom only, 1=cities always visible


def calculate_city_display_threshold(term_width, term_height, cities_ratio=None):
    """Calculate minimum zoom level for displaying city names based on terminal size."""
    import math
    term_area = term_width * term_height
    reference_area = 10000
    
    max_threshold = 20.0
    min_threshold = 2.0
    
    ratio = cities_ratio if cities_ratio is not None else CITIES_DETAIL_RATIO
    base = max_threshold - (max_threshold - min_threshold) * ratio
    area_factor = math.sqrt(reference_area / max(term_area, 1))
    threshold = base * area_factor
    
    return max(2.0, min(25.0, threshold))


def calculate_rivers_display_threshold(term_width, term_height, rivers_ratio=None):
    """Calculate minimum zoom level for displaying rivers based on terminal size."""
    import math
    term_area = term_width * term_height
    reference_area = 10000
    
    max_threshold = 20.0
    min_threshold = 2.0
    
    ratio = rivers_ratio if rivers_ratio is not None else RIVERS_DETAIL_RATIO
    base = max_threshold - (max_threshold - min_threshold) * ratio
    area_factor = math.sqrt(reference_area / max(term_area, 1))
    threshold = base * area_factor
    
    return max(2.0, min(25.0, threshold))


def calculate_map_resolution_threshold(term_width, term_height):
    """Calculate zoom threshold for switching from 110m to 50m map resolution."""
    return calculate_map_resolution_threshold_with_ratio(term_width, term_height, MAP_RESOLUTION_RATIO)


def calculate_map_resolution_threshold_with_ratio(term_width, term_height, lod_ratio):
    """Calculate zoom threshold for switching from 110m to 50m map resolution.
    
    Returns zoom level at which to switch to detailed (50m) map.
    lod_ratio controls this:
      0 = always use 110m (coarse)
      1 = always use 50m (detailed)
      0.5 = switch at moderate zoom based on terminal size
    """
    import math
    term_area = term_width * term_height
    reference_area = 10000  # 200x50 terminal
    
    # Base threshold range: switch between zoom 1.0 and 5.0
    max_threshold = 5.0   # at ratio=0, need high zoom to get 50m
    min_threshold = 1.0   # at ratio=1, use 50m even at zoom 1
    
    # Interpolate based on lod_ratio (inverted: higher ratio = lower threshold)
    base = max_threshold - (max_threshold - min_threshold) * lod_ratio
    
    # Adjust for terminal size (larger terminal = lower threshold)
    area_factor = math.sqrt(reference_area / max(term_area, 1))
    threshold = base * area_factor
    
    return max(1.0, min(10.0, threshold))


if HAS_NUMBA:
    @njit(cache=True)
    def draw_line_bresenham(grid, x0, y0, x1, y1, height, width):
        """Numba-optimized Bresenham line drawing."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        while True:
            if 0 <= y0 < height and 0 <= x0 < width:
                grid[y0, x0] = 1
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    @njit(cache=True)
    def project_coords(lons, lats, center_lon_rad, sin_clat, cos_clat, cx, cy, radius):
        """Numba-optimized coordinate projection."""
        n = len(lons)
        px = np.empty(n, dtype=np.int32)
        py = np.empty(n, dtype=np.int32)
        visible = np.empty(n, dtype=np.bool_)
        
        for i in range(n):
            lon_rad = lons[i] * 0.017453292519943295  # np.pi / 180
            lat_rad = lats[i] * 0.017453292519943295
            
            sin_lat = np.sin(lat_rad)
            cos_lat = np.cos(lat_rad)
            delta_lon = lon_rad - center_lon_rad
            cos_delta = np.cos(delta_lon)
            
            cos_c = sin_clat * sin_lat + cos_clat * cos_lat * cos_delta
            visible[i] = cos_c >= 0
            
            x = cos_lat * np.sin(delta_lon)
            y = cos_clat * sin_lat - sin_clat * cos_lat * cos_delta
            
            px[i] = int(cx + x * radius)
            py[i] = int(cy - y * radius)
        
        return px, py, visible

    @njit(cache=True)
    def draw_segments_numba(grid, all_px, all_py, all_visible, seg_starts, seg_lengths, height, width):
        """Draw all segments using Numba."""
        n_segs = len(seg_starts)
        for seg_idx in range(n_segs):
            start = seg_starts[seg_idx]
            length = seg_lengths[seg_idx]
            
            for i in range(length - 1):
                idx = start + i
                if all_visible[idx] and all_visible[idx + 1]:
                    x0, y0 = all_px[idx], all_py[idx]
                    x1, y1 = all_px[idx + 1], all_py[idx + 1]
                    
                    dx = abs(x1 - x0)
                    dy = abs(y1 - y0)
                    sx = 1 if x0 < x1 else -1
                    sy = 1 if y0 < y1 else -1
                    err = dx - dy
                    
                    while True:
                        if 0 <= y0 < height and 0 <= x0 < width:
                            grid[y0, x0] = 1
                        if x0 == x1 and y0 == y1:
                            break
                        e2 = 2 * err
                        if e2 > -dy:
                            err -= dy
                            x0 += sx
                        if e2 < dx:
                            err += dx
                            y0 += sy
else:
    def draw_line_bresenham(grid, x0, y0, x1, y1, height, width):
        """Pure Python Bresenham line drawing fallback."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        while True:
            if 0 <= y0 < height and 0 <= x0 < width:
                grid[y0, x0] = 1
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy


def pixels_to_braille_colored(border_grid, river_grid, orbital_grid=None, gps_grid=None):
    """Convert pixel grids to colored braille output using Rich Text objects."""
    pixel_h, pixel_w = border_grid.shape
    
    pad_h = (4 - pixel_h % 4) % 4
    pad_w = (2 - pixel_w % 2) % 2
    if pad_h or pad_w:
        border_grid = np.pad(border_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        river_grid = np.pad(river_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        if orbital_grid is not None:
            orbital_grid = np.pad(orbital_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        if gps_grid is not None:
            gps_grid = np.pad(gps_grid, ((0, pad_h), (0, pad_w)), mode='constant')
    
    pixel_h, pixel_w = border_grid.shape
    char_h, char_w = pixel_h // 4, pixel_w // 2
    
    if orbital_grid is None:
        orbital_grid = np.zeros_like(border_grid)
    if gps_grid is None:
        gps_grid = np.zeros_like(border_grid)
    
    border_blocks = border_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    river_blocks = river_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    orbital_blocks = orbital_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    gps_blocks = gps_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    
    combined_blocks = border_blocks | river_blocks | orbital_blocks | gps_blocks
    weights = BRAILLE_WEIGHTS.reshape(1, 1, 4, 2).astype(np.uint16)
    codes = BRAILLE_BASE + np.sum(combined_blocks * weights, axis=(2, 3))
    
    has_border = np.any(border_blocks, axis=(2, 3))
    has_river = np.any(river_blocks, axis=(2, 3))
    has_orbital = np.any(orbital_blocks, axis=(2, 3))
    has_gps = np.any(gps_blocks, axis=(2, 3))
    
    result = []
    for cy in range(char_h):
        row_text = Text()
        row_codes = codes[cy]
        row_border = has_border[cy]
        row_river = has_river[cy]
        row_orbital = has_orbital[cy]
        row_gps = has_gps[cy]
        
        current_color = None
        current_chars = []
        
        for cx in range(char_w):
            if row_gps[cx]:
                color = COLOR_GREEN
            elif row_orbital[cx]:
                color = COLOR_YELLOW
            elif row_river[cx] and not row_border[cx]:
                color = COLOR_LIGHT_BLUE
            elif row_river[cx] and row_border[cx]:
                color = COLOR_LIGHT_BLUE
            elif row_border[cx]:
                color = COLOR_WHITE
            else:
                color = None
            
            char = chr(row_codes[cx])
            
            if color == current_color:
                current_chars.append(char)
            else:
                if current_chars:
                    row_text.append(''.join(current_chars), style=current_color)
                current_chars = [char]
                current_color = color
        
        if current_chars:
            row_text.append(''.join(current_chars), style=current_color)
        
        result.append(row_text)
    
    return result


def pixels_to_braille_colored_typed(border_grid, river_grid, orbital_typed_grid=None, gps_grid=None, shadow_grid=None, shadow_mode="ALL", in_globe_grid=None):
    """Convert pixel grids to colored braille output with multi-color satellite support.
    
    Args:
        border_grid: Boolean grid for borders
        river_grid: Boolean grid for rivers
        orbital_typed_grid: uint8 grid where 0=empty, 1-5=satellite type+1
        gps_grid: Boolean grid for GPS position
        shadow_grid: Boolean grid where True = in shadow (night side)
        shadow_mode: "ALL" (bg+borders), "BG" (background only), "BORDERS" (borders only), "OFF"
        in_globe_grid: Boolean grid where True = inside globe circle
    
    Returns:
        List of Rich Text objects, one per character row
    """
    pixel_h, pixel_w = border_grid.shape
    
    pad_h = (4 - pixel_h % 4) % 4
    pad_w = (2 - pixel_w % 2) % 2
    if pad_h or pad_w:
        border_grid = np.pad(border_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        river_grid = np.pad(river_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        if orbital_typed_grid is not None:
            orbital_typed_grid = np.pad(orbital_typed_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        if gps_grid is not None:
            gps_grid = np.pad(gps_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        if shadow_grid is not None:
            shadow_grid = np.pad(shadow_grid, ((0, pad_h), (0, pad_w)), mode='constant')
    
    pixel_h, pixel_w = border_grid.shape
    char_h, char_w = pixel_h // 4, pixel_w // 2
    
    if orbital_typed_grid is None:
        orbital_typed_grid = np.zeros((pixel_h, pixel_w), dtype=np.uint8)
    if gps_grid is None:
        gps_grid = np.zeros_like(border_grid)
    
    border_blocks = border_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    river_blocks = river_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    orbital_blocks = orbital_typed_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    gps_blocks = gps_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
    
    # Process shadow grid - a cell is in shadow if majority of its pixels are shadowed
    # Also track which cells are inside the globe (for background coloring)
    if shadow_grid is not None:
        shadow_blocks = shadow_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
        shadow_count = np.sum(shadow_blocks, axis=(2, 3))
        is_shadowed = shadow_count >= 4  # At least half of 8 pixels in shadow
    else:
        is_shadowed = np.zeros((char_h, char_w), dtype=bool)
    
    # Process in_globe_grid if provided (for lit area background coloring)
    if in_globe_grid is not None:
        if pad_h or pad_w:
            in_globe_grid = np.pad(in_globe_grid, ((0, pad_h), (0, pad_w)), mode='constant')
        globe_blocks = in_globe_grid.reshape(char_h, 4, char_w, 2).transpose(0, 2, 1, 3)
        globe_count = np.sum(globe_blocks, axis=(2, 3))
        is_in_globe = globe_count >= 4  # At least half of 8 pixels inside globe
    else:
        is_in_globe = np.zeros((char_h, char_w), dtype=bool)
    
    # For braille codes, we need boolean presence
    orbital_bool = orbital_blocks > 0
    combined_blocks = border_blocks | river_blocks | orbital_bool | gps_blocks
    weights = BRAILLE_WEIGHTS.reshape(1, 1, 4, 2).astype(np.uint16)
    codes = BRAILLE_BASE + np.sum(combined_blocks * weights, axis=(2, 3))
    
    has_border = np.any(border_blocks, axis=(2, 3))
    has_river = np.any(river_blocks, axis=(2, 3))
    has_gps = np.any(gps_blocks, axis=(2, 3))
    
    # For orbital, get the minimum type index in each character cell (highest priority)
    # Replace 0 with 255 so min() ignores empty pixels
    orbital_for_min = np.where(orbital_blocks > 0, orbital_blocks, 255)
    orbital_min_type = np.min(orbital_for_min, axis=(2, 3))  # Shape: (char_h, char_w)
    has_orbital = orbital_min_type < 255
    
    result = []
    for cy in range(char_h):
        row_text = Text()
        row_codes = codes[cy]
        row_border = has_border[cy]
        row_river = has_river[cy]
        row_orbital = has_orbital[cy]
        row_orbital_type = orbital_min_type[cy]
        row_gps = has_gps[cy]
        row_shadow = is_shadowed[cy]
        row_in_globe = is_in_globe[cy]
        
        current_style = None
        current_chars = []
        
        for cx in range(char_w):
            in_shadow = row_shadow[cx]
            in_globe = row_in_globe[cx]
            
            # Determine shadow effects based on shadow_mode
            # ALL = background + border dimming, BG = background only, BORDERS = border dimming only, OFF = none
            # Background is applied to LIT (sunny) areas, not shadow areas
            is_lit = in_globe and not in_shadow
            apply_bg = is_lit and shadow_mode in ("ALL", "BG")
            apply_dim = in_shadow and shadow_mode in ("ALL", "BORDERS")
            bg_suffix = ' on grey23' if apply_bg else ''
            
            if row_gps[cx]:
                style = COLOR_GREEN + bg_suffix
            elif row_orbital[cx]:
                # Get satellite type color (type_idx = value - 1)
                type_idx = row_orbital_type[cx] - 1
                if 0 <= type_idx < len(SATELLITE_TYPE_COLORS):
                    style = SATELLITE_TYPE_COLORS[type_idx] + bg_suffix
                else:
                    style = COLOR_YELLOW + bg_suffix
            elif row_river[cx]:
                if apply_dim:
                    style = 'blue' + bg_suffix
                else:
                    style = COLOR_LIGHT_BLUE + bg_suffix
            elif row_border[cx]:
                if apply_dim:
                    style = 'dim white' + bg_suffix
                else:
                    style = COLOR_WHITE + bg_suffix
            elif apply_bg:
                # Empty cell inside globe in lit area - use background color only
                style = 'on grey23'
            else:
                style = None
            
            char = chr(row_codes[cx])
            
            if style == current_style:
                current_chars.append(char)
            else:
                if current_chars:
                    row_text.append(''.join(current_chars), style=current_style)
                current_chars = [char]
                current_style = style
        
        if current_chars:
            row_text.append(''.join(current_chars), style=current_style)
        
        result.append(row_text)
    
    return result


def render_globe_with_layers(segments, segment_bounds, river_segments, river_bounds,
                              width, height, center_lon, center_lat, zoom=1.0, 
                              cities=None, city_names=None, term_width=None, term_height=None,
                              orbital_positions=None,
                              segments_coarse=None, segment_bounds_coarse=None,
                              lod_ratio=None, rivers_ratio=None, cities_ratio=None,
                              flat_data=None, flat_data_coarse=None, river_flat_data=None):
    """Render globe with separate layers for borders, rivers, and orbital objects.
    
    Args:
        segments, segment_bounds: Detailed (50m) map data
        segments_coarse, segment_bounds_coarse: Coarse (110m) map data for low zoom
        flat_data, flat_data_coarse, river_flat_data: Pre-computed flattened arrays for fast projection
        lod_ratio: Map resolution ratio (0=coarse, 1=detailed)
        rivers_ratio: Rivers detail ratio (0=high zoom only, 1=always visible)
        cities_ratio: Cities detail ratio (0=high zoom only, 1=always visible)
        Other args: rendering parameters
    """
    global _render_timings
    t_total_start = time.perf_counter()
    
    border_grid = np.zeros((height, width), dtype=np.uint8)
    river_grid = np.zeros((height, width), dtype=np.uint8)
    orbital_grid = np.zeros((height, width), dtype=np.uint8)
    labels = []
    
    base_radius = min(width, height) // 2 - 2
    radius = int(base_radius * zoom)
    cx, cy = width // 2, height // 2
    
    center_lon_rad = np.radians(center_lon)
    center_lat_rad = np.radians(center_lat)
    sin_clat = np.sin(center_lat_rad)
    cos_clat = np.cos(center_lat_rad)
    
    angles = np.linspace(0, 2 * np.pi, 180)
    outline_x = (cx + radius * np.cos(angles)).astype(np.int32)
    outline_y = (cy + radius * np.sin(angles)).astype(np.int32)
    valid = (outline_x >= 0) & (outline_x < width) & (outline_y >= 0) & (outline_y < height)
    border_grid[outline_y[valid], outline_x[valid]] = 1
    
    city_threshold = calculate_city_display_threshold(term_width or width // 2, term_height or height // 4, cities_ratio)
    rivers_threshold = calculate_rivers_display_threshold(term_width or width // 2, term_height or height // 4, rivers_ratio)
    
    # Calculate map resolution threshold based on lod_ratio
    # Higher ratio = switch to detailed (50m) at lower zoom
    # Lower ratio = stay on coarse (110m) longer
    effective_lod = lod_ratio if lod_ratio is not None else MAP_RESOLUTION_RATIO
    map_res_threshold = calculate_map_resolution_threshold_with_ratio(term_width or width // 2, term_height or height // 4, effective_lod)
    
    aspect_diagonal = np.sqrt(width**2 + height**2) / min(width, height)
    corner_factor = aspect_diagonal * 1.2
    visible_angular_radius = (90.0 / zoom) * corner_factor if zoom > 1 else 180.0
    
    min_visible_lon = center_lon - visible_angular_radius
    max_visible_lon = center_lon + visible_angular_radius
    min_visible_lat = max(-90, center_lat - visible_angular_radius)
    max_visible_lat = min(90, center_lat + visible_angular_radius)
    
    lon_wraps = min_visible_lon < -180 or max_visible_lon > 180
    
    if cities is not None and len(cities) > 0 and zoom >= city_threshold:
        if zoom > 1.5:
            city_lons_deg = cities[:, 0]
            city_lats_deg = cities[:, 1]
            
            lat_mask = (city_lats_deg >= min_visible_lat) & (city_lats_deg <= max_visible_lat)
            
            if lon_wraps:
                lon_mask = np.ones(len(cities), dtype=bool)
            else:
                lon_mask = (city_lons_deg >= min_visible_lon) & (city_lons_deg <= max_visible_lon)
            
            visible_mask = lat_mask & lon_mask
            filtered_cities = cities[visible_mask]
            filtered_indices = np.where(visible_mask)[0]
        else:
            filtered_cities = cities
            filtered_indices = np.arange(len(cities))
        
        if len(filtered_cities) > 0:
            city_lons = np.radians(filtered_cities[:, 0])
            city_lats = np.radians(filtered_cities[:, 1])
            
            sin_city_lats = np.sin(city_lats)
            cos_city_lats = np.cos(city_lats)
            delta_lon = city_lons - center_lon_rad
            cos_delta = np.cos(delta_lon)
            
            cos_c = sin_clat * sin_city_lats + cos_clat * cos_city_lats * cos_delta
            visible = cos_c >= 0
            
            x = cos_city_lats * np.sin(delta_lon)
            y = cos_clat * sin_city_lats - sin_clat * cos_city_lats * cos_delta
            
            px = (cx + x * radius).astype(np.int32)
            py = (cy - y * radius).astype(np.int32)
            
            for i in range(len(filtered_cities)):
                if visible[i]:
                    cpx, cpy = px[i], py[i]
                    if 0 <= cpx < width and 0 <= cpy < height:
                        for ddx in range(-1, 2):
                            for ddy in range(-1, 2):
                                npx, npy = cpx + ddx, cpy + ddy
                                if 0 <= npx < width and 0 <= npy < height:
                                    border_grid[npy, npx] = 1
                        orig_idx = filtered_indices[i]
                        if city_names and orig_idx < len(city_names) and city_names[orig_idx]:
                            char_x = cpx // 2 + 1
                            char_y = cpy // 4
                            labels.append((char_x, char_y, city_names[orig_idx]))
    
    # Timing accumulators for this render call
    t_frustum_acc = 0.0
    t_project_acc = 0.0
    t_lines_acc = 0.0
    segments_total = 0
    segments_drawn = 0
    
    def draw_segments_to_grid(segs, bounds, grid):
        nonlocal t_frustum_acc, t_project_acc, t_lines_acc, segments_total, segments_drawn
        if segs is None:
            return
        
        segments_total += len(segs)
        
        if HAS_NUMBA and len(segs) > 10:
            # Frustum culling phase - vectorized numpy approach
            t_frustum_start = time.perf_counter()
            
            if bounds is not None and zoom > 1.5:
                # Vectorized bounds check using numpy boolean indexing
                # bounds array: [min_lon, max_lon, min_lat, max_lat] per segment
                lat_mask = (bounds[:, 3] >= min_visible_lat) & (bounds[:, 2] <= max_visible_lat)
                
                if lon_wraps:
                    lon_mask = np.ones(len(bounds), dtype=bool)
                else:
                    lon_mask = (bounds[:, 1] >= min_visible_lon) & (bounds[:, 0] <= max_visible_lon)
                
                visible_mask = lat_mask & lon_mask
                visible_indices = np.where(visible_mask)[0]
                
                # Filter segments using indices (still need list comprehension but much smaller)
                filtered_segs = [segs[i] for i in visible_indices if len(segs[i]) >= 2]
            else:
                filtered_segs = [c for c in segs if len(c) >= 2]
            
            t_frustum_acc += time.perf_counter() - t_frustum_start
            
            segments_drawn += len(filtered_segs)
            
            if not filtered_segs:
                return
            
            # Prepare arrays for projection
            t_project_start = time.perf_counter()
            total_points = sum(len(c) for c in filtered_segs)
            all_lons = np.empty(total_points, dtype=np.float32)
            all_lats = np.empty(total_points, dtype=np.float32)
            seg_starts = np.empty(len(filtered_segs), dtype=np.int32)
            seg_lengths = np.empty(len(filtered_segs), dtype=np.int32)
            
            idx = 0
            for i, coords in enumerate(filtered_segs):
                seg_starts[i] = idx
                seg_lengths[i] = len(coords)
                all_lons[idx:idx+len(coords)] = coords[:, 0]
                all_lats[idx:idx+len(coords)] = coords[:, 1]
                idx += len(coords)
            
            all_px, all_py, all_visible = project_coords(
                all_lons, all_lats, center_lon_rad, sin_clat, cos_clat, cx, cy, radius
            )
            t_project_acc += time.perf_counter() - t_project_start
            
            # Line drawing phase
            t_lines_start = time.perf_counter()
            draw_segments_numba(grid, all_px, all_py, all_visible, seg_starts, seg_lengths, height, width)
            t_lines_acc += time.perf_counter() - t_lines_start
        else:
            for i, coords in enumerate(segs):
                if len(coords) < 2:
                    continue
                
                t_frustum_start = time.perf_counter()
                if bounds is not None and zoom > 1.5:
                    min_lon, max_lon, min_lat, max_lat = bounds[i]
                    if max_lat < min_visible_lat or min_lat > max_visible_lat:
                        t_frustum_acc += time.perf_counter() - t_frustum_start
                        continue
                    if not lon_wraps and (max_lon < min_visible_lon or min_lon > max_visible_lon):
                        t_frustum_acc += time.perf_counter() - t_frustum_start
                        continue
                t_frustum_acc += time.perf_counter() - t_frustum_start
                
                segments_drawn += 1
                
                t_project_start = time.perf_counter()
                lons = np.radians(coords[:, 0])
                lats = np.radians(coords[:, 1])
                
                sin_lats = np.sin(lats)
                cos_lats = np.cos(lats)
                delta_lon = lons - center_lon_rad
                cos_delta = np.cos(delta_lon)
                
                cos_c = sin_clat * sin_lats + cos_clat * cos_lats * cos_delta
                visible = cos_c >= 0
                
                x = cos_lats * np.sin(delta_lon)
                y = cos_clat * sin_lats - sin_clat * cos_lats * cos_delta
                
                px = (cx + x * radius).astype(np.int32)
                py = (cy - y * radius).astype(np.int32)
                t_project_acc += time.perf_counter() - t_project_start
                
                t_lines_start = time.perf_counter()
                for j in range(len(coords) - 1):
                    if not (visible[j] and visible[j + 1]):
                        continue
                    draw_line_bresenham(grid, px[j], py[j], px[j+1], py[j+1], height, width)
                t_lines_acc += time.perf_counter() - t_lines_start
    
    # Choose map resolution based on zoom and threshold
    # Use coarse (110m) at low zoom, detailed (50m) at high zoom
    if segments_coarse is not None and zoom < map_res_threshold:
        draw_segments_to_grid(segments_coarse, segment_bounds_coarse, border_grid)
    else:
        draw_segments_to_grid(segments, segment_bounds, border_grid)
    
    if river_segments and zoom >= rivers_threshold:
        draw_segments_to_grid(river_segments, river_bounds, river_grid)
    
    # Note: Orbital rendering is handled by orbital.py render_orbital_grid_typed()
    # which uses real satellite altitudes from SGP4 propagation
    
    # Update global timings
    t_total = time.perf_counter() - t_total_start
    _render_timings['frustum'] = t_frustum_acc * 1000  # Convert to ms
    _render_timings['project'] = t_project_acc * 1000
    _render_timings['lines'] = t_lines_acc * 1000
    _render_timings['total'] = t_total * 1000
    _render_timings['segments_total'] = segments_total
    _render_timings['segments_drawn'] = segments_drawn
    
    return border_grid.astype(bool), river_grid.astype(bool), orbital_grid.astype(bool), labels


def compute_sun_position(dt):
    """
    Calculate the sun's subsolar point (latitude, longitude) for a given datetime.
    
    Args:
        dt: datetime object (should be in UTC)
    
    Returns:
        tuple: (sun_lat, sun_lon) in degrees
    """
    # Ensure datetime is in UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Calculate day of year
    day_of_year = dt.timetuple().tm_yday
    
    # Solar declination (simplified formula)
    # Varies from -23.45� to +23.45� over the year
    declination = -23.45 * np.cos(np.radians(360 / 365.25 * (day_of_year + 10)))
    
    # Solar longitude (hour angle)
    # At 12:00 UTC, sun is over longitude 0 (Greenwich)
    # Sun moves 15 degrees per hour westward
    hours_since_noon = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 - 12.0
    sun_lon = -15.0 * hours_since_noon
    
    # Normalize to [-180, 180]
    if sun_lon < -180:
        sun_lon += 360
    elif sun_lon > 180:
        sun_lon -= 360
    
    return declination, sun_lon


def compute_shadow_grid(width, height, center_lon, center_lat, zoom, sun_lat, sun_lon):
    """
    Compute shadow grid for the visible portion of the globe (vectorized).
    
    The screen shows an orthographic projection where:
    - Screen X axis = East direction at view center
    - Screen Y axis = North direction at view center  
    - Screen Z axis (into screen) = radial outward at view center
    
    Args:
        width, height: Pixel dimensions
        center_lon, center_lat: Globe center coordinates
        zoom: Current zoom level
        sun_lat, sun_lon: Sun's subsolar point coordinates
    
    Returns:
        tuple: (shadow_grid, in_globe_grid) where:
            - shadow_grid: Boolean grid where True = in shadow (facing away from sun)
            - in_globe_grid: Boolean grid where True = inside globe circle
    """
    base_radius = min(width, height) // 2 - 2
    radius = int(base_radius * zoom)
    cx, cy = width // 2, height // 2
    
    # Convert angles to radians
    sun_lat_rad = np.radians(sun_lat)
    sun_lon_rad = np.radians(sun_lon)
    center_lon_rad = np.radians(center_lon)
    center_lat_rad = np.radians(center_lat)
    
    # Sun direction in ECEF (Earth-Centered Earth-Fixed) coordinates
    # X = towards lon=0, lat=0
    # Y = towards lon=90, lat=0
    # Z = towards north pole
    sun_ecef_x = np.cos(sun_lat_rad) * np.cos(sun_lon_rad)
    sun_ecef_y = np.cos(sun_lat_rad) * np.sin(sun_lon_rad)
    sun_ecef_z = np.sin(sun_lat_rad)
    
    # Transform sun vector to view-local coordinates (ENU at view center)
    # East-North-Up at (center_lon, center_lat)
    # 
    # View local axes in ECEF:
    # East  = (-sin(lon), cos(lon), 0)
    # North = (-sin(lat)*cos(lon), -sin(lat)*sin(lon), cos(lat))
    # Up    = (cos(lat)*cos(lon), cos(lat)*sin(lon), sin(lat))
    
    sin_clat = np.sin(center_lat_rad)
    cos_clat = np.cos(center_lat_rad)
    sin_clon = np.sin(center_lon_rad)
    cos_clon = np.cos(center_lon_rad)
    
    # Project sun onto local East axis (screen X)
    sun_view_x = -sin_clon * sun_ecef_x + cos_clon * sun_ecef_y
    
    # Project sun onto local North axis (screen Y, but Y is flipped on screen)
    sun_view_y = -sin_clat * cos_clon * sun_ecef_x - sin_clat * sin_clon * sun_ecef_y + cos_clat * sun_ecef_z
    
    # Project sun onto local Up axis (screen Z, pointing out of screen)
    sun_view_z = cos_clat * cos_clon * sun_ecef_x + cos_clat * sin_clon * sun_ecef_y + sin_clat * sun_ecef_z
    
    # Create coordinate grids
    py_grid, px_grid = np.ogrid[0:height, 0:width]
    dx = px_grid - cx
    dy = py_grid - cy
    dist_sq = dx * dx + dy * dy
    
    # Mask for pixels within globe circle
    in_globe = dist_sq <= radius * radius
    
    # Compute surface normals in view space (orthographic projection)
    # nx = East component, ny = North component (screen Y is inverted), nz = Up component
    nx = dx / radius
    ny = -dy / radius  # Flip y because screen Y increases downward
    nz_sq = 1.0 - nx * nx - ny * ny
    nz_sq = np.maximum(nz_sq, 0)  # Clamp negative values
    nz = np.sqrt(nz_sq)
    
    # Dot product: positive means facing sun, negative means in shadow
    dot = nx * sun_view_x + ny * sun_view_y + nz * sun_view_z
    
    # Shadow where dot < 0 AND within globe
    shadow_grid = (dot < 0) & in_globe
    
    return shadow_grid, in_globe


def render_gps_position(width, height, center_lon, center_lat, zoom, gps_lon, gps_lat, hostname):
    """
    Render GPS position as a small green rectangle on the globe.
    
    Args:
        width, height: Pixel dimensions of the grid
        center_lon, center_lat: Globe center coordinates
        zoom: Current zoom level
        gps_lon, gps_lat: GPS coordinates
        hostname: Label to display next to the marker
    
    Returns:
        tuple: (gps_grid, gps_label) where gps_grid is the pixel grid and 
               gps_label is (char_x, char_y, hostname) or None if not visible
    """
    gps_grid = np.zeros((height, width), dtype=np.uint8)
    gps_label = None
    
    base_radius = min(width, height) // 2 - 2
    radius = int(base_radius * zoom)
    cx, cy = width // 2, height // 2
    
    center_lon_rad = np.radians(center_lon)
    center_lat_rad = np.radians(center_lat)
    sin_clat = np.sin(center_lat_rad)
    cos_clat = np.cos(center_lat_rad)
    
    gps_lon_rad = np.radians(gps_lon)
    gps_lat_rad = np.radians(gps_lat)
    
    sin_gps_lat = np.sin(gps_lat_rad)
    cos_gps_lat = np.cos(gps_lat_rad)
    delta_lon = gps_lon_rad - center_lon_rad
    cos_delta = np.cos(delta_lon)
    
    cos_c = sin_clat * sin_gps_lat + cos_clat * cos_gps_lat * cos_delta
    
    if cos_c < 0:
        return gps_grid.astype(bool), None
    
    x = cos_gps_lat * np.sin(delta_lon)
    y = cos_clat * sin_gps_lat - sin_clat * cos_gps_lat * cos_delta
    
    px = int(cx + x * radius)
    py = int(cy - y * radius)
    
    rect_half_w = 3
    rect_half_h = 2
    
    for dx in range(-rect_half_w, rect_half_w + 1):
        for dy in range(-rect_half_h, rect_half_h + 1):
            npx, npy = px + dx, py + dy
            if 0 <= npx < width and 0 <= npy < height:
                gps_grid[npy, npx] = 1
    
    char_x = px // 2 + rect_half_w // 2 + 1
    char_y = py // 4
    gps_label = (char_x, char_y, hostname)
    
    return gps_grid.astype(bool), gps_label
