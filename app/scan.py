"""速度扫描块：对候选叠加速度逐个评估，看哪个把同相轴校平。

观测同相轴走时 t_obs(x) 满足反射双曲线（真实速度 v_true）::

    t_obs(x)^2 = t0^2 + x^2 / v_true^2

用候选速度 v 做动校正::

    t_corr(x) = t_obs(x) - sqrt(t0^2 + x^2 / v^2)

同相轴被校平，等价于所有炮检距处 t_corr 都等于零（残差为零）。
以各道校正后走时相对零偏移道残差的均方值（总体方差）作为平整度
评分：平方项 |x/v| 关于 v 单调，该评分在 v = v_true 处取唯一最小值 0，
因此正确速度必然把双曲线拉得最平，扫描结果直接反映这一点。

观测来源二选一：
- ``event_velocity`` + ``t0``：按真实事件速度合成观测走时；
- ``observed_times``：直接给观测走时（首道须为零偏移道）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import validation
from .errors import NmoError
from .nmo import traveltime


@dataclass(frozen=True)
class ScanCandidate:
    velocity: float
    corrected_times: list[float]
    flatness: float          # 校正后残差均方，越小越平（0 为完全校平）
    max_abs_deviation: float  # 最大绝对残差


@dataclass(frozen=True)
class ScanResult:
    t0: float
    offsets: list[float]
    observed_times: list[float]
    candidates: list[ScanCandidate]
    best_velocity: float
    best_flatness: float
    best_index: int


def _evaluate_candidate(
    velocity: float,
    t0: float,
    offsets: list[float],
    observed: list[float],
) -> ScanCandidate:
    corrected = [
        observed[i] - traveltime(t0, velocity, offsets[i])
        for i in range(len(offsets))
    ]
    reference = corrected[0]
    residuals = [value - reference for value in corrected]
    flatness = sum(r * r for r in residuals) / len(residuals)
    max_dev = max(abs(r) for r in residuals)
    return ScanCandidate(
        velocity=velocity,
        corrected_times=corrected,
        flatness=flatness,
        max_abs_deviation=max_dev,
    )


def scan_velocities(
    offsets: list[float],
    candidate_velocities: list[float],
    t0: float | None = None,
    event_velocity: float | None = None,
    observed_times: list[float] | None = None,
) -> ScanResult:
    """带校验地跑速度扫描。列表/网格类问题在此提前挡下，不在循环中途崩。"""
    grid = validation.validate_offset_grid(offsets)
    candidates_input = validation.validate_candidate_velocities(candidate_velocities)
    if grid[0] != 0.0:
        raise NmoError("速度扫描要求炮检距网格首端为零偏移距（offsets[0] = 0）")

    synthetic = event_velocity is not None
    direct = observed_times is not None
    if synthetic and direct:
        raise NmoError("event_velocity 与 observed_times 只能提供一个")
    if not synthetic and not direct:
        raise NmoError("速度扫描必须提供 event_velocity 或 observed_times")
    if synthetic and t0 is None:
        raise NmoError("通过 event_velocity 合成观测时必须提供 t0")

    if synthetic:
        t0_value = validation.validate_t0(t0)
        event_v = validation.validate_velocity(event_velocity)
        observed = [traveltime(t0_value, event_v, x) for x in grid]
    else:
        observed = validation.validate_observed_times(observed_times, grid)
        t0_value = observed[0]  # 零偏移道观测值即零偏移距双程走时

    evaluated = [
        _evaluate_candidate(v, t0_value, grid, observed) for v in candidates_input
    ]
    best_index = min(
        range(len(evaluated)),
        key=lambda i: evaluated[i].flatness,
    )
    return ScanResult(
        t0=t0_value,
        offsets=grid,
        observed_times=observed,
        candidates=evaluated,
        best_velocity=evaluated[best_index].velocity,
        best_flatness=evaluated[best_index].flatness,
        best_index=best_index,
    )
