"""
Data loading functions for shapefiles and geographic data.
Optimized for memory efficiency.
"""

import os
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

import numpy as np


def extract_line_segments_with_bounds(gdf):
    """Extract line segments with precomputed bounding boxes for frustum culling.
    
    Returns:
        segments: List of numpy arrays (variable length per segment)
        bounds: numpy array of [min_lon, max_lon, min_lat, max_lat] per segment
        flat_data: dict with pre-flattened arrays for fast projection:
            - all_lons: flattened longitude array
            - all_lats: flattened latitude array  
            - seg_starts: start index of each segment in flat arrays
            - seg_lengths: length of each segment
    """
    segments = []
    bounds = []
    
    def extract_coords(geom):
        t = geom.geom_type
        if t == 'Polygon':
            coords = np.array(geom.exterior.coords, dtype=np.float32)
            segments.append(coords)
            bounds.append((coords[:, 0].min(), coords[:, 0].max(),
                          coords[:, 1].min(), coords[:, 1].max()))
        elif t == 'MultiPolygon':
            for poly in geom.geoms:
                extract_coords(poly)
        elif t == 'LineString':
            coords = np.array(geom.coords, dtype=np.float32)
            segments.append(coords)
            bounds.append((coords[:, 0].min(), coords[:, 0].max(),
                          coords[:, 1].min(), coords[:, 1].max()))
        elif t == 'MultiLineString':
            for line in geom.geoms:
                coords = np.array(line.coords, dtype=np.float32)
                segments.append(coords)
                bounds.append((coords[:, 0].min(), coords[:, 0].max(),
                              coords[:, 1].min(), coords[:, 1].max()))
    
    for _, row in gdf.iterrows():
        if row.geometry is not None and not row.geometry.is_empty:
            extract_coords(row.geometry)
    
    bounds_arr = np.array(bounds, dtype=np.float32) if bounds else None
    
    # Pre-compute flattened arrays for fast projection
    flat_data = None
    if segments:
        # Calculate total points and segment metadata
        seg_lengths = np.array([len(s) for s in segments], dtype=np.int32)
        total_points = seg_lengths.sum()
        seg_starts = np.zeros(len(segments), dtype=np.int32)
        seg_starts[1:] = np.cumsum(seg_lengths[:-1])
        
        # Pre-allocate and fill flattened arrays
        all_lons = np.empty(total_points, dtype=np.float32)
        all_lats = np.empty(total_points, dtype=np.float32)
        
        for i, coords in enumerate(segments):
            start = seg_starts[i]
            length = seg_lengths[i]
            all_lons[start:start+length] = coords[:, 0]
            all_lats[start:start+length] = coords[:, 1]
        
        flat_data = {
            'all_lons': all_lons,
            'all_lats': all_lats,
            'seg_starts': seg_starts,
            'seg_lengths': seg_lengths,
        }
    
    return segments, bounds_arr, flat_data


def load_shapefile(shapefile_path):
    """Load shapefile and extract line segments with bounds and flat data."""
    import geopandas as gpd
    gdf = gpd.read_file(shapefile_path)
    segments, bounds, flat_data = extract_line_segments_with_bounds(gdf)
    del gdf
    return segments, bounds, flat_data


def load_shapefile_coarse(shapefile_path):
    """Load coarse (110m) shapefile for low-zoom rendering.
    
    Falls back gracefully if file doesn't exist.
    """
    if not shapefile_path or not os.path.exists(shapefile_path):
        return None, None, None
    
    import geopandas as gpd
    gdf = gpd.read_file(shapefile_path)
    segments, bounds, flat_data = extract_line_segments_with_bounds(gdf)
    del gdf
    return segments, bounds, flat_data


def load_rivers(rivers_path):
    """Load river shapefile and extract segments with bounds and flat data."""
    if not rivers_path or not os.path.exists(rivers_path):
        return None, None, None
    
    import geopandas as gpd
    rivers_gdf = gpd.read_file(rivers_path)
    river_segments, river_bounds, flat_data = extract_line_segments_with_bounds(rivers_gdf)
    del rivers_gdf
    return river_segments, river_bounds, flat_data


def load_cities(cities_path):
    """Load city coordinates and names from shapefile."""
    if not cities_path or not os.path.exists(cities_path):
        return None, None
    
    import geopandas as gpd
    gdf = gpd.read_file(cities_path)
    coords = []
    names = []
    
    name_col = None
    for col in ['NAME', 'name', 'NAME_EN', 'name_en', 'NAMEASCII']:
        if col in gdf.columns:
            name_col = col
            break
    
    for _, row in gdf.iterrows():
        if row.geometry is not None and row.geometry.geom_type == 'Point':
            coords.append([row.geometry.x, row.geometry.y])
            name = row[name_col] if name_col else ''
            names.append(str(name) if name else '')
    
    del gdf
    
    if coords:
        return np.array(coords, dtype=np.float32), names
    
    return None, None
