"""参数校验：独立成块，所有不合法输入必须在计算启动前拦住。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .errors import NmoError
from .layers import MAX_LAYERS


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


def validate_layers(layers: object) -> list[tuple[float, float]]:
    """层状模型的层序列：

    - 必须是 1～30 个层的列表；
    - 每层至少给 thickness 与 velocity 两个字段；
    - 层厚与层速度都必须是有限正数（拒绝 bool / NaN / Inf / 非正数）。
    """
    if not isinstance(layers, Sequence) or isinstance(layers, (str, bytes)):
        raise NmoError("层序列 layers 必须是列表")
    if len(layers) == 0:
        raise NmoError("层序列 layers 不能为空（至少一层）")
    if len(layers) > MAX_LAYERS:
        raise NmoError(f"层数最多 {MAX_LAYERS} 层，当前 {len(layers)} 层（层数越界）")
    result: list[tuple[float, float]] = []
    for index, item in enumerate(layers):
        position = f"layers[{index}]"
        if isinstance(item, Mapping):
            missing = [key for key in ("thickness", "velocity") if key not in item]
            if missing:
                raise NmoError(f"{position} 缺少字段: {', '.join(missing)}")
            raw_thickness, raw_velocity = item["thickness"], item["velocity"]
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) == 2:
            raw_thickness, raw_velocity = item
        else:
            raise NmoError(f"{position} 必须是包含 thickness 与 velocity 的对象")
        thickness = require_finite(f"层厚 {position}.thickness", raw_thickness)
        velocity = require_finite(f"层速度 {position}.velocity", raw_velocity)
        if thickness <= 0.0:
            raise NmoError(f"层厚 {position}.thickness 必须为有限正数")
        if velocity <= 0.0:
            raise NmoError(f"层速度 {position}.velocity 必须为有限正数")
        result.append((thickness, velocity))
    return result


def validate_interface(interface: object, layer_count: int) -> int:
    """目标界面编号：正整数，且不超过层数。"""
    if not isinstance(interface, int) or isinstance(interface, bool):
        raise NmoError("目标界面 interface 必须是从 1 起算的整数")
    if not 1 <= interface <= layer_count:
        raise NmoError(
            f"目标界面 interface={interface} 越界：模型共 {layer_count} 层，"
            f"界面编号须在 1～{layer_count} 之间"
        )
    return interface
