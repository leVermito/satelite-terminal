"""Curses debug UI for hardware diagnostics.

Receives pre-initialized hardware objects and state manager from the daemon.
Displays live sensor data and state transitions while the full client
(API server, registration, ping) runs in background threads.

Layout is fully responsive -- sections flow top-to-bottom and are
progressively dropped when the terminal is too small.
"""

import curses
import logging
import math

from states import State

log = logging.getLogger("sdr.debug_ui")

BAR_WIDTH = 40
REFRESH_HZ = 30

# Main-flow states in display order
_FLOW = [
    State.BOOT, State.INITIALIZING, State.GPS_WAIT, State.GPS_ACQUIRED,
    State.READY, State.TRACKING,
]
_SIDE_STATES = [State.DEGRADED, State.ERROR, State.SHUTDOWN]

_STATE_LABELS = {
    State.BOOT: "BOOT",
    State.INITIALIZING: "INIT",
    State.GPS_WAIT: "GPS_WAIT",
    State.GPS_ACQUIRED: "GPS_ACQ",
    State.READY: "READY",
    State.TRACKING: "TRACK",
}


def draw_state_bar(win, y, x, current: State, cols):
    """Draw horizontal state chain: BOOT - INIT - ... with active state green."""
    sep = " - "
    cx = x
    for i, st in enumerate(_FLOW):
        lbl = _STATE_LABELS[st]
        if cx + len(lbl) >= cols:
            break
        if st == current:
            attr = curses.color_pair(1) | curses.A_BOLD
        else:
            attr = curses.A_DIM
        win.addstr(y, cx, lbl, attr)
        cx += len(lbl)
        if i < len(_FLOW) - 1 and cx + len(sep) < cols:
            win.addstr(y, cx, sep, curses.A_DIM)
            cx += len(sep)

    for st in _SIDE_STATES:
        if st == current:
            tag = f"  [{st.value.upper()}]"
            if cx + len(tag) < cols:
                if st == State.ERROR:
                    color = curses.color_pair(2)
                elif st == State.DEGRADED:
                    color = curses.color_pair(5)
                else:
                    color = curses.color_pair(4)
                win.addstr(y, cx, tag, color | curses.A_BOLD)
                cx += len(tag)


def draw_bar(win, y, x, value, max_val, width, label, unit, color_pos, color_neg):
    half = width // 2
    normalized = max(-1.0, min(1.0, value / max_val))
    fill = int(abs(normalized) * half)

    win.addstr(y, x, f"{label}: ", curses.A_BOLD)
    lw = len(label) + 2
    bx = x + lw

    bar = list('.' * width)
    bar[half] = '|'

    if normalized >= 0:
        for i in range(fill):
            if half + 1 + i < width:
                bar[half + 1 + i] = '#'
    else:
        for i in range(fill):
            if half - 1 - i >= 0:
                bar[half - 1 - i] = '#'

    for i, ch in enumerate(bar):
        if ch == '#':
            c = color_pos if normalized >= 0 else color_neg
            win.addch(y, bx + i, ch, curses.color_pair(c) | curses.A_BOLD)
        else:
            win.addch(y, bx + i, ch, curses.A_DIM)

    try:
        win.addstr(y, bx + width + 1, f"{value:+8.2f} {unit}")
    except curses.error:
        pass


