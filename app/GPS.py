"""
GPS module for reading coordinates from GPS dongle.
Returns position data for rendering on globe.
Falls back gracefully when GPS hardware is unavailable.
"""

import socket
from collections import deque

# Configuration
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 9600
TIMEOUT = 1

# GPS availability flag
_gps_available = None
_serial_port = None
_current_data = {
    'fix': False,
    'latitude': 0.0,
    'longitude': 0.0,
    'lat_dir': 'N',
    'lon_dir': 'E',
    'altitude': 0.0,
    'satellites': 0,
    'quality': 'No Fix',
    'hdop': None,
    'speed': None,
    'course': None,
    'sentence_count': 0,
    'satellite_ids': set(),
}
_recent_sentences = deque(maxlen=3)


def get_hostname():
    """Get system hostname for display label."""
    try:
        return socket.gethostname()
    except:
        return "unknown"


def _check_gps_available():
    """Check if GPS hardware is available."""
    global _gps_available, _serial_port
    
    if _gps_available is not None:
        return _gps_available
    
    try:
        import serial
        _serial_port = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            timeout=TIMEOUT,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE
        )
        _gps_available = True
    except ImportError:
        _gps_available = False
    except Exception:
        _gps_available = False
    
    return _gps_available


def _parse_gga(sentence):
    """Parse GGA sentence for position data."""
    global _current_data
    try:
        import pynmea2
        msg = pynmea2.parse(sentence)
        
        if msg.gps_qual and int(msg.gps_qual) > 0:
            quality_map = {
                '0': 'No Fix', '1': 'GPS Fix', '2': 'DGPS Fix',
                '3': 'PPS Fix', '4': 'RTK Fix', '5': 'Float RTK',
                '6': 'Estimated', '7': 'Manual', '8': 'Simulation'
            }
            _current_data.update({
                'fix': True,
                'latitude': msg.latitude,
                'longitude': msg.longitude,
                'lat_dir': msg.lat_dir,
                'lon_dir': msg.lon_dir,
                'altitude': float(msg.altitude) if msg.altitude else 0.0,
                'satellites': int(msg.num_sats) if msg.num_sats else 0,
                'hdop': float(msg.horizontal_dil) if msg.horizontal_dil else None,
                'quality': quality_map.get(msg.gps_qual, 'Unknown'),
            })
            return True
        else:
            _current_data['satellites'] = int(msg.num_sats) if msg.num_sats else 0
    except:
        pass
    
    return False


def _parse_rmc(sentence):
    """Parse RMC sentence for speed and course data."""
    global _current_data
    try:
        import pynmea2
        msg = pynmea2.parse(sentence)
        
        if msg.spd_over_grnd:
            _current_data['speed'] = float(msg.spd_over_grnd) * 1.852
        if msg.true_course:
            _current_data['course'] = float(msg.true_course)
    except:
        pass


def _parse_gsv(sentence):
    """Parse GSV sentence for satellites-in-view IDs."""
    global _current_data
    try:
        import pynmea2
        msg = pynmea2.parse(sentence)
        ids = []
        for i in range(1, 5):
            val = getattr(msg, f"sv_prn_num_{i}", None)
            if val:
                try:
                    ids.append(int(val))
                except:
                    pass
        if ids:
            _current_data['satellite_ids'].update(ids)
    except:
        pass


def _parse_gsa(sentence):
    """Parse GSA sentence for satellites used in fix."""
    global _current_data
    try:
        import pynmea2
        msg = pynmea2.parse(sentence)
        ids = []
        for field in getattr(msg, "sv_ids", []) or []:
            if field:
                try:
                    ids.append(int(field))
                except:
                    pass
        if ids:
            _current_data['satellite_ids'].update(ids)
    except:
        pass


def _read_gps_data():
    """Read and parse GPS data from serial port."""
    global _serial_port, _current_data
    
    if not _serial_port:
        return False
    
    try:
        line = _serial_port.readline().decode('ascii', errors='ignore').strip()
        
        if line.startswith('$'):
            _current_data['sentence_count'] += 1
            _recent_sentences.append(line)
            if 'GGA' in line:
                return _parse_gga(line)
            elif 'RMC' in line:
                _parse_rmc(line)
            elif 'GSV' in line:
                _parse_gsv(line)
            elif 'GSA' in line:
                _parse_gsa(line)
    except:
        pass
    
    return False


def get_gps_position():
    """
    Get current GPS position.
    
    Returns:
        tuple: (success, latitude, longitude, hostname) or (False, None, None, None)
    """
    if not _check_gps_available():
        return (False, None, None, None)
    
    _read_gps_data()
    
    if _current_data['fix']:
        return (
            True,
            _current_data['latitude'],
            _current_data['longitude'],
            get_hostname()
        )
    
    return (False, None, None, None)


def has_gps_fix():
    """Check if GPS has a valid fix."""
    if not _check_gps_available():
        return False
    
    _read_gps_data()
    return _current_data['fix']


def is_gps_available():
    """Check if GPS hardware is available (not necessarily with fix)."""
    return _check_gps_available()



def close_gps():
    """Close GPS serial connection."""
    global _serial_port, _gps_available
    
    if _serial_port:
        try:
            _serial_port.close()
        except:
            pass
        _serial_port = None
    
    _gps_available = None
