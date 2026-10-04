"""参数校验：独立成块，所有不合法输入必须在计算启动前拦住。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .errors import NmoError

MAX_LAYERS = 30


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require_finite(name: str, value: object) -> float:
    """要求是有限数值，拒绝 bool / NaN / Inf / 非数值。"""
    if not _is_finite_number(value):
        raise NmoError(f"{name} 必须是有限数值")
    return float(value)


def validate_t0(t0: object) -> float:
    """零偏移距双程走时不得为负。t0 为零在数学上合法（非零炮检距会拉伸告警）。"""
    value = require_finite("零偏移距双程走时 t0", t0)
    if value < 0.0:
        raise NmoError("零偏移距双程走时 t0 不能为负")
    return value


def validate_velocity(velocity: object) -> float:
    """叠加速度必须为正。"""
    value = require_finite("叠加速度 velocity", velocity)
    if value <= 0.0:
        raise NmoError("叠加速度 velocity 必须为正")
    return value


def validate_offset(offset: object) -> float:
    """炮检距正负皆可，进公式的是它的平方。"""
    return require_finite("炮检距 offset", offset)


def validate_stretch_threshold(threshold: object) -> float:
    """拉伸告警阈值必须为正。"""
    value = require_finite("拉伸告警阈值 stretch_threshold", threshold)
    if value <= 0.0:
        raise NmoError("拉伸告警阈值 stretch_threshold 必须为正")
    return value


def validate_offset_grid(offsets: object) -> list[float]:
    """炮检距网格：必须是非空、严格递增的有限数值序列。

    端点次序不对（首端大于末端）会随“严格递增”检查一起被挡下，
    防止批量计算跑到一半才崩。
    """
    if not isinstance(offsets, Sequence) or isinstance(offsets, (str, bytes)):
        raise NmoError("炮检距网格 offsets 必须是数值列表")
    if len(offsets) == 0:
        raise NmoError("炮检距网格 offsets 不能为空")
    grid: list[float] = []
    previous: float | None = None
    for index, item in enumerate(offsets):
        value = require_finite(f"炮检距网格 offsets[{index}]", item)
        if previous is not None and value <= previous:
            raise NmoError(
                f"炮检距网格 offsets 必须严格递增：offsets[{index - 1}]={previous}, "
                f"offsets[{index}]={value}（网格端点次序不对）"
            )
        grid.append(value)
        previous = value
    return grid


def validate_candidate_velocities(velocities: object) -> list[float]:
    """候选叠加速度列表：非空，逐项为正。"""
    if not isinstance(velocities, Sequence) or isinstance(velocities, (str, bytes)):
        raise NmoError("候选叠加速度 velocities 必须是数值列表")
    if len(velocities) == 0:
        raise NmoError("候选叠加速度 velocities 列表不能为空")
    result: list[float] = []
    for index, item in enumerate(velocities):
        value = validate_velocity(item)
        result.append(value)
    return result


def validate_observed_times(times: object, offsets: Sequence[float]) -> list[float]:
    """观测走时：非空，长度与炮检距网格一致，取值不得为负。"""
    if not isinstance(times, Sequence) or isinstance(times, (str, bytes)):
        raise NmoError("观测走时 observed_times 必须是数值列表")
    if len(times) != len(offsets):
        raise NmoError(
            f"观测走时 observed_times 长度 {len(times)} 与炮检距网格长度 {len(offsets)} 不一致"
        )
    result: list[float] = []
    for index, item in enumerate(times):
        value = require_finite(f"观测走时 observed_times[{index}]", item)
        if value < 0.0:
            raise NmoError(f"观测走时 observed_times[{index}] 不能为负")
        result.append(value)
    return result


def validate_no_profile_inline_mix(profile: object, t0: object, velocity: object) -> None:
    """给了动校档名就不允许再内联 t0/velocity，避免两套参数混用。"""
    if profile is not None and (t0 is not None or velocity is not None):
        raise NmoError("指定动校档 profile 时不能同时内联提供 t0 或 velocity")


def validate_layer_specs(layers: object) -> list[tuple[float, float]]:
    """层状模型的层定义：序列长度 1~30，每层 (厚度, 层速度) 均为有限正数。

    布尔值不允许混进数值（True==1 会骗过 ``isinstance``），在计算启动前带原因挡下。
    """
    if not isinstance(layers, Sequence) or isinstance(layers, (str, bytes)):
        raise NmoError("层定义 layers 必须是层对象列表")
    count = len(layers)
    if count == 0:
        raise NmoError("层定义 layers 至少要有一层")
    if count > MAX_LAYERS:
        raise NmoError(f"层定义 layers 层数 {count} 超过上限 {MAX_LAYERS}")
    result: list[tuple[float, float]] = []
    for index, item in enumerate(layers):
        if not isinstance(item, Mapping):
            raise NmoError(f"layers[{index}] 必须是包含 thickness 与 velocity 的层对象")
        thickness = require_finite(f"第 {index + 1} 层厚度 thickness[{index}]", item.get("thickness"))
        velocity = require_finite(f"第 {index + 1} 层层速度 velocity[{index}]", item.get("velocity"))
        if thickness <= 0.0:
            raise NmoError(f"第 {index + 1} 层厚度 thickness[{index}] 必须为有限正数")
        if velocity <= 0.0:
            raise NmoError(f"第 {index + 1} 层层速度 velocity[{index}] 必须为有限正数")
        result.append((thickness, velocity))
    return result


def validate_interface(interface: object, layer_count: int) -> int:
    """目标界面编号：自 0 起（0=第一层底），不得越界到层数之外。"""
    if isinstance(interface, bool) or not isinstance(interface, int):
        raise NmoError("目标界面编号 interface 必须是整数")
    if interface < 0 or interface >= layer_count:
        raise NmoError(
            f"目标界面编号 interface={interface} 越界：模型共 {layer_count} 层，"
            f"合法范围为 0..{layer_count - 1}"
        )
    return interface


def validate_model_name(name: object) -> str:
    """速度模型名必须是非空字符串；与动校档名各管各的名字空间。"""
    if not isinstance(name, str) or not name.strip():
        raise NmoError("速度模型名 name 必须是非空字符串")
    return name.strip()


def validate_profile_name(name: object) -> str:
    """从界面生成动校档时，动校档名必须是非空字符串。"""
    if not isinstance(name, str) or not name.strip():
        raise NmoError("动校档名 profile_name 必须是非空字符串")
    return name.strip()
