"""路由层：只解析请求、组织三个接口的返回，不含动校正公式实现。

接口：
- POST /nmo/point   某炮检距处的双曲线走时、校正量与拉伸标记
- POST /nmo/curve   炮检距网格上的整条双曲线走时曲线
- POST /nmo/scan    候选叠加速度扫描，给出把同相轴校得最平的速度
另附运行期内存动校档的增删查（重启即丢）。
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Request

from . import curve, scan, stretch, validation
from .errors import NmoError
from .schemas import (
    CurveRequest,
    CurveResponse,
    PointRequest,
    PointResponse,
    ProfileBody,
    ProfileListResponse,
    ProfileResponse,
    ScanRequest,
    ScanResponse,
)

router = APIRouter()


def _store(request: Request):
    return request.app.state.profile_store


def _resolve_t0_velocity(request: Request, profile_name: str | None,
                         t0: float | None, velocity: float | None) -> tuple[float, float]:
    """档名 / 内联两种取参方式，禁止混用，避免一处一套速度。"""
    if profile_name is not None:
        validation.validate_no_profile_inline_mix(profile_name, t0, velocity)
        profile = _store(request).get(profile_name)
        return profile.t0, profile.velocity
    if t0 is None or velocity is None:
        raise NmoError("必须提供 t0 和 velocity，或通过 profile 指定命名动校档")
    return validation.validate_t0(t0), validation.validate_velocity(velocity)


@router.post("/nmo/point", response_model=PointResponse)
def nmo_point(payload: PointRequest, request: Request) -> PointResponse:
    t0, velocity = _resolve_t0_velocity(
        request, payload.profile, payload.t0, payload.velocity
    )
    offset = validation.validate_offset(payload.offset)
    threshold = validation.validate_stretch_threshold(payload.stretch_threshold)

    result = stretch.evaluate_with_traveltime(t0, velocity, offset, threshold)
    ratio = result["stretch_ratio"]
    return PointResponse(
        t0=t0,
        velocity=velocity,
        offset=offset,
        traveltime=result["traveltime"],
        moveout=result["moveout"],
        stretch_ratio=None if math.isinf(ratio) else ratio,
        stretch_threshold=threshold,
        stretched=result["stretched"],
    )


@router.post("/nmo/curve", response_model=CurveResponse)
def nmo_curve(payload: CurveRequest, request: Request) -> CurveResponse:
    t0, velocity = _resolve_t0_velocity(
        request, payload.profile, payload.t0, payload.velocity
    )
    return CurveResponse(
        **curve.build_curve(t0, velocity, payload.offsets, payload.stretch_threshold)
    )


@router.post("/nmo/scan", response_model=ScanResponse)
def nmo_scan(payload: ScanRequest, request: Request) -> ScanResponse:
    if payload.profile is not None:
        # 以档内 (t0, velocity) 定义被扫描同相轴；内联事件参数一律不许混入，
        # 避免“一处用档内速度、一处用内联速度”。
        if (
            payload.t0 is not None
            or payload.event_velocity is not None
            or payload.observed_times is not None
        ):
            raise NmoError(
                "指定动校档 profile 做速度扫描时，t0、event_velocity、observed_times 必须留空"
            )
        profile = _store(request).get(payload.profile)
        result = scan.scan_velocities(
            offsets=payload.offsets,
            candidate_velocities=payload.velocities,
            t0=profile.t0,
            event_velocity=profile.velocity,
        )
    else:
        result = scan.scan_velocities(
            offsets=payload.offsets,
            candidate_velocities=payload.velocities,
            t0=payload.t0,
            event_velocity=payload.event_velocity,
            observed_times=payload.observed_times,
        )
    return ScanResponse(
        t0=result.t0,
        offsets=result.offsets,
        observed_times=result.observed_times,
        candidates=[
            {
                "velocity": c.velocity,
                "corrected_times": c.corrected_times,
                "flatness": c.flatness,
                "max_abs_deviation": c.max_abs_deviation,
            }
            for c in result.candidates
        ],
        best_velocity=result.best_velocity,
        best_flatness=result.best_flatness,
        best_index=result.best_index,
    )


@router.put("/profiles/{name}", response_model=ProfileResponse)
def put_profile(name: str, payload: ProfileBody, request: Request) -> ProfileResponse:
    profile = _store(request).put(name, payload.t0, payload.velocity)
    return ProfileResponse(name=profile.name, t0=profile.t0, velocity=profile.velocity)


@router.get("/profiles", response_model=ProfileListResponse)
def list_profiles(request: Request) -> ProfileListResponse:
    profiles = _store(request).list()
    return ProfileListResponse(
        profiles=[
            ProfileResponse(name=p.name, t0=p.t0, velocity=p.velocity) for p in profiles
        ]
    )


@router.get("/profiles/{name}", response_model=ProfileResponse)
def get_profile(name: str, request: Request) -> ProfileResponse:
    profile = _store(request).get(name)
    return ProfileResponse(name=profile.name, t0=profile.t0, velocity=profile.velocity)


@router.delete("/profiles/{name}")
def delete_profile(name: str, request: Request) -> dict[str, bool]:
    _store(request).delete(name)
    return {"deleted": True}
