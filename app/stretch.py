"""拉伸标记判定：单列一块。

浅层（t0 小）配上大偏移距时，动校正量相对零偏移走时占比过大，
即 NMO 拉伸严重。判定量::

    stretch = Δt / t0 = (t(x) - t0) / t0

超过阈值就标 stretch=true，但走时值照实返回，不拒绝。
t0=0 且偏移距非零时比值为正无穷，必然告警；炮检距为零时比值为 0。
"""

from __future__ import annotations

import math

from .nmo import moveout, traveltime

DEFAULT_STRETCH_THRESHOLD = 0.10


def evaluate(
    t0: float,
    velocity: float,
    offset: float,
    threshold: float = DEFAULT_STRETCH_THRESHOLD,
) -> dict[str, float | bool]:
    """返回拉伸比值与标记。入参假定已通过服务层校验。"""
    delta = moveout(t0, velocity, offset)
    if offset == 0.0 or delta == 0.0:
        ratio = 0.0
    elif t0 == 0.0:
        ratio = math.inf
    else:
        ratio = delta / t0
    return {
        "stretch_ratio": ratio,
        "stretch_threshold": threshold,
        "stretched": ratio > threshold,
    }


def evaluate_with_traveltime(
    t0: float,
    velocity: float,
    offset: float,
    threshold: float = DEFAULT_STRETCH_THRESHOLD,
) -> dict[str, float | bool]:
    """拉伸判定连同走时一起返回，避免上层重复开方。"""
    t = traveltime(t0, velocity, offset)
    delta = t - t0
    if offset == 0.0 or delta == 0.0:
        ratio = 0.0
    elif t0 == 0.0:
        ratio = math.inf
    else:
        ratio = delta / t0
    return {
        "traveltime": t,
        "moveout": delta,
        "stretch_ratio": ratio,
        "stretch_threshold": threshold,
        "stretched": ratio > threshold,
    }
