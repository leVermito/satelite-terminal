"""
Pass prediction for satellites over a ground observer.
Computes rise/set times, max elevation, and duration for satellite passes.
"""

import numpy as np
from datetime import datetime, timezone, timedelta
from sgp4.api import Satrec, jday, WGS72

from satellite.propagator import omm_to_satrec, get_satrec, _greenwich_sidereal_time

# WGS84 constants
WGS84_A = 6378.137  # equatorial radius km
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)
WGS84_E2 = 1.0 - (WGS84_B / WGS84_A) ** 2

MIN_ELEVATION_DEG = 5.0


def observer_ecef(lat_deg, lon_deg, alt_km=0.0):
    """Geodetic to ECEF for ground station (WGS84)."""
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    N = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat ** 2)
    x = (N + alt_km) * cos_lat * np.cos(lon)
    y = (N + alt_km) * cos_lat * np.sin(lon)
    z = (N * (1.0 - WGS84_E2) + alt_km) * sin_lat
    return np.array([x, y, z])


def satellite_ecef_at(satrec, dt):
    """SGP4 propagate + TEME-to-ECEF rotation. Returns ECEF xyz in km or None on error."""
    jd, fr = jday(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute,
        dt.second + dt.microsecond / 1e6,
    )
    error, position, _ = satrec.sgp4(jd, fr)
    if error != 0:
        return None
    x, y, z = position
    gmst = _greenwich_sidereal_time(jd, fr)
    cos_g = np.cos(gmst)
    sin_g = np.sin(gmst)
    x_ecef = x * cos_g + y * sin_g
    y_ecef = -x * sin_g + y * cos_g
    z_ecef = z
    return np.array([x_ecef, y_ecef, z_ecef])


def compute_elevation(obs_lat_deg, obs_lon_deg, obs_alt_km, sat_ecef):
    """Elevation angle via SEZ (South-East-Zenith) topocentric frame. Returns degrees."""
    obs = observer_ecef(obs_lat_deg, obs_lon_deg, obs_alt_km)
    rng = sat_ecef - obs

    lat = np.radians(obs_lat_deg)
    lon = np.radians(obs_lon_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)

    # Rotate range vector into SEZ
    s = sin_lat * cos_lon * rng[0] + sin_lat * sin_lon * rng[1] - cos_lat * rng[2]
    e = -sin_lon * rng[0] + cos_lon * rng[1]
    z = cos_lat * cos_lon * rng[0] + cos_lat * sin_lon * rng[1] + sin_lat * rng[2]

    rng_mag = np.sqrt(s * s + e * e + z * z)
    if rng_mag < 1e-6:
        return 90.0
    el = np.degrees(np.arcsin(z / rng_mag))
    return el


def make_observer_cache(obs_lat_deg, obs_lon_deg, obs_alt_km):
    """Pre-compute observer position and trig values for repeated elevation calculations."""
    obs_ecef = observer_ecef(obs_lat_deg, obs_lon_deg, obs_alt_km)
    lat = np.radians(obs_lat_deg)
    lon = np.radians(obs_lon_deg)
    return {
        'ecef': obs_ecef,
        'sin_lat': np.sin(lat),
        'cos_lat': np.cos(lat),
        'sin_lon': np.sin(lon),
        'cos_lon': np.cos(lon),
    }


def _elevation_cached(sat_ecef, obs_cache):
    """Elevation using pre-computed observer cache."""
    rng = sat_ecef - obs_cache['ecef']
    sin_lat = obs_cache['sin_lat']
    cos_lat = obs_cache['cos_lat']
    sin_lon = obs_cache['sin_lon']
    cos_lon = obs_cache['cos_lon']

    s = sin_lat * cos_lon * rng[0] + sin_lat * sin_lon * rng[1] - cos_lat * rng[2]
    e = -sin_lon * rng[0] + cos_lon * rng[1]
    z = cos_lat * cos_lon * rng[0] + cos_lat * sin_lon * rng[1] + sin_lat * rng[2]

    rng_mag = np.sqrt(s * s + e * e + z * z)
    if rng_mag < 1e-6:
        return 90.0
    return np.degrees(np.arcsin(z / rng_mag))


def _elevation_at_cached(satrec, dt, obs_cache):
    """Helper: elevation angle at a specific time using observer cache."""
    sat_ecef = satellite_ecef_at(satrec, dt)
    if sat_ecef is None:
        return None
    return _elevation_cached(sat_ecef, obs_cache)


def compute_az_el(obs_lat_deg, obs_lon_deg, obs_alt_km, sat_ecef):
    """Azimuth and elevation from observer to satellite via SEZ frame. Returns (az_deg, el_deg)."""
    obs = observer_ecef(obs_lat_deg, obs_lon_deg, obs_alt_km)
    rng = sat_ecef - obs

    lat = np.radians(obs_lat_deg)
    lon = np.radians(obs_lon_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)

    # SEZ (South-East-Zenith)
    s = sin_lat * cos_lon * rng[0] + sin_lat * sin_lon * rng[1] - cos_lat * rng[2]
    e = -sin_lon * rng[0] + cos_lon * rng[1]
    z = cos_lat * cos_lon * rng[0] + cos_lat * sin_lon * rng[1] + sin_lat * rng[2]

    rng_mag = np.sqrt(s * s + e * e + z * z)
    if rng_mag < 1e-6:
        return 0.0, 90.0

    el = np.degrees(np.arcsin(z / rng_mag))
    az = np.degrees(np.arctan2(e, -s)) % 360.0
    return az, el