def draw_imu(win, row, rows, cols, imu_data, bar_w):
    """Draw IMU section starting at row. Returns next free row."""
    if not imu_data or imu_data.get('frames', 0) == 0:
        if row < rows:
            win.addstr(row, 0, "IMU: not available", curses.color_pair(2))
        return row + 1

    # Accel: header + 3 bars + magnitude = 5 rows
    if row + 5 > rows:
        return row
    win.addstr(row, 0, "ACCELEROMETER", curses.A_BOLD | curses.A_UNDERLINE)
    row += 1
    draw_bar(win, row, 0, imu_data['ax'], 20.0, bar_w, "X", "m/s2", 1, 2)
    draw_bar(win, row + 1, 0, imu_data['ay'], 20.0, bar_w, "Y", "m/s2", 1, 2)
    draw_bar(win, row + 2, 0, imu_data['az'], 20.0, bar_w, "Z", "m/s2", 1, 2)
    row += 3
    mag_a = math.sqrt(imu_data['ax']**2 + imu_data['ay']**2 + imu_data['az']**2)
    win.addstr(row, 0, f"   |A| = {mag_a:.2f} m/s2  ({mag_a/9.8:.3f} g)")
    row += 1

    # Gyro: blank + header + 3 bars + magnitude = 6 rows
    if row + 6 > rows:
        return row
    row += 1  # blank separator
    win.addstr(row, 0, "GYROSCOPE", curses.A_BOLD | curses.A_UNDERLINE)
    row += 1
    draw_bar(win, row, 0, imu_data['gx'], 250.0, bar_w, "X", "d/s", 3, 4)
    draw_bar(win, row + 1, 0, imu_data['gy'], 250.0, bar_w, "Y", "d/s", 3, 4)
    draw_bar(win, row + 2, 0, imu_data['gz'], 250.0, bar_w, "Z", "d/s", 3, 4)
    row += 3
    mag_g = math.sqrt(imu_data['gx']**2 + imu_data['gy']**2 + imu_data['gz']**2)
    win.addstr(row, 0, f"   |G| = {mag_g:.2f} d/s")
    row += 1

    # Kalman angles: blank + header + 3 bars = 5 rows
    if row + 5 > rows:
        return row
    row += 1
    win.addstr(row, 0, "ANGLE (Kalman)", curses.A_BOLD | curses.A_UNDERLINE)
    row += 1
    draw_bar(win, row, 0, imu_data.get('roll', 0), 180.0, bar_w, "Roll ", "deg", 1, 2)
    draw_bar(win, row + 1, 0, imu_data.get('pitch', 0), 180.0, bar_w, "Pitch", "deg", 1, 2)
    draw_bar(win, row + 2, 0, imu_data.get('yaw', 0), 180.0, bar_w, "Yaw  ", "deg", 3, 4)
    row += 3

    return row


def draw_gps(win, row, rows, cols, gps_data):
    """Draw GPS section starting at row. Returns next free row."""
    if gps_data is None:
        if row < rows:
            win.addstr(row, 0, "GPS: not available", curses.color_pair(2))
        return row + 1

    gps_type = gps_data.get('_type', 'serial')
    label = f"GPS  [{gps_type}]"
    if row >= rows:
        return row
    win.addstr(row, 0, label, curses.color_pair(5) | curses.A_BOLD)

    fix = gps_data.get('fix', False)
    fix_str = "FIX" if fix else "NO FIX"
    fix_color = curses.color_pair(1) if fix else curses.color_pair(2)
    try:
        win.addstr(row, len(label) + 2, fix_str, fix_color | curses.A_BOLD)
    except curses.error:
        pass
    row += 1

    lat = gps_data.get('lat', 0)
    lon = gps_data.get('lon', 0)
    lat_d = gps_data.get('lat_dir', 'N')
    lon_d = gps_data.get('lon_dir', 'E')
    hdop = gps_data.get('hdop')
    vdop = gps_data.get('vdop')
    hdop_s = f"{hdop:.1f}" if hdop is not None else "--"
    vdop_s = f"{vdop:.1f}" if vdop is not None else "--"
    spd = gps_data.get('speed')
    crs = gps_data.get('course')
    spd_s = f"{spd:.1f} km/h" if spd is not None else "--"
    crs_s = f"{crs:.1f} deg" if crs is not None else "--"

    lines = [
        f"  Pos:  {abs(lat):.6f} {lat_d}  {abs(lon):.6f} {lon_d}",
        f"  Alt:  {gps_data.get('alt', 0):.1f} m   Sats: {gps_data.get('sats', 0)}   Q: {gps_data.get('quality', '?')}",
        f"  HDOP: {hdop_s}  VDOP: {vdop_s}",
        f"  Spd:  {spd_s}   Crs: {crs_s}",
        f"  NMEA: {gps_data.get('sentences', 0)} sentences",
    ]

    for line in lines:
        if row >= rows:
            break
        try:
            win.addstr(row, 0, line[:cols])
        except curses.error:
            pass
        row += 1

    return row


