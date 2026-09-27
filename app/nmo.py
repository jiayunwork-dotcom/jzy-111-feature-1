"""单点块：某炮检距处的反射双曲线走时与动校正量。

内核公式（水平层状介质反射波正常时差，非折射截距）::

    t(x)^2 = t0^2 + x^2 / v^2
    Δt(x) = t(x) - t0

其中 t0 为零偏移距双程走时，v 为叠加速度，x 为炮检距。
曲线块与扫描块都只准调用本模块的公式，保证全服务同一套速度、同一个平方关系。
"""

from __future__ import annotations

import math

from . import validation


def traveltime(t0: float, velocity: float, offset: float) -> float:
    """反射双曲线走时。入参假定已通过校验（服务层保证）。"""
    return math.sqrt(t0 * t0 + (offset * offset) / (velocity * velocity))


def moveout(t0: float, velocity: float, offset: float) -> float:
    """动校正量（正常时差）：t(x) - t0。炮检距为零时严格为零。"""
    return traveltime(t0, velocity, offset) - t0


def compute(t0: float, velocity: float, offset: float) -> dict[str, float]:
    """带校验的单点计算：赶在计算启动前拦住不合法输入。"""
    t0_value = validation.validate_t0(t0)
    velocity_value = validation.validate_velocity(velocity)
    offset_value = validation.validate_offset(offset)
    t = traveltime(t0_value, velocity_value, offset_value)
    return {
        "t0": t0_value,
        "velocity": velocity_value,
        "offset": offset_value,
        "traveltime": t,
        "moveout": t - t0_value,
    }
