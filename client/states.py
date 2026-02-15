"""Client state machine: enum, transitions, thread-safe manager."""

import enum
import logging
import threading
import time

log = logging.getLogger("sdr.state")


class State(enum.Enum):
    BOOT = "boot"
    INITIALIZING = "initializing"
    GPS_WAIT = "gps_wait"
    GPS_ACQUIRED = "gps_acquired"
    READY = "ready"
    TRACKING = "tracking"
    DEGRADED = "degraded"
    ERROR = "error"
    SHUTDOWN = "shutdown"


TRANSITIONS: dict[State, set[State]] = {
    State.BOOT:           {State.INITIALIZING, State.ERROR, State.SHUTDOWN},
    State.INITIALIZING:   {State.GPS_WAIT, State.READY, State.ERROR, State.SHUTDOWN},
    State.GPS_WAIT:       {State.GPS_ACQUIRED, State.ERROR, State.SHUTDOWN},
    State.GPS_ACQUIRED:   {State.READY, State.ERROR, State.SHUTDOWN},
    State.READY:          {State.TRACKING, State.GPS_WAIT, State.DEGRADED, State.ERROR, State.SHUTDOWN},
    State.TRACKING:       {State.READY, State.ERROR, State.SHUTDOWN},
    State.DEGRADED:       {State.READY, State.ERROR, State.SHUTDOWN},
    State.ERROR:          {State.READY, State.GPS_WAIT, State.INITIALIZING, State.SHUTDOWN},
    State.SHUTDOWN:       set(),
}


class StateManager:

    def __init__(self):
        self._state = State.BOOT
        self._error_detail = ""
        self._state_since = time.time()
        self._lock = threading.Lock()
        self._on_transition_callbacks: list = []

    def on_transition(self, callback):
        """Register callback(new_state_value, error_detail) fired after each transition."""
        self._on_transition_callbacks.append(callback)

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    @property
    def error_detail(self) -> str:
        with self._lock:
            return self._error_detail

    @property
    def state_since(self) -> float:
        with self._lock:
            return self._state_since

    def transition(self, new_state: State, error_detail: str = "") -> bool:
        with self._lock:
            allowed = TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                log.warning("Invalid transition %s -> %s", self._state.value, new_state.value)
                return False
            old = self._state
            self._state = new_state
            self._error_detail = error_detail if new_state == State.ERROR else ""
            self._state_since = time.time()
        log.info("State: %s -> %s", old.value, new_state.value)
        for cb in self._on_transition_callbacks:
            try:
                cb(new_state.value, self._error_detail)
            except Exception:
                pass
        return True

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "state_since": self._state_since,
                "error_detail": self._error_detail,
            }
