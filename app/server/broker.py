"""Embedded mosquitto broker subprocess manager."""

import logging
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger("sdr.broker")

DATA_DIR = Path(__file__).parent.parent / "data" / "mqtt"


class MosquittoBroker:

    def __init__(self, host: str = "0.0.0.0", port: int = 1883,
                 username: str = "", password: str = "",
                 config_dir: Path | None = None):
        self._host = str(host)
        self._port = int(port)
        self._username = str(username)
        self._password = str(password)
        self._config_dir = config_dir or DATA_DIR
        self._proc: subprocess.Popen | None = None

    @property
    def _pid_file(self) -> Path:
        return self._config_dir / "mosquitto.pid"

    def _write_config(self) -> Path:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        conf = self._config_dir / "mosquitto.conf"

        lines = [
            f"listener {self._port} {self._host}",
            f"pid_file {self._pid_file}",
            "persistence false",
            "log_type error",
            "log_type warning",
        ]

        if self._username and self._password:
            pw_file = self._write_password_file()
            lines.append("allow_anonymous false")
            lines.append(f"password_file {pw_file}")
        else:
            lines.append("allow_anonymous true")

        conf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return conf

    def _write_password_file(self) -> Path:
        pw_file = self._config_dir / "passwd"
        mosquitto_passwd = shutil.which("mosquitto_passwd")
        if not mosquitto_passwd:
            log.error("mosquitto_passwd not found in PATH")
            raise FileNotFoundError("mosquitto_passwd")

        subprocess.run(
            [mosquitto_passwd, "-b", "-c", str(pw_file),
             self._username, self._password],
            check=True, capture_output=True,
        )
        return pw_file

    def _kill_stale(self):
        """Kill leftover mosquitto from a previous crashed run."""
        if not self._pid_file.exists():
            return
        try:
            old_pid = int(self._pid_file.read_text().strip())
            os.kill(old_pid, signal.SIGTERM)
            log.info("Killed stale mosquitto (pid %d)", old_pid)
            # Give it a moment to release the socket
            for _ in range(10):
                try:
                    os.kill(old_pid, 0)  # check if still alive
                    time.sleep(0.1)
                except ProcessLookupError:
                    break
            else:
                # Still alive after 1s, force kill
                try:
                    os.kill(old_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        self._pid_file.unlink(missing_ok=True)

    def start(self):
        if self._proc and self._proc.poll() is None:
            return

        self._kill_stale()
        conf = self._write_config()
        mosquitto = shutil.which("mosquitto")
        if not mosquitto:
            log.error("mosquitto not found in PATH")
            raise FileNotFoundError("mosquitto")

        self._proc = subprocess.Popen(
            [mosquitto, "-c", str(conf)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        if self._proc.poll() is not None:
            stderr = self._proc.stderr.read().decode(errors="replace") if self._proc.stderr else ""
            log.error("Mosquitto failed to start: %s", stderr)
            raise RuntimeError(f"Mosquitto exited immediately: {stderr}")
        log.info("Mosquitto broker started on %s:%d (pid %d)",
                 self._host, self._port, self._proc.pid)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
            log.info("Mosquitto broker stopped")
        self._proc = None
        self._pid_file.unlink(missing_ok=True)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
