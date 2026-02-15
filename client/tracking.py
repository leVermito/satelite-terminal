"""Client-side SGP4 tracking engine.

Extracted from app/satellite/propagator.py and app/satellite/pass_prediction.py.
Provides real-time az/el computation from OMM data and observer GPS position.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np
from sgp4.api import Satrec, jday, WGS72

from states import State

log = logging.getLogger("sdr.tracking")

EARTH_RADIUS_KM = 6378.137
MINUTES_PER_DAY = 1440.0

# WGS84
WGS84_A = 6378.137
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)
WGS84_E2 = 1.0 - (WGS84_B / WGS84_A) ** 2


def omm_to_satrec(omm: dict) -> Satrec:
    """Convert OMM record to SGP4 Satrec object."""
    epoch_str = omm["EPOCH"]
    epoch_dt = datetime.fromisoformat(epoch_str.replace("Z", "+00:00"))

    jd, fr = jday(
        epoch_dt.year, epoch_dt.month, epoch_dt.day,
        epoch_dt.hour, epoch_dt.minute,
        epoch_dt.second + epoch_dt.microsecond / 1e6,
    )

    deg2rad = np.pi / 180.0

    sat = Satrec()
    sat.sgp4init(
        WGS72, "i",
        omm["NORAD_CAT_ID"],
        jd + fr - 2433281.5,
        omm["BSTAR"],
        omm.get("MEAN_MOTION_DOT", 0.0) / (MINUTES_PER_DAY * 2),
        omm.get("MEAN_MOTION_DDOT", 0.0) / (MINUTES_PER_DAY * 6),
        omm["ECCENTRICITY"],
        omm["ARG_OF_PERICENTER"] * deg2rad,
        omm["INCLINATION"] * deg2rad,
        omm["MEAN_ANOMALY"] * deg2rad,
        omm["MEAN_MOTION"] / MINUTES_PER_DAY * 2 * np.pi,
        omm["RA_OF_ASC_NODE"] * deg2rad,
    )
    return sat


def _greenwich_sidereal_time(jd: float, fr: float) -> float:
    """Calculate Greenwich Mean Sidereal Time in radians."""
    t_ut1 = (jd - 2451545.0 + fr) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t_ut1
        + 0.093104 * t_ut1 ** 2
        - 6.2e-6 * t_ut1 ** 3
    )
    return (gmst_sec % 86400.0) / 86400.0 * 2.0 * np.pi


def observer_ecef(lat_deg: float, lon_deg: float, alt_km: float = 0.0) -> np.ndarray:
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


def satellite_ecef_at(satrec: Satrec, dt: datetime) -> np.ndarray | None:
    """SGP4 propagate + TEME-to-ECEF rotation. Returns ECEF xyz in km or None."""
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
    return np.array([
        x * cos_g + y * sin_g,
        -x * sin_g + y * cos_g,
        z,
    ])


def compute_az_el(obs_lat_deg: float, obs_lon_deg: float, obs_alt_km: float,
                  sat_ecef: np.ndarray) -> tuple[float, float]:
    """Azimuth and elevation from observer to satellite via SEZ frame. Returns (az_deg, el_deg)."""
    obs = observer_ecef(obs_lat_deg, obs_lon_deg, obs_alt_km)
    rng = sat_ecef - obs

    lat = np.radians(obs_lat_deg)
    lon = np.radians(obs_lon_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)

    s = sin_lat * cos_lon * rng[0] + sin_lat * sin_lon * rng[1] - cos_lat * rng[2]
    e = -sin_lon * rng[0] + cos_lon * rng[1]
    z = cos_lat * cos_lon * rng[0] + cos_lat * sin_lon * rng[1] + sin_lat * rng[2]

    rng_mag = np.sqrt(s * s + e * e + z * z)
    if rng_mag < 1e-6:
        return 0.0, 90.0

    el = np.degrees(np.arcsin(z / rng_mag))
    az = np.degrees(np.arctan2(e, -s)) % 360.0
    return az, el


class TrackingLoop:
    """Runs SGP4 tracking in a background thread.

    Continuously computes az/el from OMM data and observer position until set_time or stop().
    """

    def __init__(self, state_mgr=None):
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self.current_az: float = 0.0
        self.current_el: float = 0.0
        self.norad_id: int | None = None
        self.sat_name: str = ""
        self.active: bool = False
        self._state_mgr = state_mgr
        self._on_telemetry_callbacks: list = []

    def on_telemetry(self, callback):
        """Register callback(az, el) fired after each tracking computation."""
        self._on_telemetry_callbacks.append(callback)

    def start(self, omm: dict, obs_lat: float, obs_lon: float, obs_alt_km: float,
              set_time_str: str, update_interval: float = 0.25):
        """Start tracking a satellite."""
        self.stop()

        satrec = omm_to_satrec(omm)
        set_time = datetime.fromisoformat(set_time_str.replace("Z", "+00:00"))
        self.norad_id = omm.get("NORAD_CAT_ID")
        self.sat_name = omm.get("OBJECT_NAME", "")
        self.active = True
        self._running = True

        def loop():
            log.info("Tracking %s (NORAD %s) until %s", self.sat_name, self.norad_id, set_time_str)
            natural_end = False
            while self._running:
                now = datetime.now(timezone.utc)
                if now >= set_time:
                    log.info("Pass ended for %s", self.sat_name)
                    natural_end = True
                    break

                sat_ecef = satellite_ecef_at(satrec, now)
                if sat_ecef is not None:
                    az, el = compute_az_el(obs_lat, obs_lon, obs_alt_km, sat_ecef)
                    with self._lock:
                        self.current_az = az
                        self.current_el = el
                    log.debug("az=%.1f el=%.1f", az, el)
                    for cb in self._on_telemetry_callbacks:
                        try:
                            cb(az, el)
                        except Exception:
                            pass

                time.sleep(update_interval)

            self.active = False
            self._running = False
            if self._state_mgr and natural_end:
                self._state_mgr.transition(State.READY)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the tracking loop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        self.active = False

    def get_az_el(self) -> tuple[float, float]:
        with self._lock:
            return self.current_az, self.current_el
