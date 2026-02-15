"""
SGP4 satellite orbit propagation.
Converts OMM orbital elements to lat/lon/alt positions at any time.
"""

import numpy as np
from datetime import datetime, timezone
from typing import Optional
from sgp4.api import Satrec, SatrecArray, jday, WGS72

# Earth parameters
EARTH_RADIUS_KM = 6378.137  # WGS84 equatorial radius
MINUTES_PER_DAY = 1440.0

# Satrec cache: NORAD_CAT_ID -> Satrec
_satrec_cache: dict[int, Satrec] = {}

# Cached SatrecArray for batch propagation
_satrec_array: SatrecArray | None = None
_satrec_array_ids: list[int] | None = None  # NORAD IDs in array order
_satrec_array_type_indices: np.ndarray | None = None


def get_satrec(omm: dict) -> Satrec:
    """Get or create cached Satrec object."""
    norad_id = omm['NORAD_CAT_ID']
    if norad_id not in _satrec_cache:
        _satrec_cache[norad_id] = omm_to_satrec(omm)
    return _satrec_cache[norad_id]


def clear_satrec_cache():
    """Clear cache when satellite data is reloaded."""
    global _satrec_array, _satrec_array_ids, _satrec_array_type_indices
    _satrec_cache.clear()
    _satrec_array = None
    _satrec_array_ids = None
    _satrec_array_type_indices = None


def build_satrec_array(satellites: list[dict], type_indices: np.ndarray = None):
    """Build cached SatrecArray for fast batch propagation.

    Call this once when satellite data is loaded, before repeated propagate_batch calls.
    """
    global _satrec_array, _satrec_array_ids, _satrec_array_type_indices

    satrecs = []
    ids = []
    for omm in satellites:
        try:
            sat = get_satrec(omm)
            satrecs.append(sat)
            ids.append(omm.get('NORAD_CAT_ID', 0))
        except Exception:
            # Skip invalid satellites
            pass

    if satrecs:
        _satrec_array = SatrecArray(satrecs)
        _satrec_array_ids = ids
        _satrec_array_type_indices = type_indices if type_indices is not None else np.zeros(len(ids))
    else:
        _satrec_array = None
        _satrec_array_ids = None
        _satrec_array_type_indices = None


def omm_to_satrec(omm: dict) -> Satrec:
    """Convert OMM record to SGP4 Satrec object.
    
    Args:
        omm: OMM record dict from CelesTrak JSON
    
    Returns:
        Initialized Satrec object for propagation
    """
    # Parse epoch
    epoch_str = omm['EPOCH']
    epoch_dt = datetime.fromisoformat(epoch_str.replace('Z', '+00:00'))
    
    # Convert epoch to Julian date
    jd, fr = jday(
        epoch_dt.year, epoch_dt.month, epoch_dt.day,
        epoch_dt.hour, epoch_dt.minute, 
        epoch_dt.second + epoch_dt.microsecond / 1e6
    )
    
    # Create Satrec from orbital elements
    # SGP4 expects angles in radians, but we have degrees
    deg2rad = np.pi / 180.0
    
    sat = Satrec()
    sat.sgp4init(
        WGS72,                              # gravity model
        'i',                                # improved mode
        omm['NORAD_CAT_ID'],               # satellite number
        jd + fr - 2433281.5,               # epoch in days since 1949 Dec 31
        omm['BSTAR'],                       # drag coefficient
        omm['MEAN_MOTION_DOT'] / (MINUTES_PER_DAY * 2),  # ndot (revs/day^2 -> rad/min^2)
        omm['MEAN_MOTION_DDOT'] / (MINUTES_PER_DAY * 6), # nddot
        omm['ECCENTRICITY'],               # eccentricity
        omm['ARG_OF_PERICENTER'] * deg2rad, # argument of perigee (rad)
        omm['INCLINATION'] * deg2rad,       # inclination (rad)
        omm['MEAN_ANOMALY'] * deg2rad,      # mean anomaly (rad)
        omm['MEAN_MOTION'] / MINUTES_PER_DAY * 2 * np.pi,  # mean motion (rad/min)
        omm['RA_OF_ASC_NODE'] * deg2rad,    # RAAN (rad)
    )
    
    return sat