def draw_logs(win, row, rows, cols, gps_log, app_log):
    """Draw log sections filling remaining space. GPS log gets up to 5 rows, app log gets the rest."""
    if row >= rows:
        return

    remaining = rows - row
    line_w = cols
    if line_w < 1:
        return

    # GPS log: header + up to 5 entries
    if remaining < 3:
        return
    win.addstr(row, 0, "GPS LOG", curses.color_pair(5) | curses.A_BOLD)
    row += 1
    gps_lines = min(len(gps_log), 5, rows - row - 3)  # reserve space for APP LOG header + 2 lines
    for i in range(gps_lines):
        try:
            win.addstr(row, 0, list(gps_log)[i][:cols], curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # App log: header + fill remaining rows
    if row >= rows - 1:
        return
    row += 1  # blank separator
    win.addstr(row, 0, "APP LOG", curses.color_pair(3) | curses.A_BOLD)
    row += 1

    avail = rows - row
    if avail < 1:
        return

    # Build wrapped lines from app_log, show most recent that fit
    wrapped = []
    for entry in app_log:
        for off in range(0, len(entry), line_w):
            wrapped.append(entry[off:off + line_w])

    # Show tail of wrapped lines
    visible = wrapped[-avail:] if len(wrapped) > avail else wrapped
    for line in visible:
        if row >= rows:
            break
        try:
            win.addstr(row, 0, line, curses.A_DIM)
        except curses.error:
            pass
        row += 1


def run(gps, imu, state_mgr, stop_event):
    """Run curses debug UI using shared hardware and state.

    Args:
        gps: GPS reader (shared with daemon).
        imu: IMU reader (shared with daemon).
        state_mgr: StateManager (shared with daemon).
        stop_event: threading.Event -- set on quit to signal daemon shutdown.
    """
    imu_name = type(imu).__name__
    gps_name = type(gps).__name__

    def _main(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(int(1000 / REFRESH_HZ))

        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        curses.init_pair(3, curses.COLOR_CYAN, -1)
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)
        curses.init_pair(5, curses.COLOR_YELLOW, -1)

        imu_data = None
        gps_data = None
        frame_count = 0

        while not stop_event.is_set():
            key = stdscr.getch()
            if key == ord('q') or key == 27:
                stop_event.set()
                break

            # Read hardware (non-fatal)
            try:
                imu_data = imu.read()
            except Exception as e:
                log.warning("IMU read: %s", e)
            try:
                gps_data = gps.read()
            except Exception as e:
                log.warning("GPS read: %s", e)

            # Draw
            stdscr.erase()
            rows, cols = stdscr.getmaxyx()
            frame_count += 1

            bar_w = min(BAR_WIDTH, cols - 25)
            if bar_w < 10:
                bar_w = 10

            # Row 0: header
            # Row 1: keybinds
            # Row 2: state bar
            # Row 3+: sections flow downward
            row = 0

            try:
                stdscr.addstr(row, 0,
                    f"SDR Client Debug UI   frame:{frame_count}  IMU:{imu_name}  GPS:{gps_name}",
                    curses.color_pair(5) | curses.A_BOLD)
                row += 1
                stdscr.addstr(row, 0, "q/ESC: quit", curses.A_DIM)
                row += 1
                draw_state_bar(stdscr, row, 0, state_mgr.state, cols)
                row += 1
            except curses.error:
                pass

            # IMU section
            try:
                row = draw_imu(stdscr, row, rows, cols, imu_data, bar_w)
            except curses.error:
                pass
            except Exception as e:
                log.warning("IMU draw: %s", e)

            # Blank separator + GPS section
            row += 1
            try:
                row = draw_gps(stdscr, row, rows, cols, gps_data)
            except curses.error:
                pass
            except Exception as e:
                log.warning("GPS draw: %s", e)

            # Blank separator + Logs fill remaining space
            row += 1
            try:
                draw_logs(stdscr, row, rows, cols, gps.gps_log, gps.app_log)
            except Exception:
                pass

            stdscr.refresh()

    curses.wrapper(_main)
