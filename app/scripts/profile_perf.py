#!/usr/bin/env python3
"""
Performance profiling script for satellite calculations.
Profiles propagate_batch, find_visible_now, and find_passes.

Usage:
    python scripts/profile_perf.py [--sats N] [--hours H] [--lat LAT] [--lon LON]

Example:
    python scripts/profile_perf.py --sats 1000 --hours 24 --lat 37.7749 --lon -122.4194
"""

import sys
import os
import argparse
import cProfile
import pstats
import time
from datetime import datetime, timezone
from io import StringIO

# Add app to path (script lives in app/scripts/, so parent is app/)
script_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.dirname(script_dir)  # app/scripts -> app/
sys.path.insert(0, app_dir)

from satellite.propagator import propagate_batch, omm_to_satrec
from satellite.pass_prediction import find_visible_now, find_passes, predict_all_favorites


def load_satellites(max_count=None):
    """Load satellite data from data directory (handles subdirectories)."""
    import json
    from pathlib import Path

    data_dir = Path(app_dir) / "data"
    json_files = list(data_dir.rglob("*.json"))

    if not json_files:
        print(f"No satellite data found in {data_dir}")
        print("Run app/scripts/pull_data.sh to fetch data")
        sys.exit(1)

    print(f"Found {len(json_files)} JSON files")

    satellites = []
    for fp in json_files:
        try:
            with open(fp) as f:
                data = json.load(f)
            if isinstance(data, list):
                satellites.extend(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Skip {fp.name}: {e}")

    if max_count and len(satellites) > max_count:
        satellites = satellites[:max_count]

    print(f"Loaded {len(satellites)} satellites")
    return satellites


def profile_function(func, *args, label="function", **kwargs):
    """Profile a function and print stats."""
    profiler = cProfile.Profile()

    # Warmup
    try:
        func(*args, **kwargs)
    except Exception as e:
        print(f"Warmup failed: {e}")

    # Timed run
    start = time.perf_counter()
    profiler.enable()
    result = func(*args, **kwargs)
    profiler.disable()
    elapsed = time.perf_counter() - start

    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    print(f"Wall time: {elapsed*1000:.2f} ms")

    # Print stats
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats('cumtime')
    stats.print_stats(25)
    print(stream.getvalue())

    return result, elapsed


def profile_propagate_batch(satellites, dt):
    """Profile propagate_batch function."""
    return profile_function(
        propagate_batch,
        satellites, dt,
        label=f"propagate_batch ({len(satellites)} satellites)"
    )


def profile_find_visible_now(satellites, lat, lon):
    """Profile find_visible_now function."""
    return profile_function(
        find_visible_now,
        satellites, lat, lon, 0.0, None,
        label=f"find_visible_now ({len(satellites)} satellites)"
    )


def profile_find_passes(omm, lat, lon, hours):
    """Profile find_passes for single satellite."""
    name = omm.get('OBJECT_NAME', 'Unknown')
    return profile_function(
        find_passes,
        omm, lat, lon, 0.0, None, hours,
        label=f"find_passes ({name}, {hours}h window)"
    )


def profile_predict_all_favorites(favorites, satellites, lat, lon, hours):
    """Profile predict_all_favorites."""
    return profile_function(
        predict_all_favorites,
        favorites, satellites, lat, lon, 0.0, hours,
        label=f"predict_all_favorites ({len(favorites)} favorites, {hours}h)"
    )


def main():
    parser = argparse.ArgumentParser(description='Profile satellite calculations')
    parser.add_argument('--sats', type=int, default=None, help='Max satellites to load')
    parser.add_argument('--hours', type=int, default=24, help='Pass prediction window')
    parser.add_argument('--lat', type=float, default=37.7749, help='Observer latitude')
    parser.add_argument('--lon', type=float, default=-122.4194, help='Observer longitude')
    parser.add_argument('--skip-visible', action='store_true', help='Skip find_visible_now (slow)')
    args = parser.parse_args()

    print(f"Observer: {args.lat:.4f}, {args.lon:.4f}")
    print(f"Pass window: {args.hours}h")
    print()

    # Load data
    satellites = load_satellites(args.sats)
    dt = datetime.now(timezone.utc)

    results = {}

    # Profile propagate_batch
    _, elapsed = profile_propagate_batch(satellites, dt)
    results['propagate_batch'] = elapsed

    # Profile find_passes for first satellite
    if satellites:
        _, elapsed = profile_find_passes(satellites[0], args.lat, args.lon, args.hours)
        results['find_passes'] = elapsed

    # Profile find_visible_now (can be slow)
    if not args.skip_visible:
        _, elapsed = profile_find_visible_now(satellites, args.lat, args.lon)
        results['find_visible_now'] = elapsed

    # Profile predict_all_favorites with sample favorites
    if len(satellites) >= 5:
        favorites = [
            {'norad_id': s['NORAD_CAT_ID'], 'name': s.get('OBJECT_NAME', '')}
            for s in satellites[:5]
        ]
        _, elapsed = profile_predict_all_favorites(
            favorites, satellites, args.lat, args.lon, args.hours
        )
        results['predict_all_favorites'] = elapsed

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, elapsed in results.items():
        print(f"{name:30s}: {elapsed*1000:10.2f} ms")


if __name__ == '__main__':
    main()
