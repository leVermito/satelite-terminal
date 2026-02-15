"""Globe display widget for rendering the 3D globe."""

import time
import numpy as np
from datetime import datetime, timezone
from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text
from rich.style import Style

from globe_renderer import (
    render_globe_with_layers, 
    pixels_to_braille_colored,
    pixels_to_braille_colored_typed,
    render_gps_position,
    compute_sun_position,
    compute_shadow_grid,
    COLOR_WHITE,
    COLOR_GREEN,
    SATELLITE_TYPE_COLORS
)
from config_manager import SATELLITE_TYPES
from GPS import get_gps_position
from satellite.orbital import (
    render_orbital_grid,
    render_orbital_grid_typed,
    get_type_index,
    EARTH_RADIUS_KM
)
from satellite.propagator import propagate_batch, get_orbital_period, omm_to_satrec, propagate_to_datetime
from datetime import timedelta


def _style_at(text: Text, index: int):
    if hasattr(text, "style_at"):
        return text.style_at(index)
    if hasattr(text, "get_style_at"):
        return text.get_style_at(index)
    style = text.style
    if isinstance(style, str):
        style = Style.parse(style)
    for span in text.spans:
        if span.start <= index < span.end:
            span_style = span.style
            if isinstance(span_style, str):
                span_style = Style.parse(span_style)
            if style is None:
                style = span_style
            elif span_style is not None:
                try:
                    style = style + span_style
                except Exception:
                    style = span_style
    return style


def _combine_style_with_bg(overlay_style, base_style):
    style = overlay_style
    if isinstance(style, str):
        style = Style.parse(style)
    if isinstance(base_style, Style) and base_style.bgcolor is not None:
        if style is None:
            return Style(bgcolor=base_style.bgcolor)
        try:
            return style + Style(bgcolor=base_style.bgcolor)
        except Exception:
            return Style(
                color=style.color,
                bgcolor=base_style.bgcolor,
                bold=style.bold,
                dim=style.dim,
                italic=style.italic,
                underline=style.underline,
                strike=style.strike,
                reverse=style.reverse,
                link=style.link,
                meta=style.meta,
            )
    return style


def _truncate_segments(segments, max_len):
    if max_len <= 0:
        return []
    remaining = max_len
    truncated = []
    for text, style in segments:
        if remaining <= 0:
            break
        if len(text) > remaining:
            truncated.append((text[:remaining], style))
            break
        truncated.append((text, style))
        remaining -= len(text)
    return truncated


def _overlay_segments(line: Text, start: int, segments):
    line_str = line.plain
    if start < 0 or start >= len(line_str):
        return line
    overlay_text = "".join(text for text, _ in segments)
    if not overlay_text:
        return line
    max_len = len(line_str) - start
    overlay_text = overlay_text[:max_len]
    segments = _truncate_segments(segments, max_len)
    new_line = Text()
    seg_idx = 0
    seg_offset = 0
    seg_text, seg_style = segments[seg_idx] if segments else ("", None)
    for idx, ch in enumerate(line_str):
        if start <= idx < start + len(overlay_text):
            if seg_offset >= len(seg_text) and seg_idx + 1 < len(segments):
                seg_idx += 1
                seg_text, seg_style = segments[seg_idx]
                seg_offset = 0
            overlay_char = overlay_text[idx - start]
            base_style = _style_at(line, idx)
            style = _combine_style_with_bg(seg_style, base_style)
            new_line.append(overlay_char, style=style)
            seg_offset += 1
        else:
            new_line.append(ch, style=_style_at(line, idx))
    return new_line


def _overlay_char_map(line: Text, overlay_map):
    line_str = line.plain
    new_line = Text()
    for idx, ch in enumerate(line_str):
        if idx in overlay_map:
            overlay_char, overlay_style = overlay_map[idx]
            base_style = _style_at(line, idx)
            style = _combine_style_with_bg(overlay_style, base_style)
            new_line.append(overlay_char, style=style)
        else:
            new_line.append(ch, style=_style_at(line, idx))
    return new_line


