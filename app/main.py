#!/usr/bin/env python3
"""
Interactive terminal globe viewer using Textual TUI framework.
Uses braille characters for high-resolution rendering.

Interactive controls:
  Arrow keys: Rotate globe
  +/=: Zoom in
  -: Zoom out
  o: Options menu (LOD, Rivers, Cities detail)
  s: Satellites menu (load/manage satellite categories)
  g: Toggle GPS stats popup
  t: Toggle time popup
  d: Toggle debug timing overlay
  /: Search satellites
  r: Reset view
  q: Quit
"""

import logging
import sys
import argparse

from data_loader import load_shapefile, load_rivers, load_cities, load_shapefile_coarse
from globe_app import GlobeApp


def _start_mqtt(mqtt_cfg, antenna_manager):
    """Start embedded mosquitto broker and server MQTT client."""
    from server.broker import MosquittoBroker
    from server.mqtt_client import ServerMQTTClient

    host = mqtt_cfg.get("host", "0.0.0.0")
    port = mqtt_cfg.get("port", 1883)
    username = mqtt_cfg.get("username", "")
    password = mqtt_cfg.get("password", "")

    broker = MosquittoBroker(host=host, port=port,
                             username=username, password=password)
    broker.start()

    # Connect to broker on the same host it's bound to.
    # 0.0.0.0 means all interfaces -- use localhost in that case.
    client_host = "127.0.0.1" if host == "0.0.0.0" else host
    mqtt_client = ServerMQTTClient(
        antenna_manager,
        host=client_host, port=port,
        username=username, password=password,
    )
    mqtt_client.start()
    antenna_manager.set_mqtt_client(mqtt_client)

    return broker, mqtt_client


def main():
    parser = argparse.ArgumentParser(description='Interactive 3D globe renderer')
    parser.add_argument('shapefile', nargs='?', default='files/ne_50m_admin_0_countries.shp')
    parser.add_argument('--sat-framerate', type=int, default=1,
                        help='Satellite render framerate (default: 1 per second)')
    parser.add_argument('--server', action='store_true',
                        help='Enable antenna server (MQTT broker + client manager)')

    args = parser.parse_args()

    def status(msg):
        sys.stdout.write(f'\r{msg}')
        sys.stdout.flush()

    # Start antenna server if requested
    antenna_manager = None
    broker = None
    mqtt_client = None
    if args.server:
        from config_manager import config
        from server.antenna_manager import AntennaManager

        mqtt_cfg = config.mqtt
        antenna_manager = AntennaManager()
        broker, mqtt_client = _start_mqtt(mqtt_cfg, antenna_manager)
        status(f'MQTT broker started on port {mqtt_cfg["port"]}...\n')

    status('Loading 50m map...')
    segments, segment_bounds, flat_data = load_shapefile(args.shapefile)

    status('Loading 110m map...')
    segments_coarse, segment_bounds_coarse, flat_data_coarse = load_shapefile_coarse('files/ne_110m_admin_0_countries.shp')

    status('Loading rivers...')
    river_segments, river_bounds, river_flat_data = load_rivers('files/ne_50m_rivers_lake_centerlines.shp')

    status('Loading cities...')
    city_coords, city_names = load_cities('files/ne_50m_populated_places.shp')

    status('Starting UI...        \n')

    app = GlobeApp(
        segments=segments,
        segment_bounds=segment_bounds,
        river_segments=river_segments,
        river_bounds=river_bounds,
        city_coords=city_coords,
        city_names=city_names,
        segments_coarse=segments_coarse,
        segment_bounds_coarse=segment_bounds_coarse,
        satellite_framerate=args.sat_framerate,
        antenna_manager=antenna_manager,
    )

    app.run()

    if mqtt_client:
        mqtt_client.stop()
    if broker:
        broker.stop()


if __name__ == '__main__':
    main()
