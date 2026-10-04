"""层状模型 / 精确射线路由层：只解析请求、组织返回，不含公式。

接口：
- PUT/GET/DELETE /velocity-models[/{name}]   命名层状速度模型增删查（重启即丢）
- POST /ray/point      单炮检距精确射线走时与双曲近似之差
- POST /ray/curve      严格递增炮检距网格上的整条精确走时曲线
- POST /velocity-models/profile   从模型某界面直接生成一套动校档
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from . import raytrace
from .model_schemas import (
    InterfaceStat,
    LayerResponse,
    ModelBody,
    ModelListResponse,
    ModelResponse,
    ProfileFromInterfaceRequest,
    ProfileFromInterfaceResponse,
    RayCurvePoint,
    RayCurveRequest,
    RayCurveResponse,
    RayPointRequest,
    RayPointResponse,
)

model_router = APIRouter()


def _models(request: Request):
    return request.app.state.velocity_model_store


def _profiles(request: Request):
    return request.app.state.profile_store


def _model_response(model: raytrace.LayeredModel) -> ModelResponse:
    stats = model.all_interfaces()
    depth = 0.0
    interface_payload: list[InterfaceStat] = []
    for index, ((thickness, velocity), (t0, vrms)) in enumerate(
        zip(model.layers, stats)
    ):
        depth += thickness
        interface_payload.append(
            InterfaceStat(interface=index, depth=depth, t0=t0, vrms=vrms)
        )
    return ModelResponse(
        name=model.name,
        layers=[
            LayerResponse(index=index, thickness=thickness, velocity=velocity)
            for index, (thickness, velocity) in enumerate(model.layers)
        ],
        interfaces=interface_payload,
    )


@model_router.put("/velocity-models/{name}", response_model=ModelResponse)
def put_velocity_model(
    name: str, payload: ModelBody, request: Request
) -> ModelResponse:
    model = _models(request).put(
        name, [layer.model_dump() for layer in payload.layers]
    )
    return _model_response(model)


@model_router.get("/velocity-models", response_model=ModelListResponse)
def list_velocity_models(request: Request) -> ModelListResponse:
    return ModelListResponse(
        models=[_model_response(model) for model in _models(request).list()]
    )


@model_router.get("/velocity-models/{name}", response_model=ModelResponse)
def get_velocity_model(name: str, request: Request) -> ModelResponse:
    return _model_response(_models(request).get(name))


@model_router.delete("/velocity-models/{name}")
def delete_velocity_model(name: str, request: Request) -> dict[str, bool]:
    _models(request).delete(name)
    return {"deleted": True}


@model_router.post("/ray/point", response_model=RayPointResponse)
def ray_point(payload: RayPointRequest, request: Request) -> RayPointResponse:
    model = _models(request).get(payload.model)
    result = raytrace.trace_ray(model, payload.interface, payload.offset)
    return RayPointResponse(
        model=model.name,
        interface=payload.interface,
        offset=result.offset,
        ray_parameter=result.ray_parameter,
        t0=result.t0,
        vrms=result.vrms,
        exact_traveltime=result.exact_traveltime,
        hyperbolic_traveltime=result.hyperbolic_traveltime,
        traveltime_difference=result.traveltime_difference,
        recomputed_offset=result.recomputed_offset,
    )


@model_router.post("/ray/curve", response_model=RayCurveResponse)
def ray_curve(payload: RayCurveRequest, request: Request) -> RayCurveResponse:
    model = _models(request).get(payload.model)
    results = raytrace.trace_curve(model, payload.interface, payload.offsets)
    return RayCurveResponse(
        model=model.name,
        interface=payload.interface,
        t0=results[0].t0,
        vrms=results[0].vrms,
        points=[
            RayCurvePoint(
                offset=item.offset,
                ray_parameter=item.ray_parameter,
                exact_traveltime=item.exact_traveltime,
                hyperbolic_traveltime=item.hyperbolic_traveltime,
                traveltime_difference=item.traveltime_difference,
                recomputed_offset=item.recomputed_offset,
            )
            for item in results
        ],
    )


@model_router.post(
    "/velocity-models/profile", response_model=ProfileFromInterfaceResponse
)
def create_profile_from_interface(
    payload: ProfileFromInterfaceRequest, request: Request
) -> ProfileFromInterfaceResponse:
    model = _models(request).get(payload.model)
    t0, vrms = raytrace.interface_kinematics(model, payload.interface)
    profile = _profiles(request).put(payload.profile_name, t0, vrms)
    return ProfileFromInterfaceResponse(
        profile_name=profile.name,
        model=model.name,
        interface=payload.interface,
        t0=profile.t0,
        velocity=profile.velocity,
    )
