#!/usr/bin/env python3
"""
GPS Reader for Raspberry Pi 3A with G28U7FTTL GPS Module
Iteration 1: Display geolocation information using Textual TUI

Hardware Connections:
- VDD (GPS) → 5V (Pin 2 or 4)
- GND (GPS) → Ground (Pin 6)
- TXD (GPS) → RXD/GPIO 16 (Pin 10) - GPS transmits to Pi receives
- RXD (GPS) → TXD/GPIO 15 (Pin 8) - GPS receives from Pi transmits
- EN (GPS) → 3.3V (Pin 1) or leave floating (module has internal pull-up)
- PPS (GPS) → Optional, not used in this iteration


Prerequisites:
1. Disable serial console: sudo raspi-config → Interface Options → Serial Port
   - "Would you like a login shell accessible over serial?" → No
   - "Would you like the serial port hardware enabled?" → Yes
2. Install required packages:
   - sudo apt-get update
   - sudo apt-get install python3-serial
   - pip3 install pynmea2 textual
3. Configure serial port:
   - sudo stty -F /dev/serial0 9600
   - sudo stty -F /dev/serial0 -echo
"""

import serial
import pynmea2
import sys
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Static, Label
from rich.text import Text
from textual.reactive import reactive
from threading import Thread, Event
import time

# Configuration
SERIAL_PORT = '/dev/serial0'
BAUD_RATE = 9600
TIMEOUT = 1


class GPSInfoBox(Static):
    """Display all GPS information in a bordered box with alternating row colors"""
    
    status = reactive("WAITING")
    last_sentence = reactive("")
    sentence_count = reactive(0)
    fix = reactive(False)
    quality = reactive("No Fix")
    satellites = reactive(0)
    latitude = reactive(0.0)
    longitude = reactive(0.0)
    lat_dir = reactive("N")
    lon_dir = reactive("E")
    altitude = reactive(0.0)
    hdop = reactive(None)
    speed = reactive(None)
    course = reactive(None)
    
    def compose(self) -> ComposeResult:
        yield Label("", id="line1", classes="row-light")
        yield Label("", id="line2", classes="row-dark")
        yield Label("", id="line3", classes="row-light")
    
    def format_coordinate(self, degrees: float, direction: str) -> str:
        return f"{abs(degrees):.6f}°{direction}"
    
    def on_mount(self):
        self.update_display()
    
    def watch_status(self, status: str):
        self.update_display()
    
    def watch_fix(self, has_fix: bool):
        self.update_display()
    
    def watch_satellites(self, count: int):
        self.update_display()
    
    def watch_latitude(self, lat: float):
        self.update_display()
    
    def watch_longitude(self, lon: float):
        self.update_display()
    
    def watch_altitude(self, alt: float):
        self.update_display()
    
    def watch_sentence_count(self, count: int):
        self.update_display()
    
    def update_display(self):
        try:
            # Column widths - based on coordinate values being widest
            # Lat: 54.373625°N = 12 chars, Lon: 18.563249°E = 12 chars
            col1_w = 20  # First column (title + value)
            col2_w = 20  # Second column (title + value)
            col3_w = 12  # Third column value width
            
            rx_val = str(self.sentence_count) if self.status == "RECEIVING" else "--"
            
            # Lock status with color
            if self.fix:
                lock_val = "Locked"
                lock_color = "green"
            else:
                lock_val = "Searching"
                lock_color = "yellow"
            
            # Satellites with color: green >=6, yellow 4-5, red <4
            sats_val = str(self.satellites)
            if self.satellites >= 6:
                sats_color = "green"
            elif self.satellites >= 4:
                sats_color = "yellow"
            else:
                sats_color = "red"
            
            # HDOP color coding: green <5, yellow 5-15, red >15
            if self.hdop:
                hdop_num = f"{self.hdop:.1f}"
                if self.hdop < 5:
                    hdop_color = "green"
                elif self.hdop < 15:
                    hdop_color = "yellow"
                else:
                    hdop_color = "red"
            else:
                hdop_num = "--"
                hdop_color = "white"
            
            speed_val = f"{self.speed:.1f} km/h" if self.speed else "-- km/h"
            course_val = f"{self.course:.0f}°" if self.course else "--°"
            
            lat_val = self.format_coordinate(self.latitude, self.lat_dir) if self.fix else "--"
            lon_val = self.format_coordinate(self.longitude, self.lon_dir) if self.fix else "--"
            alt_val = f"{self.altitude:.1f}m" if self.fix else "--"
            
            # Line 1: RX, Lock (colored), Sats (colored)
            line1_text = Text()
            line1_text.append(f"RX:    {rx_val:<{col1_w - 7}}")
            line1_text.append("Lock:  ")
            line1_text.append(f"{lock_val:<{col2_w - 7}}", style=lock_color)
            line1_text.append("Sats:   ")
            line1_text.append(f"{sats_val:<{col3_w - 8}}", style=sats_color)
            # Line 2: HDOP (colored), Speed, Course
            line2_text = Text()
            line2_text.append("HDOP:  ")
            line2_text.append(f"{hdop_num:<{col1_w - 7}}", style=hdop_color)
            line2_text.append(f"Speed: {speed_val:<{col2_w - 7}}Course: {course_val:<{col3_w - 8}}")
            # Line 3: Lat, Lon, Alt
            line3 = f"Lat:   {lat_val:<{col1_w - 7}}Lon:   {lon_val:<{col2_w - 7}}Alt:    {alt_val:<{col3_w - 8}}"
            
            self.query_one("#line1", Label).update(line1_text)
            self.query_one("#line2", Label).update(line2_text)
            self.query_one("#line3", Label).update(line3)
        except:
            pass




