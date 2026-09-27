"""曲线块：在炮检距网格上铺出整条反射双曲线走时曲线。

每个网格点都直接调用单点块（``nmo.traveltime`` / ``nmo.moveout``）
与拉伸块，批量曲线与单点接口天然同一套算法、同一套速度，
不存在“各说各话”的第二条公式实现。
"""

from __future__ import annotations

from . import validation
from .nmo import moveout, traveltime
from .stretch import DEFAULT_STRETCH_THRESHOLD


def build_curve(
    t0: float,
    velocity: float,
    offsets: list[float],
    stretch_threshold: float = DEFAULT_STRETCH_THRESHOLD,
) -> dict[str, object]:
    """带网格合理性校验地铺整条双曲线。

    网格必须非空且严格递增；速度为正、t0 非负等同样在计算启动前拦住。
    """
    t0_value = validation.validate_t0(t0)
    velocity_value = validation.validate_velocity(velocity)
    threshold = validation.validate_stretch_threshold(stretch_threshold)
    grid = validation.validate_offset_grid(offsets)

    traveltimes: list[float] = []
    moveouts: list[float] = []
    ratios: list[float | None] = []
    stretched_flags: list[bool] = []
    for offset in grid:
        t = traveltime(t0_value, velocity_value, offset)
        delta = moveout(t0_value, velocity_value, offset)
        traveltimes.append(t)
        moveouts.append(delta)
        if offset == 0.0 or delta == 0.0:
            ratio: float | None = 0.0
        elif t0_value == 0.0:
            ratio = None  # JSON 中用 null 表示正无穷的拉伸比
        else:
            ratio = delta / t0_value
        ratios.append(ratio)
        stretched_flags.append(ratio is None or ratio > threshold)

    return {
        "t0": t0_value,
        "velocity": velocity_value,
        "stretch_threshold": threshold,
        "offsets": grid,
        "traveltimes": traveltimes,
        "moveouts": moveouts,
        "stretch_ratios": ratios,
        "stretched": stretched_flags,
    }