def propagate_to_datetime(sat: Satrec, dt: datetime) -> tuple[float, float, float]:
    """Propagate satellite to given datetime.
    
    Args:
        sat: Satrec object
        dt: Target datetime (UTC)
    
    Returns:
        Tuple of (latitude_deg, longitude_deg, altitude_km)
        Returns (nan, nan, nan) on propagation error.
    """
    # Convert datetime to Julian date
    jd, fr = jday(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute,
        dt.second + dt.microsecond / 1e6
    )
    
    # Propagate
    error, position, velocity = sat.sgp4(jd, fr)
    
    if error != 0:
        return (np.nan, np.nan, np.nan)
    
    # Position is in TEME (True Equator Mean Equinox) frame, km
    x, y, z = position
    
    # Convert TEME to geodetic lat/lon/alt
    # First need to rotate from TEME to ECEF (account for Earth rotation)
    gmst = _greenwich_sidereal_time(jd, fr)
    
    # Rotate position from TEME to ECEF
    cos_gmst = np.cos(gmst)
    sin_gmst = np.sin(gmst)
    x_ecef = x * cos_gmst + y * sin_gmst
    y_ecef = -x * sin_gmst + y * cos_gmst
    z_ecef = z
    
    # Convert ECEF to geodetic
    lat, lon, alt = _ecef_to_geodetic(x_ecef, y_ecef, z_ecef)
    
    return (lat, lon, alt)


def propagate_batch(satellites: list[dict], dt: datetime, type_indices: np.ndarray = None) -> np.ndarray:
    """Propagate multiple satellites to given datetime.

    Args:
        satellites: List of OMM records
        dt: Target datetime (UTC)
        type_indices: Optional array of type indices for each satellite

    Returns:
        Numpy array of shape (n, 5) with columns [lat, lon, alt, norad_id, type_idx]
        Invalid propagations have nan values for lat/lon/alt.
        type_idx is preserved from input or set to 0 if not provided.
    """
    global _satrec_array, _satrec_array_ids, _satrec_array_type_indices

    # Use cached SatrecArray if available and matches input
    if (_satrec_array is not None and
        _satrec_array_ids is not None and
        len(_satrec_array_ids) == len(satellites) and
        _satrec_array_ids[0] == satellites[0].get('NORAD_CAT_ID', 0) and
        _satrec_array_ids[-1] == satellites[-1].get('NORAD_CAT_ID', 0)):
        return _propagate_batch_vectorized(dt)

    # Fallback to loop-based propagation (or first call before array is built)
    return _propagate_batch_loop(satellites, dt, type_indices)


def _propagate_batch_vectorized(dt: datetime) -> np.ndarray:
    """Vectorized batch propagation using cached SatrecArray."""
    n = len(_satrec_array_ids)
    result = np.zeros((n, 5))

    # Julian date as arrays for vectorized sgp4
    jd, fr = jday(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute,
        dt.second + dt.microsecond / 1e6
    )
    jd_arr = np.array([jd])
    fr_arr = np.array([fr])

    # Vectorized SGP4 - single call for all satellites
    errors, positions, velocities = _satrec_array.sgp4(jd_arr, fr_arr)

    # positions shape: (n_sats, 1, 3) -> squeeze to (n_sats, 3)
    positions = positions[:, 0, :]
    errors = errors[:, 0]

    # TEME to ECEF rotation
    gmst = _greenwich_sidereal_time(jd, fr)
    cos_gmst = np.cos(gmst)
    sin_gmst = np.sin(gmst)

    x = positions[:, 0]
    y = positions[:, 1]
    z = positions[:, 2]

    x_ecef = x * cos_gmst + y * sin_gmst
    y_ecef = -x * sin_gmst + y * cos_gmst
    z_ecef = z

    # Vectorized geodetic conversion
    lats, lons, alts = _ecef_to_geodetic(x_ecef, y_ecef, z_ecef)

    # Build result array
    result[:, 0] = lats
    result[:, 1] = lons
    result[:, 2] = alts
    result[:, 3] = _satrec_array_ids
    result[:, 4] = _satrec_array_type_indices[:n] if _satrec_array_type_indices is not None else 0

    # Mark errors as nan
    error_mask = errors != 0
    result[error_mask, 0:3] = np.nan

    return result


