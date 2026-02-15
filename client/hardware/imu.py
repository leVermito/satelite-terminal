"""IMU hardware reader for DFRobot SEN0386 (WT61PC).

Extracted from tests/test_imu.py:WT61PC_UART.
Data reading only -- no curses UI.
"""

import logging
import struct
import time

log = logging.getLogger("sdr.imu")

FRAME_HEADER = 0x55
FRAME_LEN = 11
TYPE_ACCEL = 0x51
TYPE_GYRO = 0x52
TYPE_ANGLE = 0x53

ACCEL_SCALE = 16.0 / 32768.0 * 9.8
GYRO_SCALE = 2000.0 / 32768.0
ANGLE_SCALE = 180.0 / 32768.0

FREQ_CMD_PREFIX = bytes([0xFF, 0xAA, 0x03])
FREQ_CMD_SUFFIX = bytes([0x00])
FREQ_CODES = {
    "0.1": 0x01, "0.5": 0x02, "1": 0x03, "2": 0x04,
    "5": 0x05, "10": 0x06, "20": 0x07, "50": 0x08,
    "100": 0x09, "125": 0x0A, "200": 0x0B,
}


class WT61PC:
    """UART driver for DFRobot SEN0386 (WT61PC) IMU."""

    def __init__(self, port="/dev/serial0", baud=9600, freq="10"):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.1)
        time.sleep(0.1)
        self.ser.reset_input_buffer()
        self.data = {
            "ax": 0.0, "ay": 0.0, "az": 0.0,
            "gx": 0.0, "gy": 0.0, "gz": 0.0,
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "frames": 0,
        }
        self._buf = bytearray()
        if freq in FREQ_CODES:
            cmd = FREQ_CMD_PREFIX + bytes([FREQ_CODES[freq]]) + FREQ_CMD_SUFFIX
            self.ser.write(cmd)
            time.sleep(0.05)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self._poll()
            if self.data["frames"] > 0:
                log.info("IMU ready on %s @ %d baud, freq=%s Hz", port, baud, freq)
                return
        raise RuntimeError(f"No valid IMU frames on {port} @ {baud} baud within 3s")

    def _parse_frame(self, frame):
        if len(frame) != FRAME_LEN or frame[0] != FRAME_HEADER:
            return
        if (sum(frame[:10]) & 0xFF) != frame[10]:
            return
        ftype = frame[1]
        x = struct.unpack_from("<h", frame, 2)[0]
        y = struct.unpack_from("<h", frame, 4)[0]
        z = struct.unpack_from("<h", frame, 6)[0]
        if ftype == TYPE_ACCEL:
            self.data["ax"] = x * ACCEL_SCALE
            self.data["ay"] = y * ACCEL_SCALE
            self.data["az"] = z * ACCEL_SCALE
        elif ftype == TYPE_GYRO:
            self.data["gx"] = x * GYRO_SCALE
            self.data["gy"] = y * GYRO_SCALE
            self.data["gz"] = z * GYRO_SCALE
        elif ftype == TYPE_ANGLE:
            self.data["roll"] = x * ANGLE_SCALE
            self.data["pitch"] = y * ANGLE_SCALE
            self.data["yaw"] = z * ANGLE_SCALE
        self.data["frames"] += 1

    def _poll(self):
        waiting = self.ser.in_waiting
        if waiting > 0:
            self._buf.extend(self.ser.read(waiting))
        while len(self._buf) >= FRAME_LEN:
            idx = self._buf.find(bytes([FRAME_HEADER]))
            if idx < 0:
                self._buf.clear()
                break
            if idx > 0:
                del self._buf[:idx]
            if len(self._buf) < FRAME_LEN:
                break
            if self._buf[1] in (TYPE_ACCEL, TYPE_GYRO, TYPE_ANGLE):
                self._parse_frame(bytes(self._buf[:FRAME_LEN]))
                del self._buf[:FRAME_LEN]
            else:
                del self._buf[:1]

    def read(self) -> dict:
        self._poll()
        return dict(self.data)

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None


class NullIMU:
    """Fallback when no IMU hardware available."""
    def read(self):
        return {
            "ax": 0.0, "ay": 0.0, "az": 0.0,
            "gx": 0.0, "gy": 0.0, "gz": 0.0,
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "calibrated": False, "frames": 0,
        }
    def close(self):
        pass


def create_imu(port: str = "/dev/serial0", baud: int = 9600, freq: str = "10"):
    """Factory: create IMU reader with fallback."""
    try:
        return WT61PC(port=port, baud=baud, freq=freq)
    except Exception as e:
        log.warning("IMU init failed (%s), using NullIMU", e)
        return NullIMU()
