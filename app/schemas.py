"""请求 / 响应模型。只描述接口形状，不含任何计算。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PointRequest(BaseModel):
    profile: str | None = Field(default=None, description="命名动校档；给了档名就不要再内联 t0/velocity")
    t0: float | None = Field(default=None, description="零偏移距双程走时（秒）")
    velocity: float | None = Field(default=None, description="叠加速度（与炮检距同量纲体系，如 m/s）")
    offset: float = Field(description="炮检距，正负均可")
    stretch_threshold: float = Field(default=0.10, description="拉伸告警阈值 Δt/t0")


class CurveRequest(BaseModel):
    profile: str | None = None
    t0: float | None = None
    velocity: float | None = None
    offsets: list[float] = Field(description="炮检距网格，必须非空且严格递增")
    stretch_threshold: float = Field(default=0.10)


class ScanRequest(BaseModel):
    profile: str | None = Field(
        default=None,
        description="命名动校档：以档内 (t0, velocity) 定义被扫描的同相轴",
    )
    offsets: list[float] = Field(description="炮检距网格，必须非空、严格递增且首端为 0")
    velocities: list[float] = Field(description="候选叠加速度列表，必须非空、逐项为正")
    t0: float | None = Field(default=None, description="内联事件的零偏移距双程走时")
    event_velocity: float | None = Field(
        default=None,
        description="内联事件的真实速度：用它合成观测走时，再在候选速度里找最平的",
    )
    observed_times: list[float] | None = Field(
        default=None,
        description="直接给观测走时（首道须为零偏移道）；与 event_velocity 二选一",
    )


class PointResponse(BaseModel):
    t0: float
    velocity: float
    offset: float
    traveltime: float
    moveout: float
    stretch_ratio: float | None
    stretch_threshold: float
    stretched: bool


class CurveResponse(BaseModel):
    t0: float
    velocity: float
    stretch_threshold: float
    offsets: list[float]
    traveltimes: list[float]
    moveouts: list[float]
    stretch_ratios: list[float | None]
    stretched: list[bool]


class ScanCandidateResponse(BaseModel):
    velocity: float
    corrected_times: list[float]
    flatness: float
    max_abs_deviation: float


class ScanResponse(BaseModel):
    t0: float
    offsets: list[float]
    observed_times: list[float]
    candidates: list[ScanCandidateResponse]
    best_velocity: float
    best_flatness: float
    best_index: int


class ProfileBody(BaseModel):
    t0: float
    velocity: float


class ProfileResponse(BaseModel):
    name: str
    t0: float
    velocity: float


class ProfileListResponse(BaseModel):
    profiles: list[ProfileResponse]


class ErrorResponse(BaseModel):
    error: bool = True
    reason: str