def _bisect_crossing(satrec, t_below, t_above, obs_cache, threshold, iterations=20):
    """Binary search for time when elevation crosses threshold. Returns datetime."""
    lo = t_below.timestamp()
    hi = t_above.timestamp()
    for _ in range(iterations):
        mid_ts = (lo + hi) / 2.0
        mid_dt = datetime.fromtimestamp(mid_ts, tz=timezone.utc)
        el = _elevation_at_cached(satrec, mid_dt, obs_cache)
        if el is None:
            break
        if el >= threshold:
            hi = mid_ts
        else:
            lo = mid_ts
    return datetime.fromtimestamp((lo + hi) / 2.0, tz=timezone.utc)


def _bisect_crossing_set(satrec, t_above, t_below, obs_cache, threshold, iterations=20):
    """Binary search for set time (elevation going below threshold). Returns datetime."""
    lo = t_above.timestamp()
    hi = t_below.timestamp()
    for _ in range(iterations):
        mid_ts = (lo + hi) / 2.0
        mid_dt = datetime.fromtimestamp(mid_ts, tz=timezone.utc)
        el = _elevation_at_cached(satrec, mid_dt, obs_cache)
        if el is None:
            break
        if el >= threshold:
            lo = mid_ts
        else:
            hi = mid_ts
    return datetime.fromtimestamp((lo + hi) / 2.0, tz=timezone.utc)


def find_passes(omm, obs_lat, obs_lon, obs_alt=0.0, start_dt=None, hours=24):
    """Find satellite passes over observer.

    Coarse 60s scan, binary search refinement for rise/set, adaptive scan for max elevation.

    Returns list of dicts: {rise, set, max_el, duration_s}
    """
    if start_dt is None:
        start_dt = datetime.now(timezone.utc)

    try:
        satrec = get_satrec(omm)
    except Exception:
        return []

    obs_cache = make_observer_cache(obs_lat, obs_lon, obs_alt)
    threshold = MIN_ELEVATION_DEG
    step = 60  # seconds
    end_dt = start_dt + timedelta(hours=hours)
    passes = []

    t = start_dt
    in_pass = False
    pass_start = None
    prev_el = None

    while t <= end_dt:
        el = _elevation_at_cached(satrec, t, obs_cache)
        if el is None:
            t += timedelta(seconds=step)
            prev_el = None
            continue

        if not in_pass:
            if el >= threshold:
                # Rising detected
                if prev_el is not None and prev_el < threshold:
                    rise = _bisect_crossing(satrec, t - timedelta(seconds=step), t, obs_cache, threshold)
                else:
                    rise = t
                in_pass = True
                pass_start = rise
        else:
            if el < threshold:
                # Setting detected
                set_time = _bisect_crossing_set(satrec, t - timedelta(seconds=step), t, obs_cache, threshold)
                # Find max elevation within this pass using adaptive scan
                max_el = _find_max_elevation(satrec, pass_start, set_time, obs_cache)
                duration = (set_time - pass_start).total_seconds()
                if duration > 0:
                    passes.append({
                        "rise": pass_start,
                        "set": set_time,
                        "max_el": max_el,
                        "duration_s": duration,
                    })
                in_pass = False
                pass_start = None

        prev_el = el
        t += timedelta(seconds=step)

    # If still in pass at end of window, close it
    if in_pass and pass_start is not None:
        max_el = _find_max_elevation(satrec, pass_start, end_dt, obs_cache)
        duration = (end_dt - pass_start).total_seconds()
        if duration > 0:
            passes.append({
                "rise": pass_start,
                "set": end_dt,
                "max_el": max_el,
                "duration_s": duration,
            })

    return passes


def _find_max_elevation(satrec, t_start, t_end, obs_cache):
    """Scan for maximum elevation using adaptive coarse-then-refine approach."""
    duration = (t_end - t_start).total_seconds()

    # For short passes, just do fine scan
    if duration < 120:
        max_el = 0.0
        t = t_start
        while t <= t_end:
            el = _elevation_at_cached(satrec, t, obs_cache)
            if el is not None and el > max_el:
                max_el = el
            t += timedelta(seconds=5)
        return max_el

    # Coarse scan at 30s intervals to find approximate peak
    max_el = 0.0
    peak_time = t_start
    t = t_start
    while t <= t_end:
        el = _elevation_at_cached(satrec, t, obs_cache)
        if el is not None and el > max_el:
            max_el = el
            peak_time = t
        t += timedelta(seconds=30)

    # Refine around peak with 5s scan (+/- 60s)
    refine_start = max(t_start, peak_time - timedelta(seconds=60))
    refine_end = min(t_end, peak_time + timedelta(seconds=60))
    t = refine_start
    while t <= refine_end:
        el = _elevation_at_cached(satrec, t, obs_cache)
        if el is not None and el > max_el:
            max_el = el
        t += timedelta(seconds=5)

    return max_el


