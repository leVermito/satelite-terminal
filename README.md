# SDR Globe Viewer

This project is a **proof of concept** for a terminal-based satellite tracking and antenna control system. It was built to explore the idea of rendering a 3D globe entirely with braille Unicode characters in the terminal, combined with real-time SGP4 orbital propagation and a distributed MQTT architecture for remote antenna pointing. Most of the hardware-specific code (motor drivers, GPIO wiring, sensor calibration) is not included, as it is heavily dependent on the specific antenna setup and there hasn't been time to generalize it beyond the POC stage.

## Features

- **Braille-rendered 3D globe** — orthographic projection of coastlines, rivers, and cities drawn using 2x4 braille pixel blocks
- **Real-time satellite tracking** — SGP4 propagation from OMM/TLE data across LEO, MEO, and GEO orbits with altitude-accurate rendering and Earth-obstruction culling
- **Interactive TUI panels** — satellite browser, location manager, favorites, pass predictions with countdown timers, antenna status monitor, time control, search, and configurable display options
- **Satellite focus mode** — camera auto-follows a selected satellite with full orbital path visualization and lockable/unlockable tracking
- **Pass prediction engine** — 24-hour rise/set calculations with max elevation and live countdowns for bookmarked satellites
- **MQTT server-client architecture** — desktop TUI acts as server with embedded broker; Raspberry Pi clients run local SGP4 for real-time antenna pointing independent of network connectivity
- **Hardware abstraction layer** — client supports GPS (serial UART / pigpio bit-bang), 6-axis IMU with Kalman filtering, and PWM motor control via pigpiod
- **Dynamic level of detail** — switches between 110m and 50m map resolution based on zoom, with frustum culling and static geometry caching
- **TOML configuration** — two-layer config (code defaults + user overrides) with hot-reload for display settings, satellite colors, locations, favorites, and MQTT broker settings
- **Data management** — CelesTrak and Space-Track.org sources with auto-backup, timestamped downloads, and batch loading of default satellite categories

## Some screenshots

<img width="1991" height="1041" alt="4" src="https://github.com/user-attachments/assets/b650c67f-1ff2-4bd0-a198-5ac32226b883" />
<img width="1991" height="1041" alt="3" src="https://github.com/user-attachments/assets/64c3e804-e0a0-49a4-b204-bb5d27f443b4" />
<img width="2002" height="1044" alt="2" src="https://github.com/user-attachments/assets/b3eb5307-6a93-4775-abbd-70bffda3d9dc" />
<img width="2002" height="1044" alt="1" src="https://github.com/user-attachments/assets/481141f1-a072-4995-b1d2-ee8a73da7da8" />
