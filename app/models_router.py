"""层状模型路由层：模型增删查、精确射线走时、从界面生动校档。

本层只做请求解析与返回组织；层状派生量在 ``layers`` 块，
斯奈尔射线追踪在 ``rays`` 块，这里不写任何公式。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from . import model_store, rays, validation
from .errors import NmoError
from .layers import LayeredModel
from .schemas import (
    ModelBody,
    ModelListResponse,
    ModelResponse,
    ProfileFromModelRequest,
    ProfileResponse,
    RayCurveRequest,
    RayCurveResponse,
    RayPointRequest,
    RayPointResponse,
)

router = APIRouter(prefix="/models")


def _models(request: Request) -> model_store.ModelStore:
    return request.app.state.model_store


def _profiles(request: Request):
    return request.app.state.profile_store


def _path_interface(value: str) -> int:
    """路径上的界面编号：只接受十进制整数写法，其余按越界类原因打回。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise NmoError("目标界面 interface 必须是从 1 起算的整数")


def _model_response(model: LayeredModel) -> ModelResponse:
    return ModelResponse(
        name=model.name,
        layers=[
            {"thickness": layer.thickness, "velocity": layer.velocity}
            for layer in model.layers
        ],
        interfaces=[
            {
                "index": summary.index,
                "depth": summary.depth,
                "t0": summary.t0,
                "vrms": summary.vrms,
            }
            for summary in model.interfaces()
        ],
    )


def _ray_point_response(model_name: str, point: rays.RayPoint) -> RayPointResponse:
    return RayPointResponse(
        model=model_name,
        interface=point.interface,
        offset=point.offset,
        ray_parameter=point.ray_parameter,
        exact_time=point.exact_time,
        t0=point.t0,
        vrms=point.vrms,
        hyperbolic_time=point.hyperbolic_time,
        difference=point.difference,
        recomputed_offset=point.recomputed_offset,
    )


@router.put("/{name}", response_model=ModelResponse)
def put_model(name: str, payload: ModelBody, request: Request) -> ModelResponse:
    model = _models(request).put(
        name,
        [(layer.thickness, layer.velocity) for layer in payload.layers],
    )
    return _model_response(model)


@router.get("", response_model=ModelListResponse)
def list_models(request: Request) -> ModelListResponse:
    return ModelListResponse(
        models=[_model_response(model) for model in _models(request).list()]
    )


@router.get("/{name}", response_model=ModelResponse)
def get_model(name: str, request: Request) -> ModelResponse:
    return _model_response(_models(request).get(name))


@router.delete("/{name}")
def delete_model(name: str, request: Request) -> dict[str, bool]:
    _models(request).delete(name)
    return {"deleted": True}


@router.post(
    "/{name}/interfaces/{interface}/ray/point",
    response_model=RayPointResponse,
)
def ray_point(
    name: str,
    interface: str,
    payload: RayPointRequest,
    request: Request,
) -> RayPointResponse:
    model = _models(request).get(name)
    if payload.model != name:
        raise NmoError("路径模型名与请求体 model 不一致")
    interface_value = validation.validate_interface(
        _path_interface(interface), model.layer_count
    )
    point = rays.trace_ray(model, interface_value, payload.offset)
    return _ray_point_response(name, point)


@router.post(
    "/{name}/interfaces/{interface}/ray/curve",
    response_model=RayCurveResponse,
)
def ray_curve(
    name: str,
    interface: str,
    payload: RayCurveRequest,
    request: Request,
) -> RayCurveResponse:
    model = _models(request).get(name)
    if payload.model != name:
        raise NmoError("路径模型名与请求体 model 不一致")
    interface_value = validation.validate_interface(
        _path_interface(interface), model.layer_count
    )
    curve = rays.trace_curve(model, interface_value, payload.offsets)
    return RayCurveResponse(
        model=name,
        interface=curve.interface,
        t0=curve.t0,
        vrms=curve.vrms,
        points=[_ray_point_response(name, point) for point in curve.points],
    )


@router.post(
    "/{name}/interfaces/{interface}/profile",
    response_model=ProfileResponse,
)
def profile_from_model(
    name: str,
    interface: str,
    request: Request,
    payload: ProfileFromModelRequest | None = None,
) -> ProfileResponse:
    """从模型某界面直接生成一套动校档：t0=垂直双程走时，v=均方根速度。

    生成后落在原有动校档命名空间，单点/曲线/扫描拿档名照常可用。
    """
    model = _models(request).get(name)
    interface_value = validation.validate_interface(
        _path_interface(interface), model.layer_count
    )
    summary = model.interface(interface_value)
    profile_name = payload.profile if payload and payload.profile else model.name
    profile = _profiles(request).put(profile_name, summary.t0, summary.vrms)
    return ProfileResponse(name=profile.name, t0=profile.t0, velocity=profile.velocity)
