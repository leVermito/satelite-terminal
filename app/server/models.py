"""Pydantic models for server-side client state."""

from typing import Optional
from pydantic import BaseModel


class GPSData(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0
    satellites: int = 0
    hdop: float = 0.0


class TrackingInfo(BaseModel):
    active: bool = False
    norad_id: Optional[int] = None
    name: Optional[str] = None


class ClientStateInfo(BaseModel):
    state: str = "unknown"
    state_since: float = 0.0
    error_detail: str = ""


class ClientGPSInfo(BaseModel):
    fix: bool = False
    satellites: int = 0
    hdop: Optional[float] = None


class ClientIMUInfo(BaseModel):
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


class ClientState(BaseModel):
    client_id: str
    hostname: str
    capabilities: list[str] = []
    status: str = "initializing"
    gps: Optional[GPSData] = None
    imu_calibrated: bool = False
    tracking: Optional[TrackingInfo] = None
    uptime_s: float = 0.0
    client_state_info: Optional[ClientStateInfo] = None
    client_gps_info: Optional[ClientGPSInfo] = None
    client_imu_info: Optional[ClientIMUInfo] = None
    last_full_status: Optional[dict] = None
    tracking_az: float = 0.0
    tracking_el: float = 0.0


class ClientSummary(BaseModel):
    client_id: str
    hostname: str
    status: str
    gps: Optional[GPSData] = None
    tracking: Optional[TrackingInfo] = None
    client_state_info: Optional[ClientStateInfo] = None
    client_gps_info: Optional[ClientGPSInfo] = None
    client_imu_info: Optional[ClientIMUInfo] = None