def _scan_forward_set(satrec, start_dt, obs_cache, threshold, max_hours=6):
    """Scan forward from a known-visible time to find when satellite sets."""
    step = 30
    prev_t = start_dt
    t = start_dt + timedelta(seconds=step)
    end = start_dt + timedelta(hours=max_hours)
    while t <= end:
        el = _elevation_at_cached(satrec, t, obs_cache)
        if el is None or el < threshold:
            return _bisect_crossing_set(satrec, prev_t, t, obs_cache, threshold)
        prev_t = t
        t += timedelta(seconds=step)
    return end


def _scan_backward_rise(satrec, start_dt, obs_cache, threshold, max_hours=2):
    """Scan backward from a known-visible time to find when satellite rose."""
    step = 30
    prev_t = start_dt
    t = start_dt - timedelta(seconds=step)
    begin = start_dt - timedelta(hours=max_hours)
    while t >= begin:
        el = _elevation_at_cached(satrec, t, obs_cache)
        if el is None or el < threshold:
            return _bisect_crossing(satrec, t, prev_t, obs_cache, threshold)
        prev_t = t
        t -= timedelta(seconds=step)
    return begin


def find_visible_now(satellite_data, obs_lat, obs_lon, obs_alt=0.0, favorites=None):
    """Find all satellites currently visible above MIN_ELEVATION_DEG.

    Returns list sorted: favorites first (by elevation desc), then others (by elevation desc).
    Each dict: {name, norad_id, el, rise, set, max_el, duration_s, is_favorite, omm}
    """
    now = datetime.now(timezone.utc)
    threshold = MIN_ELEVATION_DEG
    fav_ids = {f["norad_id"] for f in (favorites or [])}

    # Pre-compute observer data once for all satellites
    obs_cache = make_observer_cache(obs_lat, obs_lon, obs_alt)

    visible = []
    for omm in satellite_data:
        try:
            satrec = get_satrec(omm)
        except Exception:
            continue
        sat_ecef = satellite_ecef_at(satrec, now)
        if sat_ecef is None:
            continue
        el = _elevation_cached(sat_ecef, obs_cache)
        if el < threshold:
            continue

        nid = omm.get("NORAD_CAT_ID")
        name = omm.get("OBJECT_NAME", f"NORAD {nid}")

        set_time = _scan_forward_set(satrec, now, obs_cache, threshold)
        rise_time = _scan_backward_rise(satrec, now, obs_cache, threshold)
        max_el = max(el, _find_max_elevation(satrec, now, set_time, obs_cache))

        visible.append({
            "name": name,
            "norad_id": nid,
            "el": el,
            "rise": rise_time,
            "set": set_time,
            "max_el": max_el,
            "duration_s": (set_time - rise_time).total_seconds(),
            "is_favorite": nid in fav_ids,
            "omm": omm,
        })

    favs = sorted([s for s in visible if s["is_favorite"]], key=lambda x: -x["el"])
    others = sorted([s for s in visible if not s["is_favorite"]], key=lambda x: -x["el"])
    return favs + others


def predict_all_favorites(favorites, satellite_data, obs_lat, obs_lon, obs_alt=0.0, hours=24,
                          max_per_sat=None, max_total=None):
    """Batch prediction for all favorites, sorted by rise time.

    Args:
        favorites: list of favorite dicts with 'norad_id' and 'name'
        satellite_data: list of OMM dicts (loaded satellites)
        obs_lat, obs_lon: observer geodetic coordinates
        obs_alt: observer altitude in km (default 0)
        hours: prediction window
        max_per_sat: max passes per satellite (None = unlimited)
        max_total: max total passes returned (None = unlimited)

    Returns:
        list of dicts: {name, norad_id, rise, set, max_el, duration_s}
    """
    if not favorites or not satellite_data:
        return []

    # Build NORAD lookup and pre-cache satrecs
    norad_map = {}
    for omm in satellite_data:
        nid = omm.get("NORAD_CAT_ID")
        if nid is not None:
            norad_map[nid] = omm

    start_dt = datetime.now(timezone.utc)
    results = []

    for fav in favorites:
        nid = fav["norad_id"]
        omm = norad_map.get(nid)
        if omm is None:
            continue
        # find_passes already uses get_satrec and observer caching
        passes = find_passes(omm, obs_lat, obs_lon, obs_alt, start_dt, hours)
        if max_per_sat is not None:
            passes = passes[:max_per_sat]
        for p in passes:
            results.append({
                "name": fav["name"],
                "norad_id": nid,
                "type": fav.get("type", ""),
                "rise": p["rise"],
                "set": p["set"],
                "max_el": p["max_el"],
                "duration_s": p["duration_s"],
            })

    results.sort(key=lambda r: r["rise"])
    if max_total is not None:
        results = results[:max_total]
    return results
