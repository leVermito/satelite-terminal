#!/usr/bin/env python3
"""SDR antenna client daemon.

Starts hardware (GPS, IMU), connects to MQTT broker,
publishes state/telemetry, receives commands.

With --debug-ui: same daemon, but the foreground loop is a curses
hardware display instead of a silent sleep loop.
"""

import argparse
import logging
import signal
import threading
import time
from pathlib import Path

ERROR_LOG = Path(__file__).parent / "error.log"


def _setup_logging(debug_ui: bool, gps):
    """Configure logging: INFO to app_log (debug-ui) or stdout, WARNING+ to error.log."""
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s",
                            datefmt="%H:%M:%S")

    # File handler for WARNING+ -- always active
    file_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.root.addHandler(file_handler)

    if debug_ui:
        # Route INFO-only to gps.app_log for curses display.
        # WARNING+ goes only to error.log (file handler above).
        class _DequeHandler(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    return
                try:
                    gps.app_log.append(self.format(record))
                except Exception:
                    gps.app_log.append(f"{record.levelname} {record.name}: [log format error]")

        handler = _DequeHandler()
        handler.setFormatter(fmt)
        logging.root.addHandler(handler)
    else:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        logging.root.addHandler(console)

    logging.root.setLevel(logging.INFO)


def main():
    parser = argparse.ArgumentParser(description="SDR antenna client")
    parser.add_argument("--debug-ui", action="store_true",
                        help="Show curses hardware debug UI (daemon still runs)")
    parser.add_argument("--test-motor", action="store_true",
                        help="Run motor test: 2.5s forward, 2.5s reverse, then exit")
    args = parser.parse_args()

    if args.test_motor:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(name)s %(levelname)s %(message)s",
                            datefmt="%H:%M:%S")
        from hardware.motor import test_cycle, cleanup
        try:
            test_cycle(duration=15.0, speed=10)
        finally:
            cleanup()
        return

    from config import load_config

    cfg = load_config()

    from hardware.gps import create_gps, get_hostname
    from hardware.imu import create_imu
    from tracking import TrackingLoop
    from mqtt_client import ClientMQTTClient
    from states import State, StateManager

    state_mgr = StateManager()
    stop_event = threading.Event()

    def sigterm_handler(sig, frame):
        state_mgr.transition(State.SHUTDOWN)
        stop_event.set()

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)

    gps = create_gps(
        gps_type=cfg["gps_type"],
        baud=cfg.get("gps_baud", 9600),
        gpio=cfg.get("gps_gpio", 18),
    )

    imu = create_imu(
        port=cfg.get("imu_port", "/dev/serial0"),
        baud=cfg.get("imu_baud", 9600),
        freq=cfg.get("imu_freq", "10"),
    )

    _setup_logging(args.debug_ui, gps)
    log = logging.getLogger("sdr.client")

    client_id = cfg["client_id"]
    start_time = time.time()

    tracker = TrackingLoop(state_mgr=state_mgr)

    def daemon_startup():
        """MQTT connect, GPS wait, IMU cal, ready signal."""

        log.info("Client %s starting", client_id)
        state_mgr.transition(State.INITIALIZING)

        # --- Detect capabilities ---

        capabilities = []
        gps_data = gps.read() if gps else None
        if gps_data is not None:
            capabilities.append("gps")
        imu_data = imu.read() if imu else None
        if imu_data is not None and imu_data.get("frames", 0) > 0:
            capabilities.append("imu")

        hostname = get_hostname()

        # --- MQTT client ---

        mqtt = ClientMQTTClient(
            client_id=client_id,
            hostname=hostname,
            broker_host=cfg["mqtt_broker"],
            broker_port=cfg["mqtt_port"],
            username=cfg.get("mqtt_username", ""),
            password=cfg.get("mqtt_password", ""),
            state_mgr=state_mgr,
            tracker=tracker,
            gps_reader=gps,
            imu_reader=imu,
            start_time=start_time,
        )

        # Wire callbacks: auto-publish state on every transition
        state_mgr.on_transition(lambda state, err: mqtt.publish_state())

        # Wire telemetry callback
        tracker.on_telemetry(lambda az, el: mqtt.publish_telemetry(az, el))

        mqtt.start(capabilities)
        log.info("MQTT client started")

        # --- Wait for GPS fix, publish location ---

        if cfg["gps_type"] == "none":
            state_mgr.transition(State.READY)
        else:
            state_mgr.transition(State.GPS_WAIT)
            log.info("Waiting for GPS fix...")
            for _ in range(120):
                if stop_event.is_set():
                    mqtt.stop()
                    return
                gps_data = gps.read() if gps else None
                if gps_data and gps_data.get("fix"):
                    state_mgr.transition(State.GPS_ACQUIRED)
                    mqtt.publish_location(gps_data)
                    log.info("GPS fix: %.6f, %.6f (%d sats)",
                             gps_data["lat"], gps_data["lon"], gps_data.get("sats", 0))
                    break
                time.sleep(1)

        # --- Send IMU calibration ---

        imu_data = imu.read() if imu else None
        if imu_data and imu_data.get("frames", 0) > 0:
            mqtt.publish_calibration({
                "roll": imu_data.get("roll", 0.0),
                "pitch": imu_data.get("pitch", 0.0),
                "yaw": imu_data.get("yaw", 0.0),
                "calibrated": True,
            })

        # --- Signal ready ---

        if state_mgr.state != State.READY:
            state_mgr.transition(State.READY)
        log.info("Client ready, waiting for commands")

        # --- Background maintenance loop ---
        # - Monitor mqtt.connected: if False for >120s in READY, transition DEGRADED
        # - On reconnect (was DEGRADED, now connected): transition READY
        # - Periodic location: every 300s

        LOCATION_INTERVAL = 300
        DISCONNECT_TIMEOUT = 120
        RECONNECT_INTERVAL = 30
        GPS_RECONNECT_INTERVAL = 30

        last_location_time = time.time()
        disconnect_start = 0.0
        last_reconnect_attempt = 0.0
        last_gps_reconnect = 0.0

        while not stop_event.is_set():
            try:
                time.sleep(1)
                now = time.time()
                cur_state = state_mgr.state

                # --- MQTT connectivity watchdog ---
                if not mqtt.connected:
                    if disconnect_start == 0.0:
                        disconnect_start = now

                    elapsed = now - disconnect_start

                    if cur_state == State.READY and elapsed > DISCONNECT_TIMEOUT:
                        log.warning("MQTT disconnected for %ds, entering degraded", int(elapsed))
                        state_mgr.transition(State.DEGRADED)
                    elif cur_state == State.TRACKING:
                        # Tracking is protected -- never degrade while aiming.
                        # Reset disconnect timer so DEGRADED doesn't trigger
                        # instantly when tracking ends and state returns to READY.
                        disconnect_start = now
                        if now - last_reconnect_attempt > RECONNECT_INTERVAL:
                            last_reconnect_attempt = now
                            log.debug("MQTT disconnected during tracking, attempting reconnect")
                            mqtt.force_reconnect()
                    elif cur_state == State.DEGRADED and now - last_reconnect_attempt > RECONNECT_INTERVAL:
                        last_reconnect_attempt = now
                        log.info("MQTT still disconnected in degraded, forcing reconnect")
                        mqtt.force_reconnect()
                else:
                    if disconnect_start > 0.0:
                        disconnect_start = 0.0
                        last_reconnect_attempt = 0.0
                        if cur_state == State.DEGRADED:
                            log.info("MQTT reconnected, resuming ready")
                            state_mgr.transition(State.READY)

                # --- GPS recovery ---
                if cfg["gps_type"] != "none" and not gps.connected:
                    if now - last_gps_reconnect > GPS_RECONNECT_INTERVAL:
                        last_gps_reconnect = now
                        log.info("GPS disconnected, attempting reconnect")
                        if gps.reconnect():
                            log.info("GPS reconnected, waiting for fix")
                            state_mgr.transition(State.GPS_WAIT)
                            for _ in range(120):
                                if stop_event.is_set():
                                    break
                                gps_data = gps.read() if gps else None
                                if gps_data and gps_data.get("fix"):
                                    state_mgr.transition(State.GPS_ACQUIRED)
                                    mqtt.publish_location(gps_data)
                                    log.info("GPS fix recovered: %.6f, %.6f (%d sats)",
                                             gps_data["lat"], gps_data["lon"],
                                             gps_data.get("sats", 0))
                                    state_mgr.transition(State.READY)
                                    break
                                time.sleep(1)
                            else:
                                log.warning("GPS reconnected but no fix within timeout")
                                state_mgr.transition(State.READY)

                # --- Periodic location update ---
                if now - last_location_time > LOCATION_INTERVAL:
                    gps_data = gps.read() if gps else None
                    if gps_data and gps_data.get("fix"):
                        mqtt.publish_location(gps_data)
                    last_location_time = now

            except Exception:
                log.exception("Maintenance loop error")
                if state_mgr.state not in (State.DEGRADED, State.SHUTDOWN):
                    state_mgr.transition(State.DEGRADED)

        mqtt.stop()

    try:
        if args.debug_ui:
            # Run daemon startup in background so UI appears immediately
            daemon_thread = threading.Thread(target=daemon_startup, daemon=True)
            daemon_thread.start()

            from debug_ui import run as run_debug_ui
            run_debug_ui(gps, imu, state_mgr, stop_event)
        else:
            daemon_startup()

    finally:
        tracker.stop()
        gps.close()
        imu.close()
        log.info("Client shutdown")


if __name__ == "__main__":
    main()
