"""层状模型与精确射线接口的请求 / 响应模型，只描述接口形状。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LayerBody(BaseModel):
    # 数值字段保持宽松，交给领域校验统一带原因打回；这里只额外拦 bool
    # （Pydantic 默认会把 True/False 强转成 1.0/0.0）。
    thickness: float = Field(description="层厚（与炮检距同量纲体系，如 m）")
    velocity: float = Field(description="层速度（如 m/s）")

    @field_validator("thickness", "velocity", mode="before")
    @classmethod
    def _reject_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("不能是布尔值，必须是数值")
        return value


class ModelBody(BaseModel):
    layers: list[LayerBody] = Field(description="自地表向下的层，1~30 层")


def _reject_bool_int(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("不能是布尔值，界面编号必须是整数")
    return value


class InterfaceStat(BaseModel):
    interface: int = Field(description="界面编号，自 0 起（0=第一层底）")
    depth: float = Field(description="该界面深度（自地表累计层厚）")
    t0: float = Field(description="垂直双程走时（秒）")
    vrms: float = Field(description="均方根速度")


class LayerResponse(BaseModel):
    index: int
    thickness: float
    velocity: float


class ModelResponse(BaseModel):
    name: str
    layers: list[LayerResponse]
    interfaces: list[InterfaceStat] = Field(
        description="每个层底界面的垂直双程走时与均方根速度"
    )


class ModelListResponse(BaseModel):
    models: list[ModelResponse]


class RayPointRequest(BaseModel):
    model: str = Field(description="命名速度模型")
    interface: int = Field(description="目标界面编号，自 0 起")
    offset: float = Field(description="炮检距，正负均可，按绝对值处理")

    @field_validator("interface", mode="before")
    @classmethod
    def _interface_not_bool(cls, value: object) -> object:
        return _reject_bool_int(value)


class RayPointResponse(BaseModel):
    model: str
    interface: int
    offset: float
    ray_parameter: float
    t0: float
    vrms: float
    exact_traveltime: float
    hyperbolic_traveltime: float
    traveltime_difference: float
    recomputed_offset: float = Field(description="由射线参数复算回的炮检距（绝对值）")


class RayCurveRequest(BaseModel):
    model: str
    interface: int
    offsets: list[float] = Field(description="炮检距网格，必须非空且严格递增")

    @field_validator("interface", mode="before")
    @classmethod
    def _interface_not_bool(cls, value: object) -> object:
        return _reject_bool_int(value)


class RayCurvePoint(BaseModel):
    offset: float
    ray_parameter: float
    exact_traveltime: float
    hyperbolic_traveltime: float
    traveltime_difference: float
    recomputed_offset: float


class RayCurveResponse(BaseModel):
    model: str
    interface: int
    t0: float
    vrms: float
    points: list[RayCurvePoint]


class ProfileFromInterfaceRequest(BaseModel):
    model: str = Field(description="来源速度模型")
    interface: int = Field(description="取该界面的垂直双程走时与均方根速度")
    profile_name: str = Field(description="生成的动校档名，与已有动校档同一名字空间")

    @field_validator("interface", mode="before")
    @classmethod
    def _interface_not_bool(cls, value: object) -> object:
        return _reject_bool_int(value)


class ProfileFromInterfaceResponse(BaseModel):
    profile_name: str
    model: str
    interface: int
    t0: float
    velocity: float
