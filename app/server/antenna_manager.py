"""Client registry and command manager.

Maintains state of all connected RPi antenna clients.
Commands dispatched via MQTT. State updates received via MQTT callbacks.
"""

import logging
import threading

from .models import (
    ClientGPSInfo,
    ClientIMUInfo,
    ClientState,
    ClientStateInfo,
    ClientSummary,
    GPSData,
    TrackingInfo,
)

log = logging.getLogger("sdr.antenna_manager")


class AntennaManager:

    def __init__(self):
        self._clients: dict[str, ClientState] = {}
        self._lock = threading.Lock()
        self._callbacks: list = []
        self._mqtt_client = None

    def set_mqtt_client(self, mqtt_client):
        self._mqtt_client = mqtt_client

    # --- Registry ---

    def register(self, client_id: str, hostname: str,
                 capabilities: list[str], status: str):
        with self._lock:
            self._clients[client_id] = ClientState(
                client_id=client_id,
                hostname=hostname,
                capabilities=capabilities,
                status=status,
            )
        log.info("Client registered: %s (%s)", client_id, hostname)
        self._notify()

    def update_location(self, client_id: str, gps: GPSData):
        with self._lock:
            c = self._clients.get(client_id)
            if c:
                c.gps = gps
        self._notify()

    def update_calibration(self, client_id: str, imu_data: dict):
        with self._lock:
            c = self._clients.get(client_id)
            if c:
                c.imu_calibrated = imu_data.get("calibrated", False)
        self._notify()

    def update_state(self, client_id: str, payload: dict):
        """Update client from a state MQTT message."""
        with self._lock:
            c = self._clients.get(client_id)
            if not c:
                return
            state_val = payload.get("state", "")
            if state_val:
                c.status = state_val
            c.uptime_s = payload.get("uptime_s", c.uptime_s)
            c.client_state_info = ClientStateInfo(
                state=state_val,
                state_since=payload.get("state_since", 0.0),
                error_detail=payload.get("error_detail", ""),
            )
            tracking = payload.get("tracking")
            if tracking:
                c.tracking = TrackingInfo(
                    active=True,
                    norad_id=tracking.get("norad_id"),
                    name=tracking.get("name"),
                )
            elif state_val not in ("tracking",):
                c.tracking = None
        self._notify()

    def update_telemetry(self, client_id: str, az: float, el: float):
        with self._lock:
            c = self._clients.get(client_id)
            if c:
                c.tracking_az = az
                c.tracking_el = el
        self._notify()

    def update_full_status(self, client_id: str, payload: dict):
        with self._lock:
            c = self._clients.get(client_id)
            if not c:
                return
            c.last_full_status = payload
            c.uptime_s = payload.get("uptime_s", c.uptime_s)
            state_info = payload.get("state")
            if state_info:
                c.client_state_info = ClientStateInfo(**state_info)
                c.status = state_info.get("state", c.status)
            gps_info = payload.get("gps")
            if gps_info:
                c.client_gps_info = ClientGPSInfo(**gps_info)
            imu_info = payload.get("imu")
            if imu_info:
                c.client_imu_info = ClientIMUInfo(**imu_info)
            tracking = payload.get("tracking")
            if tracking:
                c.tracking = TrackingInfo(
                    active=tracking.get("active", False),
                    norad_id=tracking.get("norad_id"),
                    name=tracking.get("name"),
                )
                c.tracking_az = tracking.get("az", 0.0)
                c.tracking_el = tracking.get("el", 0.0)
        self._notify()

    def mark_offline(self, client_id: str):
        with self._lock:
            c = self._clients.get(client_id)
            if c:
                c.status = "offline"
                c.client_state_info = ClientStateInfo(state="offline")
                c.tracking = None
        log.warning("Client %s offline (LWT)", client_id)
        self._notify()

    def get_client(self, client_id: str) -> ClientState | None:
        with self._lock:
            return self._clients.get(client_id)

    def get_all_clients(self) -> list[ClientSummary]:
        with self._lock:
            return [
                ClientSummary(
                    client_id=c.client_id,
                    hostname=c.hostname,
                    status=c.status,
                    gps=c.gps,
                    tracking=c.tracking,
                    client_state_info=c.client_state_info,
                    client_gps_info=c.client_gps_info,
                    client_imu_info=c.client_imu_info,
                )
                for c in self._clients.values()
            ]

    def get_clients_with_gps(self) -> list[ClientState]:
        """Return clients that have a GPS fix."""
        with self._lock:
            return [c for c in self._clients.values() if c.gps is not None]

    # --- Commands (via MQTT) ---

    def push_track(self, client_id: str, omm: dict, rise_time: str, set_time: str) -> bool:
        if not self._mqtt_client:
            return False
        with self._lock:
            c = self._clients.get(client_id)
        if not c:
            return False
        self._mqtt_client.publish_track(client_id, omm, rise_time, set_time)
        with self._lock:
            c.tracking = TrackingInfo(
                active=True,
                norad_id=omm.get("NORAD_CAT_ID"),
                name=omm.get("OBJECT_NAME"),
            )
        self._notify()
        return True

    def push_stop(self, client_id: str) -> bool:
        if not self._mqtt_client:
            return False
        with self._lock:
            c = self._clients.get(client_id)
        if not c:
            return False
        self._mqtt_client.publish_stop(client_id)
        return True

    def request_status(self, client_id: str):
        """Non-blocking: publishes status request. Result arrives via update_full_status."""
        if self._mqtt_client:
            self._mqtt_client.publish_status_request(client_id)

    # --- Callbacks for TUI updates ---

    def on_change(self, callback):
        self._callbacks.append(callback)

    def _notify(self):
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                pass
