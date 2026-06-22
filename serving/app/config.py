"""12-factor settings for the Harbormaster serving plane. Read once, immutable.

Env prefix is HM_ (Harbormaster). The kinematic constant mirrors GeoTrace's
GT_VESSEL_V_MAX_KTS=25 and the HITL threshold mirrors GT_HITL_CONFIDENCE_THRESHOLD=0.7
(the reuse anchors in docs/phases/PHASE_1.md); only the env prefix differs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HM_", extra="ignore")

    env: Literal["dev", "staging", "prod"] = "dev"
    version: str = "0.1.0"

    # storage (HITL queue). Empty/unreachable -> the in-memory HITL backend.
    pg_dsn: str = ""

    # kinematics (hard physical bounds). vessel_v_max_kts * 0.514444 = 12.861 m/s.
    vessel_v_max_kts: float = Field(25.0, gt=0)
    vehicle_v_max_kmh: float = Field(130.0, gt=0)

    # scoring / HITL routing
    hitl_confidence_threshold: float = Field(0.7, ge=0, le=1)
    anomaly_hitl_threshold: float = Field(0.6, ge=0, le=1)

    # gap detection
    coverage_threshold_s: float = Field(600.0, gt=0)  # > 10 min between fixes is a gap
    gap_saturation_s: float = Field(7200.0, gt=0)  # >= 2 h silence saturates severity

    # speed scoring vs corrupt-data rejection. A vessel doing several x v_max is a
    # scored anomaly (spoofing / GPS error); a teleport beyond corrupt_reject_factor
    # x v_max is non-physical sensor corruption and is rejected (422), not scored.
    speed_saturation_mult: float = Field(3.0, gt=0)  # v_req = 4x v_max -> severity 1
    corrupt_reject_factor: float = Field(12.0, gt=1)

    # corridor (GTRA static sea-lane graph)
    corridor_artifact_path: str = "app/artifacts/corridors.json"
    off_corridor_threshold_m: float = Field(2_000.0, gt=0)
    corridor_saturation_m: float = Field(6_000.0, gt=0)  # deviation that saturates severity
    unexpected_node_heading_deg: float = Field(45.0, gt=0)
    # a course change within this distance of a node is expected, not anomalous
    waypoint_radius_m: float = Field(5_000.0, gt=0)

    @property
    def vessel_v_max_mps(self) -> float:
        return self.vessel_v_max_kts * 0.514_444


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