def _propagate_batch_loop(satellites: list[dict], dt: datetime, type_indices: np.ndarray = None) -> np.ndarray:
    """Loop-based batch propagation fallback."""
    n = len(satellites)
    result = np.zeros((n, 5))

    jd, fr = jday(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute,
        dt.second + dt.microsecond / 1e6
    )
    gmst = _greenwich_sidereal_time(jd, fr)
    cos_gmst = np.cos(gmst)
    sin_gmst = np.sin(gmst)

    valid_indices = []
    x_ecef_list = []
    y_ecef_list = []
    z_ecef_list = []

    for i, omm in enumerate(satellites):
        type_idx = type_indices[i] if type_indices is not None else 0
        norad_id = omm.get('NORAD_CAT_ID', 0)
        try:
            sat = get_satrec(omm)
            error, position, velocity = sat.sgp4(jd, fr)

            if error != 0:
                result[i] = [np.nan, np.nan, np.nan, norad_id, type_idx]
                continue

            x, y, z = position

            x_ecef = x * cos_gmst + y * sin_gmst
            y_ecef = -x * sin_gmst + y * cos_gmst
            z_ecef = z

            valid_indices.append(i)
            x_ecef_list.append(x_ecef)
            y_ecef_list.append(y_ecef)
            z_ecef_list.append(z_ecef)

            result[i, 3] = norad_id
            result[i, 4] = type_idx

        except Exception:
            result[i] = [np.nan, np.nan, np.nan, norad_id, type_idx]

    if valid_indices:
        x_arr = np.array(x_ecef_list)
        y_arr = np.array(y_ecef_list)
        z_arr = np.array(z_ecef_list)

        lats, lons, alts = _ecef_to_geodetic(x_arr, y_arr, z_arr)

        for j, i in enumerate(valid_indices):
            result[i, 0] = lats[j] if not np.isscalar(lats) else lats
            result[i, 1] = lons[j] if not np.isscalar(lons) else lons
            result[i, 2] = alts[j] if not np.isscalar(alts) else alts

    return result


def _greenwich_sidereal_time(jd: float, fr: float) -> float:
    """Calculate Greenwich Mean Sidereal Time.
    
    Args:
        jd: Julian date (integer part)
        fr: Julian date (fractional part)
    
    Returns:
        GMST in radians
    """
    # Julian centuries from J2000.0
    t_ut1 = (jd - 2451545.0 + fr) / 36525.0
    
    # GMST in seconds
    gmst_sec = (67310.54841 + 
                (876600.0 * 3600.0 + 8640184.812866) * t_ut1 +
                0.093104 * t_ut1**2 -
                6.2e-6 * t_ut1**3)
    
    # Convert to radians (86400 seconds = 2*pi radians)
    gmst = (gmst_sec % 86400.0) / 86400.0 * 2.0 * np.pi
    
    return gmst


def _ecef_to_geodetic(x, y, z):
    """Convert ECEF coordinates to geodetic lat/lon/alt.

    Uses iterative method for accuracy. Accepts scalars or arrays.

    Args:
        x, y, z: ECEF coordinates in km (scalar or array)

    Returns:
        Tuple of (latitude_deg, longitude_deg, altitude_km)
    """
    # WGS84 parameters
    a = 6378.137  # equatorial radius km
    f = 1.0 / 298.257223563  # flattening
    b = a * (1.0 - f)  # polar radius
    e2 = 1.0 - (b/a)**2  # eccentricity squared

    # Longitude is straightforward
    lon = np.arctan2(y, x)

    # Iterative latitude calculation (Bowring's method)
    p = np.sqrt(x**2 + y**2)
    lat = np.arctan2(z, p * (1.0 - e2))  # initial estimate

    for _ in range(5):  # converges quickly
        sin_lat = np.sin(lat)
        N = a / np.sqrt(1.0 - e2 * sin_lat**2)
        lat = np.arctan2(z + e2 * N * sin_lat, p)

    # Altitude
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    N = a / np.sqrt(1.0 - e2 * sin_lat**2)

    # Handle scalar vs array for altitude calculation
    if np.isscalar(cos_lat):
        if abs(cos_lat) > 1e-10:
            alt = p / cos_lat - N
        else:
            alt = abs(z) - b
    else:
        alt = np.where(np.abs(cos_lat) > 1e-10, p / cos_lat - N, np.abs(z) - b)

    # Convert to degrees
    lat_deg = np.degrees(lat)
    lon_deg = np.degrees(lon)

    return (lat_deg, lon_deg, alt)


def get_orbital_period(omm: dict) -> float:
    """Get orbital period in minutes.
    
    Args:
        omm: OMM record
    
    Returns:
        Orbital period in minutes
    """
    mean_motion = omm['MEAN_MOTION']  # revolutions per day
    return MINUTES_PER_DAY / mean_motion


def get_apogee_perigee(omm: dict) -> tuple[float, float]:
    """Get apogee and perigee altitudes.
    
    Args:
        omm: OMM record
    
    Returns:
        Tuple of (apogee_km, perigee_km) above Earth surface
    """
    # Semi-major axis from mean motion
    # n = sqrt(mu / a^3), where mu = 398600.4418 km^3/s^2
    mu = 398600.4418
    n = omm['MEAN_MOTION'] / MINUTES_PER_DAY * 2 * np.pi / 60  # rad/s
    a = (mu / n**2) ** (1/3)  # semi-major axis km
    
    e = omm['ECCENTRICITY']
    
    apogee = a * (1 + e) - EARTH_RADIUS_KM
    perigee = a * (1 - e) - EARTH_RADIUS_KM
    
    return (apogee, perigee)
