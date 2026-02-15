#!/bin/bash

# Satellite data download script
# Downloads TLE data in OMM JSON format from CelesTrak

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
DATA_DIR="$PROJECT_ROOT/app/data"
BACKUP_DIR="$DATA_DIR/backup"

# Create directories if they don't exist
mkdir -p "$DATA_DIR"
mkdir -p "$BACKUP_DIR"

# Empty backup directory
echo "Clearing backup directory..."
rm -rf "$BACKUP_DIR"/*

# Move existing data files to backup
echo "Moving existing data to backup..."
find "$DATA_DIR" -maxdepth 1 -name "*.json" -exec mv {} "$BACKUP_DIR"/ \; 2>/dev/null || true
for subdir in "$DATA_DIR"/*/; do
  [ -d "$subdir" ] && [ "$(basename "$subdir")" != "backup" ] && mv "$subdir" "$BACKUP_DIR"/ 2>/dev/null || true
done

# Function to download satellite data
# Args: $1=group_name, $2=output_filename, $3=subdirectory (optional)
download_group() {
  local group="$1"
  local filename="$2"
  local subdir="$3"
  
  if [ -n "$subdir" ]; then
    mkdir -p "$DATA_DIR/$subdir"
    local output="$DATA_DIR/$subdir/${filename}_${TIMESTAMP}.json"
  else
    local output="$DATA_DIR/${filename}_${TIMESTAMP}.json"
  fi
  
  echo "Fetching $filename..."
  curl -s "https://celestrak.org/NORAD/elements/gp.php?GROUP=${group}&FORMAT=json" -o "$output"
  sleep 0.5
}

echo "Downloading satellite data..."

# =============================================================================
# SPECIAL-INTEREST SATELLITES
# =============================================================================
# download_group "last-30-days" "last-30-days-launches" "special-interest"
download_group "stations" "stations" "special-interest"
# Skipped: visual (100-brightest) - subset of active satellites filtered by brightness
# Skipped: active - aggregation of satellites from other categories
download_group "analyst" "analyst" "special-interest"
download_group "cosmos-1408-debris" "russian-asat-debris" "special-interest"
download_group "fengyun-1c-debris" "chinese-asat-debris" "special-interest"
download_group "iridium-33-debris" "iridium-33-debris" "special-interest"
download_group "cosmos-2251-debris" "cosmos-2251-debris" "special-interest"

# =============================================================================
# WEATHER & EARTH RESOURCES SATELLITES
# =============================================================================
# Skipped: weather - aggregation of noaa, goes, and other weather satellites
download_group "noaa" "noaa" "weather"
download_group "goes" "goes" "weather"
download_group "resource" "earth-resources" "weather"
download_group "sarsat" "sarsat" "weather"
download_group "dmc" "disaster-monitoring" "weather"
download_group "tdrss" "tdrss" "weather"
download_group "argos" "argos" "weather"
download_group "planet" "planet" "weather"
download_group "spire" "spire" "weather"

# =============================================================================
# COMMUNICATIONS SATELLITES
# =============================================================================
download_group "geo" "active-geosynchronous" "communications"
download_group "moving" "movers" "communications"
# Skipped: gpz (geo-protected-zone) - subset of gpz-plus
download_group "gpz-plus" "geo-protected-zone-plus" "communications"
download_group "intelsat" "intelsat" "communications"
download_group "ses" "ses" "communications"
download_group "eutelsat" "eutelsat" "communications"
download_group "telesat" "telesat" "communications"
download_group "starlink" "starlink" "communications"
download_group "oneweb" "oneweb" "communications"
download_group "qianfan" "qianfan" "communications"
download_group "hwdigui" "hulianwang-digui" "communications"
download_group "kuiper" "kuiper" "communications"
download_group "iridium-NEXT" "iridium-next" "communications"
download_group "orbcomm" "orbcomm" "communications"
download_group "globalstar" "globalstar" "communications"
download_group "amateur" "amateur" "communications"
download_group "satnogs" "satnogs" "communications"
download_group "x-comm" "experimental-comm" "communications"
download_group "other-comm" "other-comm" "communications"

# =============================================================================
# NAVIGATION SATELLITES
# =============================================================================
# Skipped: gnss - aggregation of gps-ops, glonass-ops, galileo, beidou
download_group "gps-ops" "gps-ops" "navigation"
download_group "glo-ops" "glonass-ops" "navigation"
download_group "galileo" "galileo" "navigation"
download_group "beidou" "beidou" "navigation"
download_group "sbas" "sbas" "navigation"
download_group "nnss" "nnss" "navigation"
download_group "musson" "russian-leo-navigation" "navigation"

# =============================================================================
# SCIENTIFIC SATELLITES
# =============================================================================
download_group "science" "space-earth-science" "scientific"
download_group "geodetic" "geodetic" "scientific"
download_group "engineering" "engineering" "scientific"
download_group "education" "education" "scientific"

# =============================================================================
# MISCELLANEOUS SATELLITES
# =============================================================================
download_group "military" "military" "miscellaneous"
download_group "radar" "radar-calibration" "miscellaneous"
download_group "cubesat" "cubesats" "miscellaneous"
download_group "other" "other" "miscellaneous"

echo "Download complete. Files saved to $DATA_DIR/"
echo "Timestamp: $TIMESTAMP"
