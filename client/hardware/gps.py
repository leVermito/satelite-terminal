"""GPS hardware reader for RPi client.

Provides PigpioGPS (bit-bang serial via pigpio) with stale-session
cleanup and reconnection support, plus NullGPS fallback.
"""

import collections
import logging
import socket
import time

log = logging.getLogger("sdr.gps")


class PigpioGPS:
    """GPS reader via pigpio bit-bang serial on a GPIO pin.

    Handles stale GPIO sessions from prior unclean shutdowns by
    attempting bb_serial_read_close before opening.
    """

    def __init__(self, gpio=18, baud=9600, enable_sbas=True):
        self.gpio = gpio
        self.baud = baud
        self._enable_sbas = enable_sbas
        self._connected = False
        self.pi = None
        self._line_buf = ""
        self.gps_log = collections.deque(maxlen=5)
        self.app_log = collections.deque(maxlen=100)
        self.data = self._empty_data()
        self._init_pigpio()

    @staticmethod
    def _empty_data():
        return {
            "fix": False,
            "lat": 0.0, "lon": 0.0,
            "lat_dir": "N", "lon_dir": "E",
            "alt": 0.0, "sats": 0,
            "quality": "No Fix",
            "hdop": None, "vdop": None,
            "speed": None, "course": None,
            "geoid_sep": None,
            "sentences": 0,
        }

    def _init_pigpio(self):
        """Connect to pigpiod and open bit-bang serial, cleaning up stale state first."""
        import pigpio

        if self.pi and self.pi.connected:
            try:
                self.pi.stop()
            except Exception:
                pass
            self.pi = None

        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpiod not running")

        # Clear any leftover bit-bang session on this GPIO from a prior crash
        self._cleanup_stale()

        self.pi.bb_serial_read_open(self.gpio, self.baud)
        self._connected = True
        self._line_buf = ""

        if self._enable_sbas:
            self._configure()

        log.info("PigpioGPS opened on GPIO%d", self.gpio)

    def _cleanup_stale(self):
        """Close any prior bit-bang session on our GPIO pin. Errors ignored."""
        try:
            self.pi.bb_serial_read_close(self.gpio)
            log.debug("Cleared stale bit-bang on GPIO%d", self.gpio)
        except Exception:
            pass

    @property
    def connected(self):
        return self._connected

    def reconnect(self):
        """Tear down current connection and re-initialize.

        Returns True on success, False on failure. While disconnected,
        read() returns None so callers degrade gracefully.
        """
        log.info("GPS reconnect attempt on GPIO%d", self.gpio)
        self._connected = False

        # Tear down existing connection
        try:
            self.pi.bb_serial_read_close(self.gpio)
        except Exception:
            pass
        try:
            self.pi.stop()
        except Exception:
            pass
        self.pi = None

        try:
            self._init_pigpio()
            self.data = self._empty_data()
            log.info("GPS reconnected on GPIO%d", self.gpio)
            return True
        except Exception as e:
            log.warning("GPS reconnect failed: %s", e)
            self._connected = False
            return False

    def _ubx_frame(self, cls, msg_id, payload):
        sync = bytes([0xB5, 0x62])
        length = len(payload)
        header = sync + bytes([cls, msg_id, length & 0xFF, (length >> 8) & 0xFF])
        data = bytes([cls, msg_id, length & 0xFF, (length >> 8) & 0xFF]) + payload
        ck_a = ck_b = 0
        for b in data:
            ck_a = (ck_a + b) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        return header + payload + bytes([ck_a, ck_b])

    def _send_ubx(self, frame, label):
        import struct
        self.pi.wave_add_serial(self._tx_gpio, 9600, frame)
        wid = self.pi.wave_create()
        self.pi.wave_send_once(wid)
        while self.pi.wave_tx_busy():
            time.sleep(0.01)
        self.pi.wave_delete(wid)
        self.app_log.append(f"{time.strftime('%H:%M:%S')} TX: {label}")
        log.debug("UBX TX: %s", label)

    def _configure(self):
        try:
            import struct
            self._tx_gpio = 17
            self.pi.set_mode(self._tx_gpio, 1)
            self.pi.wave_clear()
            self.app_log.append(f"{time.strftime('%H:%M:%S')} GPS config start (GPIO17 TX)")

            # SBAS
            self._send_ubx(self._ubx_frame(0x06, 0x16,
                bytes([0x01, 0x03, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])), "CFG-SBAS")
            # GPS+GLONASS
            header = bytes([0x00, 56, 56, 0x02])
            gps_block = bytes([0x00, 8, 16, 0x00, 0x01, 0x00, 0x01, 0x00])
            glo_block = bytes([0x06, 8, 14, 0x00, 0x01, 0x00, 0x01, 0x00])
            self._send_ubx(self._ubx_frame(0x06, 0x3E, header + gps_block + glo_block), "CFG-GNSS")
            # 5Hz
            self._send_ubx(self._ubx_frame(0x06, 0x08, struct.pack("<HHH", 200, 1, 1)), "CFG-RATE")
            # NMEA output config
            for cls_id, msg_id, rate in [(0xF0, 0x00, 1), (0xF0, 0x02, 1),
                                          (0xF0, 0x03, 5), (0xF0, 0x04, 1),
                                          (0xF0, 0x01, 0), (0xF0, 0x05, 0)]:
                self._send_ubx(self._ubx_frame(0x06, 0x01, bytes([cls_id, msg_id, rate])), f"MSG {msg_id}")
            # Save
            save_payload = (bytes([0x00]*4) + bytes([0xFF, 0xFF, 0x00, 0x00]) + bytes([0x00]*4))
            self._send_ubx(self._ubx_frame(0x06, 0x09, save_payload), "CFG-SAVE")
            self.app_log.append(f"{time.strftime('%H:%M:%S')} GPS config done")
            log.info("GPS configured (SBAS+GLONASS, 5Hz)")
        except Exception as e:
            log.warning("GPS configure failed: %s", e)

    def _parse_gga(self, sentence):
        try:
            import pynmea2
            msg = pynmea2.parse(sentence)
            if msg.gps_qual and int(msg.gps_qual) > 0:
                qmap = {"0": "No Fix", "1": "GPS", "2": "DGPS", "3": "PPS",
                         "4": "RTK", "5": "Float RTK", "6": "Est", "7": "Manual", "8": "Sim"}
                gsep = None
                try:
                    if msg.geo_sep:
                        gsep = float(msg.geo_sep)
                except (AttributeError, ValueError):
                    pass
                self.data.update({
                    "fix": True,
                    "lat": msg.latitude, "lon": msg.longitude,
                    "lat_dir": msg.lat_dir, "lon_dir": msg.lon_dir,
                    "alt": float(msg.altitude) if msg.altitude else 0.0,
                    "sats": int(msg.num_sats) if msg.num_sats else 0,
                    "quality": qmap.get(msg.gps_qual, "?"),
                    "geoid_sep": gsep,
                })
            else:
                self.data["sats"] = int(msg.num_sats) if msg.num_sats else 0
        except Exception:
            pass

    def _parse_rmc(self, sentence):
        try:
            import pynmea2
            msg = pynmea2.parse(sentence)
            if msg.spd_over_grnd:
                self.data["speed"] = float(msg.spd_over_grnd) * 1.852
            if msg.true_course:
                self.data["course"] = float(msg.true_course)
        except Exception:
            pass

    def _parse_gsa(self, sentence):
        try:
            fields = sentence.split("*")[0].split(",")
            if len(fields) >= 18:
                hdop = fields[16]
                vdop = fields[17]
                if hdop:
                    self.data["hdop"] = float(hdop)
                if vdop:
                    self.data["vdop"] = float(vdop)
        except Exception:
            pass

    def read(self):
        if not self._connected:
            return None
        try:
            (count, raw) = self.pi.bb_serial_read(self.gpio)
        except Exception:
            self._connected = False
            log.warning("GPS read failed, marking disconnected")
            return None
        if count > 0:
            text = raw.decode("ascii", errors="ignore")
            self._line_buf += text
            while "\n" in self._line_buf:
                line, self._line_buf = self._line_buf.split("\n", 1)
                line = line.strip()
                if not line.startswith("$"):
                    continue
                self.data["sentences"] += 1
                if "GGA" in line:
                    self._parse_gga(line)
                    self.gps_log.append(f"{time.strftime('%H:%M:%S')} {line[:72]}")
                elif "RMC" in line:
                    self._parse_rmc(line)
                elif "GSA" in line:
                    self._parse_gsa(line)
        return dict(self.data)

    def close(self):
        self._connected = False
        try:
            self.pi.bb_serial_read_close(self.gpio)
        except Exception:
            pass
        try:
            self.pi.stop()
        except Exception:
            pass


class NullGPS:
    """Fallback when no GPS hardware is available."""
    gps_log = collections.deque(maxlen=5)
    app_log = collections.deque(maxlen=100)

    @property
    def connected(self):
        return False

    def read(self):
        return None

    def reconnect(self):
        return False

    def close(self):
        pass


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def create_gps(gps_type: str = "pigpio", **kwargs):
    """Factory: create a GPS reader based on type.

    gps_type: "pigpio" or "none"
    """
    if gps_type == "pigpio":
        gpio = kwargs.get("gpio", 18)
        baud = kwargs.get("baud", 9600)

        # First attempt
        try:
            return PigpioGPS(gpio=gpio, baud=baud)
        except Exception as e:
            log.warning("PigpioGPS init failed (%s), retrying in 1s", e)

        # Retry once -- pigpiod may need a moment after restart
        time.sleep(1)
        try:
            return PigpioGPS(gpio=gpio, baud=baud)
        except Exception as e:
            log.warning("PigpioGPS retry failed (%s), falling back to NullGPS", e)
            return NullGPS()

    return NullGPS()
