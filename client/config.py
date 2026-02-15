"""Client configuration loader.

Creates config.toml with a unique client_id (UUID) on first run.
"""

import logging
import uuid
from pathlib import Path

import tomlkit

log = logging.getLogger("sdr.client_config")

CONFIG_FILE = Path(__file__).parent / "config.toml"

_defaults = {
    "client_id": "",
    "mqtt_broker": "192.168.1.100",
    "mqtt_port": 1883,
    "mqtt_username": "",
    "mqtt_password": "",
    "gps_type": "pigpio",
    "gps_baud": 9600,
    "gps_gpio": 18,
    "imu_port": "/dev/serial0",
    "imu_baud": 9600,
    "imu_freq": "10",
    "tracking_interval": 0.25,
}


def _generate_config():
    """Create a default config.toml with a fresh UUID as client_id."""
    doc = tomlkit.document()
    doc.add(tomlkit.comment("SDR client configuration"))
    doc.add(tomlkit.nl())

    client = tomlkit.table()
    client.add("client_id", str(uuid.uuid4()))
    doc.add("client", client)

    doc.add(tomlkit.nl())

    mqt = tomlkit.table()
    mqt.add("broker", "192.168.1.100")
    mqt.add("port", 1883)
    mqt.add("username", "")
    mqt.add("password", "")
    doc.add("mqtt", mqt)

    doc.add(tomlkit.nl())

    hw = tomlkit.table()
    hw.add(tomlkit.comment('"pigpio" or "none"'))
    hw.add("gps_type", "pigpio")
    hw.add("gps_baud", 9600)
    hw.add("gps_gpio", 18)
    hw.add("imu_port", "/dev/serial0")
    hw.add("imu_baud", 9600)
    hw.add("imu_freq", "10")
    hw.add("tracking_interval", 0.25)
    doc.add("hardware", hw)

    CONFIG_FILE.write_text(tomlkit.dumps(doc), encoding="utf-8")
    log.info("Generated %s with client_id=%s", CONFIG_FILE, client["client_id"])
    return doc


def load_config() -> dict:
    cfg = dict(_defaults)

    if not CONFIG_FILE.exists():
        doc = _generate_config()
    else:
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            doc = tomlkit.parse(raw)
        except Exception as e:
            log.warning("Config load error: %s", e)
            doc = tomlkit.document()

    if "client" in doc:
        for k, v in doc["client"].items():
            cfg[k] = v
    if "mqtt" in doc:
        mqt = doc["mqtt"]
        if "broker" in mqt:
            cfg["mqtt_broker"] = mqt["broker"]
        if "port" in mqt:
            cfg["mqtt_port"] = mqt["port"]
        if "username" in mqt:
            cfg["mqtt_username"] = mqt["username"]
        if "password" in mqt:
            cfg["mqtt_password"] = mqt["password"]
    if "hardware" in doc:
        for k, v in doc["hardware"].items():
            cfg[k] = v

    # Backfill client_id if missing or empty in existing config
    if not cfg["client_id"]:
        cfg["client_id"] = str(uuid.uuid4())
        if "client" not in doc:
            doc.add("client", tomlkit.table())
        doc["client"]["client_id"] = cfg["client_id"]
        CONFIG_FILE.write_text(tomlkit.dumps(doc), encoding="utf-8")
        log.info("Assigned client_id=%s", cfg["client_id"])

    return cfg