class GPSReaderApp(App):
    """Textual TUI application for GPS reader"""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    GPSInfoBox {
        height: auto;
        border: solid white;
        border-title-color: white;
        border-title-style: bold;
        margin: 0;
        padding: 0;
    }
    
    .row-light {
        background: #3a3a3a;
        margin: 0;
        padding: 0 1;
    }
    
    .row-dark {
        background: #2a2a2a;
        margin: 0;
        padding: 0 1;
    }
    
    Label {
        margin: 0;
        padding: 0;
    }
    """
    
    TITLE = "GPS - Pi 3A + G28U7FTTL"
    BINDINGS = [
        ("q", "quit", "Quit"),
    ]
    
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.stop_event = Event()
        self.reader_thread = None
        
        self.current_data = {
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
            'last_sentence': '',
            'sentence_count': 0
        }
    
    def compose(self) -> ComposeResult:
        """Create child widgets for the app"""
        gps_box = GPSInfoBox()
        gps_box.border_title = "SDR GPS Test"
        yield gps_box
    
    def on_mount(self) -> None:
        """Initialize GPS reader when app starts"""
        self.set_interval(1.0, self.update_display)
        self.reader_thread = Thread(target=self.gps_reader_loop, daemon=True)
        self.reader_thread.start()
    
    def update_display(self) -> None:
        """Update all display panels"""
        panel = self.query_one(GPSInfoBox)
        if self.current_data['last_sentence']:
            panel.status = "RECEIVING"
        panel.sentence_count = self.current_data['sentence_count']
        panel.fix = self.current_data['fix']
        panel.quality = self.current_data['quality']
        panel.satellites = self.current_data['satellites']
        panel.latitude = self.current_data['latitude']
        panel.longitude = self.current_data['longitude']
        panel.lat_dir = self.current_data['lat_dir']
        panel.lon_dir = self.current_data['lon_dir']
        panel.altitude = self.current_data['altitude']
        panel.hdop = self.current_data['hdop']
        panel.speed = self.current_data['speed']
        panel.course = self.current_data['course']
    
    def gps_reader_loop(self) -> None:
        """Background thread for reading GPS data"""
        try:
            self.serial_port = serial.Serial(
                port=SERIAL_PORT,
                baudrate=BAUD_RATE,
                timeout=TIMEOUT,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            
            while not self.stop_event.is_set():
                try:
                    line = self.serial_port.readline().decode('ascii', errors='ignore').strip()
                    
                    if line.startswith('$'):
                        self.current_data['last_sentence'] = line
                        self.current_data['sentence_count'] += 1
                        
                        if 'GGA' in line:
                            parsed_data = self.parse_gga(line)
                            self.current_data.update(parsed_data)
                            self.current_data['last_sentence'] = line
                        
                        elif 'RMC' in line:
                            self.parse_rmc(line)
                            
                except UnicodeDecodeError:
                    continue
                    
        except serial.SerialException as e:
            self.notify(f"Serial port error: {e}", severity="error", timeout=10)
        except Exception as e:
            self.notify(f"Unexpected error: {e}", severity="error", timeout=10)
    
    def parse_gga(self, sentence: str) -> dict:
        """Parse GGA sentence for position data"""
        data = {
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
            'course': None
        }
        
        try:
            msg = pynmea2.parse(sentence)
            
            if msg.gps_qual and int(msg.gps_qual) > 0:
                data['fix'] = True
                data['latitude'] = msg.latitude
                data['longitude'] = msg.longitude
                data['lat_dir'] = msg.lat_dir
                data['lon_dir'] = msg.lon_dir
                data['altitude'] = float(msg.altitude) if msg.altitude else 0.0
                data['satellites'] = int(msg.num_sats) if msg.num_sats else 0
                data['hdop'] = float(msg.horizontal_dil) if msg.horizontal_dil else None
                
                quality_map = {
                    '0': 'No Fix',
                    '1': 'GPS Fix',
                    '2': 'DGPS Fix',
                    '3': 'PPS Fix',
                    '4': 'RTK Fix',
                    '5': 'Float RTK',
                    '6': 'Estimated',
                    '7': 'Manual',
                    '8': 'Simulation'
                }
                data['quality'] = quality_map.get(msg.gps_qual, 'Unknown')
            else:
                data['satellites'] = int(msg.num_sats) if msg.num_sats else 0
                
        except (pynmea2.ParseError, AttributeError):
            pass
        
        return data
    
    def parse_rmc(self, sentence: str) -> None:
        """Parse RMC sentence for speed and course data"""
        try:
            msg = pynmea2.parse(sentence)
            
            if msg.spd_over_grnd:
                self.current_data['speed'] = float(msg.spd_over_grnd) * 1.852
            
            if msg.true_course:
                self.current_data['course'] = float(msg.true_course)
                
        except (pynmea2.ParseError, AttributeError):
            pass
    
    def action_quit(self) -> None:
        """Quit the application"""
        self.stop_event.set()
        if self.serial_port:
            self.serial_port.close()
        self.exit()


def main():
    """Main entry point"""
    app = GPSReaderApp()
    app.run()


if __name__ == "__main__":
    main()