class GlobeDisplay(Static):
    """Display widget for the globe map."""
    
    center_lon = reactive(0.0)
    center_lat = reactive(0.0)
    zoom = reactive(1.0)
    lod_ratio = reactive(0.5)
    rivers_ratio = reactive(0.5)
    cities_ratio = reactive(0.5)
    
    # Satellite tracking
    tracked_satellite_idx = reactive(None)  # Index into satellite_data
    tracked_satellite_name = reactive("")
    tracked_satellite_type = reactive("")
    _camera_locked = True  # True = camera follows satellite, False = user moved camera
    
    def __init__(self, segments, segment_bounds, river_segments, river_bounds, 
                 city_coords, city_names,
                 segments_coarse=None, segment_bounds_coarse=None, frame_interval=1.0,
                 satellite_data=None):
        super().__init__()
        self.segments = segments
        self.segment_bounds = segment_bounds
        self.river_segments = river_segments
        self.river_bounds = river_bounds
        self.city_coords = city_coords
        self.city_names = city_names
        self.satellite_data = satellite_data
        self.segments_coarse = segments_coarse
        self.segment_bounds_coarse = segment_bounds_coarse
        self._last_size = (0, 0)
        self._needs_redraw = True
        self._animate_orbitals = True
        self._cached_border_grid = None
        self._cached_river_grid = None
        self._cached_labels = None
        self._cache_key = None
        self._last_frame_time = 0
        self._frame_interval = frame_interval
        self._cached_output = None
        self._last_orbital_visible = False
        self._gps_lat = None
        self._gps_lon = None
        self._gps_hostname = None
        self._options_menu = None
        self._satellites_popup = None
        self.satellite_types_list = []
        self.type_indices = None
        self.time_provider = None
        # Propagation cache for frame-level reuse
        self._propagation_cache_time = None
        self._propagation_cache_results = None
        # Orbit path cache
        self._orbit_cache_satellite = None
        self._orbit_cache_points = None
        self._orbit_cache_frame = 0
        # In-sight pass arcs
        self._passes_data = []  # List of pass dicts from pass prediction
    
    def on_mount(self):
        self.render_globe()

    def _current_datetime(self) -> datetime:
        """Get current datetime for orbit calculations.
        
        Uses custom time if set via time_provider, otherwise uses real time.
        """
        if self.time_provider:
            return self.time_provider()
        return datetime.now(timezone.utc)
    
    def _compute_satellite_labels(self, pixel_width, pixel_height, term_width, term_height):
        """Compute satellite name labels for visible satellites with decluttering.
        
        Returns list of (char_x, char_y, name, color, count) tuples for satellites
        that should have labels displayed. Count indicates total satellites at that location.
        
        Implements:
        1. Improved visibility detection (shows satellites behind Earth if above limb)
        2. Spatial decluttering to prevent label overlap
        3. Count display for multiple satellites at same location
        """
        labels = []
        if self.satellite_data is None:
            return labels
        
        # Get display modes from satellites popup
        display_modes = {}
        if self._satellites_popup is not None:
            display_modes = self._satellites_popup.get_display_modes()
        
        # Get type indices
        type_indices = self.type_indices
        satellite_types_list = self.satellite_types_list
        
        # Projection parameters
        base_radius = min(pixel_width, pixel_height) // 2 - 2
        radius = int(base_radius * self.zoom)
        cx, cy = pixel_width // 2, pixel_height // 2
        
        center_lon_rad = np.radians(self.center_lon)
        center_lat_rad = np.radians(self.center_lat)
        sin_clat = np.sin(center_lat_rad)
        cos_clat = np.cos(center_lat_rad)
        
        # Propagate to get current positions
        now = self._current_datetime()
        results = propagate_batch(self.satellite_data, now, type_indices)
        
        # Collect candidate labels with priority
        candidates = []
        
        for i, sat in enumerate(self.satellite_data):
            # Check if this satellite type should show labels (NAME mode)
            if i < len(satellite_types_list):
                sat_type = satellite_types_list[i]
                mode = display_modes.get(sat_type, 'POSITION')
                if mode != 'NAME':
                    continue
            
            # Skip invalid propagations
            if np.isnan(results[i, 0]):
                continue
            
            lat = results[i, 0]
            lon = results[i, 1]
            alt = results[i, 2]
            
            # Improved visibility check (same as render_orbital_grid_typed)
            lat_rad = np.radians(lat)
            lon_rad = np.radians(lon)
            sin_lat = np.sin(lat_rad)
            cos_lat = np.cos(lat_rad)
            delta_lon = lon_rad - center_lon_rad
            cos_delta = np.cos(delta_lon)
            cos_c = sin_clat * sin_lat + cos_clat * cos_lat * cos_delta
            
            # Check if satellite is visible (front hemisphere OR above Earth's limb)
            perp_dist_sq = 1.0 - cos_c * cos_c
            r_ratio = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + alt)
            r_ratio_sq = r_ratio * r_ratio
            
            visible = (cos_c >= 0) or (perp_dist_sq > r_ratio_sq)
            
            if not visible:
                continue
            
            # Project to screen coordinates (with altitude-adjusted radius)
            orbital_scale = (EARTH_RADIUS_KM + alt) / EARTH_RADIUS_KM
            orbital_radius = int(radius * orbital_scale)
            
            x = cos_lat * np.sin(delta_lon)
            y = cos_clat * sin_lat - sin_clat * cos_lat * cos_delta
            
            px = int(cx + x * orbital_radius)
            py = int(cy - y * orbital_radius)
            
            # Convert to character coordinates
            char_x = px // 2 + 1
            char_y = py // 4
            
            # Get satellite name and color
            name = sat.get('OBJECT_NAME', '')
            if not name:
                continue
            
            # Get color based on category
            priority = 99  # Default low priority
            if i < len(satellite_types_list):
                sat_type = satellite_types_list[i]
                type_idx = get_type_index(sat_type)
                priority = type_idx  # Lower index = higher priority
                if 0 <= type_idx < len(SATELLITE_TYPE_COLORS):
                    color = SATELLITE_TYPE_COLORS[type_idx]
                else:
                    color = 'yellow'
            else:
                color = 'yellow'
            
            # Store candidate: (priority, char_x, char_y, name, color)
            candidates.append((priority, char_x, char_y, name, color))
        
        # Declutter: sort by priority (lower = higher priority), then apply spatial filtering
        candidates.sort(key=lambda x: x[0])
        
        # Spatial grid for decluttering
        # Grid cell size: minimum spacing between labels (in characters)
        min_spacing_x = 8  # Horizontal spacing
        min_spacing_y = 2  # Vertical spacing
        
        occupied = {}  # Dict of (grid_x, grid_y) -> (name, color, count)
        
        for priority, char_x, char_y, name, color in candidates:
            # Calculate grid cell
            grid_x = char_x // min_spacing_x
            grid_y = char_y // min_spacing_y
            
            # Check if this cell or adjacent cells are occupied
            blocked = False
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if (grid_x + dx, grid_y + dy) in occupied:
                        blocked = True
                        break
                if blocked:
                    break
            
            if not blocked:
                # Accept this label - initialize count to 1
                occupied[(grid_x, grid_y)] = (char_x, char_y, name, color, 1)
            else:
                # Increment count for the occupied cell
                # Find which cell is occupied
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        key = (grid_x + dx, grid_y + dy)
                        if key in occupied:
                            cx, cy, n, c, count = occupied[key]
                            occupied[key] = (cx, cy, n, c, count + 1)
                            break
        
        # Convert to final label list with counts
        for char_x, char_y, name, color, count in occupied.values():
            labels.append((char_x, char_y, name, color, count))
        
        return labels
    
    def watch_center_lon(self, value):
        self._needs_redraw = True
        self._cached_output = None
        self.render_globe()
    
    def watch_center_lat(self, value):
        self._needs_redraw = True
        self._cached_output = None
        self.render_globe()
    
    def watch_zoom(self, value):
        self._needs_redraw = True
        self._cached_output = None
        self.render_globe()
    
    def get_tracked_satellite_position(self):
        """Get current position of tracked satellite.
        
        Returns:
            tuple: (lat, lon, alt) or None if not tracking or invalid
        """
        if self.tracked_satellite_idx is None or self.satellite_data is None:
            return None
        
        if self.tracked_satellite_idx >= len(self.satellite_data):
            return None
        
        now = self._current_datetime()
        results = propagate_batch(self.satellite_data, now, self.type_indices)
        
        idx = self.tracked_satellite_idx
        if np.isnan(results[idx, 0]):
            return None
        
        return (results[idx, 0], results[idx, 1], results[idx, 2])  # lat, lon, alt
    
    def set_tracked_satellite(self, idx, name, sat_type):
        """Set satellite to track.
        
        Args:
            idx: Index into satellite_data
            name: Satellite name for display
            sat_type: Satellite type string for color
        """
        self.tracked_satellite_idx = idx
        self.tracked_satellite_name = name
        self.tracked_satellite_type = sat_type
        self._camera_locked = True  # Lock camera when setting new tracking
    
    def clear_tracking(self):
        """Clear satellite tracking."""
        self.tracked_satellite_idx = None
        self.tracked_satellite_name = ""
        self.tracked_satellite_type = ""
        self._camera_locked = True
    
    def is_tracking(self):
        """Check if currently tracking a satellite."""
        return self.tracked_satellite_idx is not None
    
    def is_camera_locked(self):
        """Check if camera is locked to tracked satellite."""
        return self._camera_locked and self.tracked_satellite_idx is not None
    
    def unlock_camera(self):
        """Unlock camera from satellite (user moved camera)."""
        self._camera_locked = False
    
    def refocus_camera(self):
        """Re-lock camera to tracked satellite."""
        if self.tracked_satellite_idx is not None:
            self._camera_locked = True
            # Immediately center on satellite
            pos = self.get_tracked_satellite_position()
            if pos is not None:
                self.center_lat = pos[0]
                self.center_lon = pos[1]
    
    def _compute_orbit_points(self, num_points=60):
        """Compute orbit path points for the tracked satellite.
        
        Args:
            num_points: Number of points to compute along the orbit
            
        Returns:
            List of (lat, lon, alt) tuples representing the orbit path,
            or empty list if not tracking or error.
        """
        if self.tracked_satellite_idx is None or self.satellite_data is None:
            return []
        
        if self.tracked_satellite_idx >= len(self.satellite_data):
            return []
        
        omm = self.satellite_data[self.tracked_satellite_idx]
        
        try:
            # Get orbital period
            period_minutes = get_orbital_period(omm)
            sat = omm_to_satrec(omm)
            
            # Compute points along one full orbit
            now = self._current_datetime()
            orbit_points = []
            
            for i in range(num_points):
                # Spread points across one orbital period
                t_offset = (i / num_points) * period_minutes
                dt = now + timedelta(minutes=t_offset)
                
                lat, lon, alt = propagate_to_datetime(sat, dt)
                if not np.isnan(lat):
                    orbit_points.append((lat, lon, alt))
            
            return orbit_points
        except Exception:
            return []

    def _get_in_sight_arcs(self, pixel_width, pixel_height):
        """Compute projected arc points for passes currently in sight.

        Returns list of (arc_points, color) where arc_points is list of (char_y, char_x).
        """
        if not self._passes_data or self.satellite_data is None:
            return []

        now = self._current_datetime()
        norad_map = {}
        for omm in self.satellite_data:
            nid = omm.get("NORAD_CAT_ID")
            if nid is not None:
                norad_map[nid] = omm

        arcs = []
        for p in self._passes_data:
            if p["rise"] > now or p["set"] < now:
                continue
            omm = norad_map.get(p["norad_id"])
            if omm is None:
                continue
            try:
                sat = omm_to_satrec(omm)
            except Exception:
                continue

            # Compute arc from rise to set
            duration_s = (p["set"] - p["rise"]).total_seconds()
            num_pts = max(5, min(30, int(duration_s / 20)))
            points = []
            for i in range(num_pts + 1):
                frac = i / num_pts
                dt = p["rise"] + timedelta(seconds=frac * duration_s)
                try:
                    lat, lon, alt = propagate_to_datetime(sat, dt)
                except Exception:
                    continue
                if np.isnan(lat):
                    continue
                px, py, visible = self._project_point(lat, lon, alt, pixel_width, pixel_height)
                if visible:
                    cx = px // 2
                    cy = py // 4
                    points.append((cy, cx))

            if points:
                sat_type = p.get("type", "")
                color = SATELLITE_TYPES.get(sat_type, {}).get('color', 'yellow')
                arcs.append((points, color, p["name"]))

        return arcs

    def _project_point(self, lat, lon, alt, pixel_width, pixel_height):
        """Project a lat/lon/alt point to screen pixel coordinates.
        
        Returns:
            (px, py, visible) tuple where px, py are pixel coords and visible is bool
        """
        base_radius = min(pixel_width, pixel_height) // 2 - 2
        radius = int(base_radius * self.zoom)
        cx, cy = pixel_width // 2, pixel_height // 2
        
        center_lon_rad = np.radians(self.center_lon)
        center_lat_rad = np.radians(self.center_lat)
        sin_clat = np.sin(center_lat_rad)
        cos_clat = np.cos(center_lat_rad)
        
        lat_rad = np.radians(lat)
        lon_rad = np.radians(lon)
        sin_lat = np.sin(lat_rad)
        cos_lat = np.cos(lat_rad)
        delta_lon = lon_rad - center_lon_rad
        cos_delta = np.cos(delta_lon)
        cos_c = sin_clat * sin_lat + cos_clat * cos_lat * cos_delta
        
        # Visibility check
        perp_dist_sq = 1.0 - cos_c * cos_c
        r_ratio = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + alt)
        r_ratio_sq = r_ratio * r_ratio
        visible = (cos_c >= 0) or (perp_dist_sq > r_ratio_sq)
        
        # Project
        orbital_scale = (EARTH_RADIUS_KM + alt) / EARTH_RADIUS_KM
        orbital_radius = int(radius * orbital_scale)
        
        x = cos_lat * np.sin(delta_lon)
        y = cos_clat * sin_lat - sin_clat * cos_lat * cos_delta
        
        px = int(cx + x * orbital_radius)
        py = int(cy - y * orbital_radius)
        
        return px, py, visible
    
    def animate_frame(self):
        """Update only orbital positions for animation."""
        if not self._animate_orbitals:
            return
        
        now = time.time()
        if now - self._last_frame_time < self._frame_interval:
            return
        self._last_frame_time = now
        
        # Always fetch GPS position
        success, lat, lon, hostname = get_gps_position()
        if success:
            self._gps_lat = lat
            self._gps_lon = lon
            self._gps_hostname = hostname
        
        # Update camera to follow tracked satellite (only if camera is locked)
        if self.tracked_satellite_idx is not None and self._camera_locked:
            pos = self.get_tracked_satellite_position()
            if pos is not None:
                sat_lat, sat_lon, sat_alt = pos
                self.center_lat = sat_lat
                self.center_lon = sat_lon
        
        size = self.size
        if size.width == 0 or size.height == 0:
            return
        
        current_size = (size.width, size.height)
        if current_size != self._last_size:
            self._needs_redraw = True
            self._cached_output = None
            self._last_size = current_size
            self.render_globe()
            self._needs_redraw = False
            return
        
        self.render_globe()
        self._needs_redraw = False
    
    def render_globe(self):
        """Render the globe to the display."""
        size = self.size
        if size.width == 0 or size.height == 0:
            return
        
        pixel_width = size.width * 2
        pixel_height = size.height * 4
        
        cache_key = (pixel_width, pixel_height, self.center_lon, self.center_lat, self.zoom,
                     self.lod_ratio, self.rivers_ratio, self.cities_ratio)
        
        static_changed = self._needs_redraw or self._cache_key != cache_key
        
        if static_changed:
            border_grid, river_grid, _, labels = render_globe_with_layers(
                self.segments, self.segment_bounds,
                self.river_segments, self.river_bounds,
                pixel_width, pixel_height,
                self.center_lon, self.center_lat, self.zoom,
                self.city_coords, self.city_names, size.width, size.height,
                orbital_positions=None,
                segments_coarse=self.segments_coarse,
                segment_bounds_coarse=self.segment_bounds_coarse,
                lod_ratio=self.lod_ratio,
                rivers_ratio=self.rivers_ratio,
                cities_ratio=self.cities_ratio
            )
            self._cached_border_grid = border_grid
            self._cached_river_grid = river_grid
            self._cached_labels = labels
            self._cache_key = cache_key
            self._cached_output = None
        
        # All loaded satellites are already filtered by visibility in satellites_popup
        # No additional filtering needed here
        enabled_types = None
        
        # Compute satellite positions using SGP4 propagation
        use_typed_rendering = False
        orbital_types = None
        
        if self.satellite_data is not None:
            now = self._current_datetime()
            type_indices = self.type_indices
            
            results = propagate_batch(self.satellite_data, now, type_indices)
            # results is [lat, lon, alt, norad_id, type_idx] - we need [lon, lat] for rendering
            valid_mask = ~np.isnan(results[:, 0])
            orbital_positions = np.column_stack([results[:, 1], results[:, 0]])  # [lon, lat]
            orbital_altitudes = results[:, 2]
            orbital_types = results[:, 4].astype(np.int32) if results.shape[1] > 4 else None
            
            # Filter out invalid propagations
            orbital_positions = orbital_positions[valid_mask]
            orbital_altitudes = orbital_altitudes[valid_mask]
            if orbital_types is not None:
                orbital_types = orbital_types[valid_mask]
                use_typed_rendering = True
        else:
            # No satellites
            orbital_positions = np.zeros((0, 2))
            orbital_altitudes = None
        
        # Render orbital grid (typed or simple)
        if use_typed_rendering and orbital_types is not None:
            orbital_grid = render_orbital_grid_typed(
                orbital_positions, orbital_altitudes, orbital_types,
                pixel_width, pixel_height,
                self.center_lon, self.center_lat, self.zoom,
                enabled_types=enabled_types
            )
        else:
            orbital_grid = render_orbital_grid(
                orbital_positions, pixel_width, pixel_height,
                self.center_lon, self.center_lat, self.zoom,
                orbital_altitudes=orbital_altitudes
            )
        
        orbital_has_pixels = bool(np.any(orbital_grid))
        
        # Determine shadow mode early to check if we need to re-render for time changes
        shadow_mode = "OFF"
        if self._options_menu is not None:
            shadow_mode = self._options_menu.shadow_mode
        else:
            shadow_mode = "BORDERS"  # Default when no options menu
        
        # Skip re-render only if: static unchanged, no orbitals, no in-sight passes, AND shadow is off
        # When shadow is enabled, we must re-render because sun position changes with time
        has_in_sight = bool(self._passes_data)
        if not static_changed and not orbital_has_pixels and not self._last_orbital_visible and not has_in_sight and self._cached_output is not None and shadow_mode == "OFF":
            return
        
        self._last_orbital_visible = orbital_has_pixels
        
        # Get GPS label position (no braille dots, only unicode rectangle)
        gps_label = None
        if self._gps_lat is not None and self._gps_lon is not None:
            _, gps_label = render_gps_position(
                pixel_width, pixel_height,
                self.center_lon, self.center_lat, self.zoom,
                self._gps_lon, self._gps_lat, self._gps_hostname
            )
        
        # Compute sun position and shadow grid (if enabled)
        # shadow_mode already determined above for early-exit check
        shadow_grid = None
        in_globe_grid = None
        if shadow_mode != "OFF":
            now = self._current_datetime()
            sun_lat, sun_lon = compute_sun_position(now)
            shadow_grid, in_globe_grid = compute_shadow_grid(
                pixel_width, pixel_height,
                self.center_lon, self.center_lat, self.zoom,
                sun_lat, sun_lon
            )
        
        # Use typed braille rendering when we have type information OR shadow rendering is enabled
        if use_typed_rendering or shadow_mode != "OFF":
            braille_lines = pixels_to_braille_colored_typed(
                self._cached_border_grid, 
                self._cached_river_grid, 
                orbital_grid if use_typed_rendering else None,
                gps_grid=None,
                shadow_grid=shadow_grid,
                shadow_mode=shadow_mode,
                in_globe_grid=in_globe_grid
            )
        else:
            braille_lines = pixels_to_braille_colored(
                self._cached_border_grid, 
                self._cached_river_grid, 
                orbital_grid.astype(bool)
            )
        
        # Render satellite name labels if enabled
        if self.satellite_data is not None:
            # Get satellite names and positions for labeling
            sat_labels = self._compute_satellite_labels(
                pixel_width, pixel_height, size.width, size.height
            )
            for char_x, char_y, name, color, count in sat_labels:
                if 0 <= char_y < len(braille_lines):
                    line = braille_lines[char_y]
                    line_str = line.plain
                    max_len = len(line_str) - char_x
                    if max_len > 0 and char_x >= 0:
                        # Build label with count suffix if count > 1
                        if count > 1:
                            segments = [
                                (name, color),
                                (f" [{count}]", "white bold"),
                            ]
                        else:
                            segments = [(name, color)]
                        segments = _truncate_segments(segments, max_len)
                        braille_lines[char_y] = _overlay_segments(line, char_x, segments)
        
        # Render city labels (grey/dim)
        for char_x, char_y, name in self._cached_labels:
            if 0 <= char_y < len(braille_lines):
                line = braille_lines[char_y]
                line_str = line.plain
                max_len = len(line_str) - char_x
                if max_len > 0 and char_x >= 0:
                    segments = [(name, "dim")]
                    segments = _truncate_segments(segments, max_len)
                    braille_lines[char_y] = _overlay_segments(line, char_x, segments)
        
        # Render GPS label after cities (green bold with unicode rectangle icon)
        if gps_label:
            char_x, char_y, hostname = gps_label
            if 0 <= char_y < len(braille_lines):
                line = braille_lines[char_y]
                line_str = line.plain
                # Unicode rectangle icon + space + hostname
                gps_icon = '\u25a0'  # Black square
                gps_text = f"{gps_icon} {hostname}"
                max_len = len(line_str) - char_x
                if max_len > 0 and char_x >= 0:
                    segments = [(gps_text, COLOR_GREEN + " bold")]
                    segments = _truncate_segments(segments, max_len)
                    braille_lines[char_y] = _overlay_segments(line, char_x, segments)

        # Render saved locations (X marker + name)
        from config_manager import config
        locations = config.locations
        for loc in locations:
            if loc.get("hide", False):
                continue  # Skip hidden locations

            lat = loc["lat"]
            lon = loc["lon"]
            name = loc["name"]
            color = loc.get("color", "#ffffff")

            # Project location to screen
            px, py, visible = self._project_point(lat, lon, 0, pixel_width, pixel_height)
            if visible:
                char_x = px // 2
                char_y = py // 4
                if 0 <= char_y < len(braille_lines):
                    line = braille_lines[char_y]
                    line_str = line.plain
                    # X marker + space + name
                    loc_text = f"X {name}"
                    max_len = len(line_str) - char_x
                    if max_len > 0 and char_x >= 0:
                        segments = [(loc_text, color)]
                        segments = _truncate_segments(segments, max_len)
                        braille_lines[char_y] = _overlay_segments(line, char_x, segments)

        # Render antenna clients with GPS fix
        _amgr = getattr(self, '_antenna_manager', None)
        if _amgr:
            _STATUS_COLORS = {
                "ready": "#00ff00",
                "tracking": "#00ffff",
                "offline": "#ff0000",
                "initializing": "#ffff00",
            }
            for client in _amgr.get_all_clients():
                if client.gps is None:
                    continue
                px, py, visible = self._project_point(
                    client.gps.lat, client.gps.lon, 0, pixel_width, pixel_height)
                if visible:
                    char_x = px // 2
                    char_y = py // 4
                    if 0 <= char_y < len(braille_lines):
                        line = braille_lines[char_y]
                        line_str = line.plain
                        client_color = _STATUS_COLORS.get(client.status, "#aaaaaa")
                        client_text = f"\u25b2 {client.client_id}"
                        max_len = len(line_str) - char_x
                        if max_len > 0 and char_x >= 0:
                            segments = [(client_text, client_color + " bold")]
                            segments = _truncate_segments(segments, max_len)
                            braille_lines[char_y] = _overlay_segments(line, char_x, segments)

        # Render in-sight pass arcs (if enabled in options)
        draw_arcs = True
        if self._options_menu is not None:
            draw_arcs = self._options_menu.draw_pass_arcs
        in_sight_arcs = self._get_in_sight_arcs(pixel_width, pixel_height) if draw_arcs else []
        show_pass_names = False
        if self._options_menu is not None:
            show_pass_names = self._options_menu.show_pass_names
        for arc_points, arc_color, arc_name in in_sight_arcs:
            arc_by_line = {}
            for cy, cx in arc_points:
                if 0 <= cy < len(braille_lines) and 0 <= cx < size.width:
                    if cy not in arc_by_line:
                        arc_by_line[cy] = set()
                    arc_by_line[cy].add(cx)
            for cy, positions in arc_by_line.items():
                line = braille_lines[cy]
                line_len = len(line.plain)
                overlay_map = {}
                for pos in positions:
                    if 0 <= pos < line_len:
                        overlay_map[pos] = ('\u00b7', arc_color)
                if overlay_map:
                    braille_lines[cy] = _overlay_char_map(line, overlay_map)
            # Render pass name at arc midpoint
            if show_pass_names and arc_points:
                mid = arc_points[len(arc_points) // 2]
                mid_y, mid_x = mid
                label = f" {arc_name}"
                if 0 <= mid_y < len(braille_lines):
                    max_len = len(braille_lines[mid_y].plain) - mid_x
                    if max_len > 1:
                        segments = [(label, arc_color + " bold")]
                        segments = _truncate_segments(segments, max_len)
                        braille_lines[mid_y] = _overlay_segments(braille_lines[mid_y], mid_x, segments)

        # Render focused satellite orbit and marker
        if self.tracked_satellite_idx is not None and self.satellite_data is not None:
            # Get satellite color
            sat_color = SATELLITE_TYPES.get(self.tracked_satellite_type, {}).get('color', 'yellow')
            
            # Collect orbit points to render as overlay (after all other rendering)
            # Scale number of points based on zoom level
            base_points = 80
            zoom_factor = max(1.0, self.zoom)
            num_orbit_points = int(base_points * zoom_factor)
            num_orbit_points = min(num_orbit_points, 400)  # Cap at 400 points
            
            orbit_overlay = []  # List of (char_y, char_x) for orbit dots
            orbit_points = self._compute_orbit_points(num_points=num_orbit_points)
            for lat, lon, alt in orbit_points:
                px, py, visible = self._project_point(lat, lon, alt, pixel_width, pixel_height)
                if visible:
                    char_x = px // 2
                    char_y = py // 4
                    if 0 <= char_y < len(braille_lines) and 0 <= char_x < size.width:
                        orbit_overlay.append((char_y, char_x))
            
            # Get focused satellite position for marker
            sat_marker_pos = None
            pos = self.get_tracked_satellite_position()
            if pos is not None:
                sat_lat, sat_lon, sat_alt = pos
                px, py, visible = self._project_point(sat_lat, sat_lon, sat_alt, pixel_width, pixel_height)
                if visible:
                    sat_marker_pos = (py // 4, px // 2)  # (char_y, char_x)
            
            # Rebuild affected lines with orbit and marker overlay
            # Group orbit points by line
            orbit_by_line = {}
            for char_y, char_x in orbit_overlay:
                if char_y not in orbit_by_line:
                    orbit_by_line[char_y] = set()
                orbit_by_line[char_y].add(char_x)
            
            # Process each line that has orbit dots or marker
            lines_to_process = set(orbit_by_line.keys())
            if sat_marker_pos is not None:
                lines_to_process.add(sat_marker_pos[0])
            
            for char_y in lines_to_process:
                if char_y < 0 or char_y >= len(braille_lines):
                    continue
                
                line = braille_lines[char_y]
                line_str = line.plain
                line_len = len(line_str)
                
                # Get orbit positions for this line
                orbit_positions = orbit_by_line.get(char_y, set())
                
                # Check if marker is on this line
                marker_on_line = sat_marker_pos and sat_marker_pos[0] == char_y
                marker_x = sat_marker_pos[1] if marker_on_line else -1
                
                overlay_map = {}
                if orbit_positions:
                    orbit_char = '\u00b7'  # Middle dot
                    for pos in orbit_positions:
                        if 0 <= pos < line_len:
                            overlay_map[pos] = (orbit_char, sat_color)
                
                if marker_on_line and 0 <= marker_x < line_len:
                    sat_marker = '\u25c6'  # Black diamond
                    sat_name = self.tracked_satellite_name
                    label_text = f"{sat_marker} {sat_name}"
                    max_len = line_len - marker_x
                    display_label = label_text[:max_len]
                    for offset, ch in enumerate(display_label):
                        overlay_map[marker_x + offset] = (ch, sat_color + " bold")
                
                braille_lines[char_y] = _overlay_char_map(line, overlay_map)
        
        combined = Text()
        for i, line in enumerate(braille_lines):
            combined.append_text(line)
            if i < len(braille_lines) - 1:
                combined.append("\n")
        
        self._cached_output = combined
        self.update(combined)
