"""Client-side MQTT wrapper: publishes state/telemetry, receives commands."""

from __future__ import annotations

import json
import logging
import time

import paho.mqtt.client as mqtt

from states import State

log = logging.getLogger("sdr.client_mqtt")


class ClientMQTTClient:

    def __init__(self, client_id: str, hostname: str,
                 broker_host: str, broker_port: int,
                 username: str, password: str,
                 state_mgr, tracker, gps_reader, imu_reader, start_time: float):
        self._client_id = client_id
        self._hostname = hostname
        self._state_mgr = state_mgr
        self._tracker = tracker
        self._gps_reader = gps_reader
        self._imu_reader = imu_reader
        self._start_time = start_time
        self._broker_host = str(broker_host)
        self._broker_port = int(broker_port)
        self._connected = False
        self._capabilities = []

        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id=f"sdr-client-{client_id}")
        if username:
            self._mqtt.username_pw_set(username, password)
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.on_message = self._on_message
        self._mqtt.reconnect_delay_set(min_delay=1, max_delay=30)

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, capabilities: list[str]):
        self._capabilities = capabilities

        # Set LWT before connecting
        lwt_payload = json.dumps({
            "client_id": self._client_id,
            "hostname": self._hostname,
            "capabilities": self._capabilities,
            "state": "offline",
            "state_since": 0.0,
            "error_detail": "",
            "uptime_s": 0,
            "tracking": None,
        })
        self._mqtt.will_set(
            f"sdr/clients/{self._client_id}/state",
            lwt_payload, qos=1, retain=True,
        )

        self._mqtt.connect_async(self._broker_host, self._broker_port, keepalive=60)
        self._mqtt.loop_start()
        log.info("MQTT client connecting to %s:%d", self._broker_host, self._broker_port)

    def force_reconnect(self):
        """Force a reconnect attempt when Paho's internal loop has stalled."""
        try:
            self._mqtt.reconnect()
        except Exception as exc:
            log.debug("Force reconnect failed: %s", exc)

    def stop(self):
        # Publish clean shutdown state
        self._publish_state_payload("shutdown")
        self._mqtt.loop_stop()
        self._mqtt.disconnect()
        log.info("MQTT client stopped")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            log.info("MQTT connected to broker")
            client.subscribe(f"sdr/cmd/{self._client_id}/#", qos=1)
            client.subscribe(f"sdr/clients/{self._client_id}/status/request", qos=1)
            # Publish current state on connect/reconnect
            self.publish_state()
            # Re-publish location so restarted server gets GPS data immediately
            gps_data = self._gps_reader.read() if self._gps_reader else None
            if gps_data and gps_data.get("fix"):
                self.publish_location(gps_data)
        else:
            log.error("MQTT connect failed: rc=%s", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        if rc != 0:
            log.warning("MQTT disconnected unexpectedly (rc=%s), will reconnect", rc)

    def _on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")

        try:
            payload = json.loads(msg.payload) if msg.payload else {}
        except (json.JSONDecodeError, ValueError):
            log.warning("Bad JSON on %s", msg.topic)
            return

        # sdr/cmd/{id}/track or sdr/cmd/{id}/stop
        if len(parts) == 4 and parts[0] == "sdr" and parts[1] == "cmd":
            cmd = parts[3]
            if cmd == "track":
                self._handle_track(payload)
            elif cmd == "stop":
                self._handle_stop()
            return

        # sdr/clients/{id}/status/request
        if msg.topic == f"sdr/clients/{self._client_id}/status/request":
            self.publish_status()

    def _handle_track(self, payload: dict):
        omm = payload.get("omm")
        set_time = payload.get("set_time", "")
        if not omm or not set_time:
            log.warning("Track command missing omm or set_time")
            return

        gps_data = self._gps_reader.read() if self._gps_reader else None
        if not gps_data or not gps_data.get("fix"):
            log.error("Track command received but no GPS fix")
            return

        obs_lat = gps_data["lat"]
        obs_lon = gps_data["lon"]
        obs_alt_km = gps_data.get("alt", 0.0) / 1000.0

        self._state_mgr.transition(State.TRACKING)
        self._tracker.start(omm, obs_lat, obs_lon, obs_alt_km, set_time)
        log.info("Track command: %s (NORAD %s)",
                 omm.get("OBJECT_NAME", "?"), omm.get("NORAD_CAT_ID"))

    def _handle_stop(self):
        self._tracker.stop()
        self._state_mgr.transition(State.READY)
        log.info("Stop command received")

    # --- Publishers ---

    def _publish_state_payload(self, state_override: str | None = None):
        tracking = None
        if self._tracker.active:
            tracking = {
                "norad_id": self._tracker.norad_id,
                "name": self._tracker.sat_name,
            }

        payload = json.dumps({
            "client_id": self._client_id,
            "hostname": self._hostname,
            "capabilities": self._capabilities,
            "state": state_override or self._state_mgr.state.value,
            "state_since": self._state_mgr.state_since,
            "error_detail": self._state_mgr.error_detail,
            "uptime_s": time.time() - self._start_time,
            "tracking": tracking,
        })
        self._mqtt.publish(
            f"sdr/clients/{self._client_id}/state",
            payload, qos=1, retain=True,
        )

    def publish_state(self):
        self._publish_state_payload()

    def publish_location(self, gps_data: dict):
        payload = json.dumps({
            "client_id": self._client_id,
            "gps": {
                "lat": gps_data.get("lat", 0.0),
                "lon": gps_data.get("lon", 0.0),
                "alt_m": gps_data.get("alt", 0.0),
                "satellites": gps_data.get("sats", 0),
                "hdop": gps_data.get("hdop", 0.0) or 0.0,
            },
        })
        self._mqtt.publish(
            f"sdr/clients/{self._client_id}/location",
            payload, qos=1, retain=True,
        )

    def publish_calibration(self, imu_data: dict):
        payload = json.dumps({
            "client_id": self._client_id,
            "imu": {
                "roll": imu_data.get("roll", 0.0),
                "pitch": imu_data.get("pitch", 0.0),
                "yaw": imu_data.get("yaw", 0.0),
                "calibrated": imu_data.get("calibrated", False),
            },
        })
        self._mqtt.publish(
            f"sdr/clients/{self._client_id}/imu/calibration",
            payload, qos=1, retain=True,
        )

    def publish_telemetry(self, az: float, el: float):
        payload = json.dumps({
            "az": az, "el": el, "ts": time.time(),
        })
        self._mqtt.publish(
            f"sdr/clients/{self._client_id}/telemetry",
            payload, qos=0, retain=False,
        )

    def publish_status(self):
        gps_data = self._gps_reader.read() if self._gps_reader else None
        imu_data = self._imu_reader.read() if self._imu_reader else None

        az, el = (0.0, 0.0)
        if self._tracker.active:
            az, el = self._tracker.get_az_el()

        tracking_info = None
        if self._tracker.active:
            tracking_info = {
                "active": True,
                "norad_id": self._tracker.norad_id,
                "name": self._tracker.sat_name,
                "az": az,
                "el": el,
            }

        gps_info = None
        if gps_data:
            gps_info = {
                "fix": bool(gps_data.get("fix")),
                "satellites": gps_data.get("sats", 0),
                "hdop": gps_data.get("hdop"),
            }

        imu_info = None
        if imu_data and imu_data.get("frames", 0) > 0:
            imu_info = {
                "roll": imu_data.get("roll", 0.0),
                "pitch": imu_data.get("pitch", 0.0),
                "yaw": imu_data.get("yaw", 0.0),
            }

        payload = json.dumps({
            "client_id": self._client_id,
            "state": self._state_mgr.to_dict(),
            "uptime_s": time.time() - self._start_time,
            "gps_raw": gps_data,
            "imu_raw": imu_data,
            "gps": gps_info,
            "imu": imu_info,
            "tracking": tracking_info,
        })
        self._mqtt.publish(
            f"sdr/clients/{self._client_id}/status",
            payload, qos=0, retain=True,
        )
