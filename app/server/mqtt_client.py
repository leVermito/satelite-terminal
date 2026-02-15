"""Server-side MQTT client: subscribes to client topics, routes to AntennaManager."""

import json
import logging

import paho.mqtt.client as mqtt

log = logging.getLogger("sdr.server_mqtt")


class ServerMQTTClient:

    def __init__(self, antenna_manager, host: str = "127.0.0.1", port: int = 1883,
                 username: str = "", password: str = ""):
        self._manager = antenna_manager
        self._host = str(host)
        self._port = int(port)
        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self._mqtt.username_pw_set(username, password)
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_message = self._on_message

    def start(self):
        self._mqtt.connect(self._host, self._port, keepalive=60)
        self._mqtt.loop_start()
        log.info("Server MQTT client connecting to %s:%d", self._host, self._port)

    def stop(self):
        self._mqtt.loop_stop()
        self._mqtt.disconnect()
        log.info("Server MQTT client stopped")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("Server MQTT connected")
            client.subscribe("sdr/clients/+/#", qos=1)
        else:
            log.error("Server MQTT connect failed: rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        # Expected: sdr/clients/{id}/...
        if len(parts) < 4 or parts[0] != "sdr" or parts[1] != "clients":
            return

        client_id = parts[2]
        subtopic = "/".join(parts[3:])

        try:
            payload = json.loads(msg.payload) if msg.payload else {}
        except (json.JSONDecodeError, ValueError):
            log.warning("Bad JSON on %s", msg.topic)
            return

        if subtopic == "state":
            self._handle_state(client_id, payload)
        elif subtopic == "location":
            self._handle_location(client_id, payload)
        elif subtopic == "imu/calibration":
            self._handle_calibration(client_id, payload)
        elif subtopic == "telemetry":
            self._handle_telemetry(client_id, payload)
        elif subtopic == "status":
            self._handle_status(client_id, payload)

    def _handle_state(self, client_id: str, payload: dict):
        state = payload.get("state", "")
        if state == "offline":
            self._manager.mark_offline(client_id)
            return

        # Register if new, update if known
        existing = self._manager.get_client(client_id)
        if existing is None:
            self._manager.register(
                client_id=client_id,
                hostname=payload.get("hostname", ""),
                capabilities=payload.get("capabilities", []),
                status=state,
            )
        self._manager.update_state(client_id, payload)

    def _handle_location(self, client_id: str, payload: dict):
        gps = payload.get("gps")
        if gps:
            from .models import GPSData
            self._manager.update_location(client_id, GPSData(**gps))

    def _handle_calibration(self, client_id: str, payload: dict):
        imu = payload.get("imu")
        if imu:
            self._manager.update_calibration(client_id, imu)

    def _handle_telemetry(self, client_id: str, payload: dict):
        self._manager.update_telemetry(
            client_id,
            az=payload.get("az", 0.0),
            el=payload.get("el", 0.0),
        )

    def _handle_status(self, client_id: str, payload: dict):
        self._manager.update_full_status(client_id, payload)

    # --- Publish commands ---

    def publish_track(self, client_id: str, omm: dict, rise_time: str, set_time: str):
        payload = json.dumps({
            "omm": omm,
            "rise_time": rise_time,
            "set_time": set_time,
        })
        self._mqtt.publish(f"sdr/cmd/{client_id}/track", payload, qos=1, retain=False)
        log.info("Published track command to %s", client_id)

    def publish_stop(self, client_id: str):
        self._mqtt.publish(f"sdr/cmd/{client_id}/stop", json.dumps({}), qos=1, retain=False)
        log.info("Published stop command to %s", client_id)

    def publish_status_request(self, client_id: str):
        self._mqtt.publish(f"sdr/clients/{client_id}/status/request",
                           json.dumps({}), qos=1, retain=False)
