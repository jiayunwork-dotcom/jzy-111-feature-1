"""精确射线走时块：水平层状介质中按斯奈尔定律折射/反射的真实射线路径。

物理关系（地表出发，穿过第 1～k 层，在第 k 个层底界面反射后原路返回）::

    Snell:      p = sin θ_i / v_i          （射线参数，全路径守恒）
    第 i 层水平投影（单程）:  X_i = p v_i h_i / sqrt(1 - (p v_i)^2)
    第 i 层传播时间（单程）:  τ_i =   h_i   / (v_i sqrt(1 - p² v_i²))
    半偏移（反射点在中点）:  X(p) = Σ X_i，地面炮检距 x = 2 X
    双程走时:                 t(p) = 2 Σ τ_i

p 的合法区间是 [0, 1/v_max)，其中 v_max 为射线穿过的各层中的最大层速度；
p 一旦等于 1/v_max，最快层临界折射，偏移趋于无穷。给定 x 求走时，就是求
单调方程 2 X(p) = |x| 的根。

求根变量的选择（README 中同样有说明）
--------------------------------------

直接对 p 做对分看似简单，但区间右端是开的奇点：p → 1/v_max 时
``sqrt(1-(pv)^2)`` 因相消损失精度，且 ``1/sqrt(...)`` 发散溢出，
右端点要小心翼翼地“留余量”，余量取多少都没有统一答案。

这里换变量::

    u = sqrt(1 - (p v_max)^2),   p = sqrt(1 - u^2) / v_max,   u ∈ (0, 1]

记 r_i = v_i / v_max（≤1）、q_i = 1 - r_i^2 = (1-r_i)(1+r_i)，则::

    X(u) = Σ h_i r_i sqrt((1-u)(1+u)) / sqrt(q_i + r_i^2 u^2)
    t(u) = 2 Σ h_i / (v_i sqrt(q_i + r_i^2 u^2))

这个参数化的好处：

1. 全程没有开平方相消项：``1 - u^2`` 写成 ``(1-u)(1+u)``，
   ``1 - r_i^2`` 写成 ``(1-r_i)(1+r_i)``，小 u / 大速度比都不丢位；
2. 最快层 r=1、q=0，分母 sqrt(r^2 u^2) 直接化简为 u，
   u→0 时 X→∞ 是干净的 ``1/u`` 发散，不出现 NaN/负数开根；
3. X(u) 关于 u 严格单调递减、u 关于 |x| 单调，括根只需从 u=1 出发
   逐次对分（u → u/2），天然不越过 u=0，不需要任何外推或猜测右端点。

代价：每次函数求值是一次 O(k) 求和，二分约 40～55 次到机器精度，
不引入任何外部求解器；换来的是临界区不溢出、不跑飞、对 30 层模型
依然瞬时完成。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import validation
from .errors import NmoError
from .layers import LayeredModel
from .nmo import traveltime as hyperbolic_traveltime

# 二分上限与残差目标。u 为二进制对分，200 步对应 u 下探到 2^-200，
# 覆盖任何有限炮检距；残差目标 1e-10 m 远严于核对口径 1 mm。
_MAX_BISECTION_STEPS = 200
_OFFSET_RESIDUAL_TOLERANCE = 1e-10


@dataclass(frozen=True)
class RayPoint:
    """单点精确射线结果。"""

    interface: int
    offset: float           # 请求炮检距（保留正负号，走时按绝对值算）
    ray_parameter: float    # p，s/m（恒非负；x=0 时严格为 0）
    exact_time: float       # 精确双程走时（秒）
    t0: float               # 该界面垂直双程走时
    vrms: float             # 该界面均方根速度
    hyperbolic_time: float  # 同一 t0、vrms 套双曲线的近似走时
    difference: float       # 精确 − 双曲近似（秒；多层远道为负，单层为机器零）
    recomputed_offset: float  # 用求得的射线参数复算的炮检距（正值）


@dataclass(frozen=True)
class RayCurve:
    """一排炮检距上的精确射线曲线。"""

    interface: int
    t0: float
    vrms: float
    points: tuple[RayPoint, ...]


@dataclass(frozen=True)
class _LayerTerms:
    """每层预算一次的与 u 无关的量。"""

    thickness: float
    ratio: float          # r_i = v_i / v_max
    q_value: float        # 1 - r_i^2，用 (1-r)(1+r) 稳定求值
    time_constant: float  # 2 h_i / v_i（走时求和系数，除分母后即双程层内时间）


def _prepare(
    model: LayeredModel, interface: int
) -> tuple[list[_LayerTerms], float, float, float]:
    """预算层系数、界面 t0、vrms 与最快层速度。"""
    layers = model.layers[:interface]
    v_max = max(layer.velocity for layer in layers)
    terms: list[_LayerTerms] = []
    for layer in layers:
        ratio = layer.velocity / v_max
        q_value = (1.0 - ratio) * (1.0 + ratio)
        terms.append(
            _LayerTerms(
                thickness=layer.thickness,
                ratio=ratio,
                q_value=q_value,
                time_constant=2.0 * layer.thickness / layer.velocity,
            )
        )
    summary = model.interface(interface)
    return terms, summary.t0, summary.vrms, v_max


def _half_offset_and_time(u: float, terms: list[_LayerTerms]) -> tuple[float, float]:
    """给定 u 计算半偏移 X(u) 与双程走时 t(u)。

    全部使用无开平方相消的稳定形式；调用方保证 u > 0。
    """
    one_minus_u2 = (1.0 - u) * (1.0 + u)
    sqrt_one_minus_u2 = math.sqrt(one_minus_u2)
    half_offset = 0.0
    total_time = 0.0
    for term in terms:
        inside = term.q_value + term.ratio * term.ratio * u * u
        denominator = math.sqrt(inside)
        # X_i = h_i r_i sqrt(1-u^2) / sqrt(q_i + r_i^2 u^2)
        half_offset += term.thickness * term.ratio * sqrt_one_minus_u2 / denominator
        # t_i（双程）= 2 h_i / (v_i sqrt(q_i + r_i^2 u^2))
        total_time += term.time_constant / denominator
    return half_offset, total_time


def _solve_u(target_half_offset: float, terms: list[_LayerTerms]) -> tuple[float, float, float]:
    """对分求解 2 X(u) = 2·target_half_offset，返回 (u, 半偏移, 走时)。

    括根：从 u=1（垂直射线，X=0）起逐次对分，直到 X(u) ≥ 目标值，
    根夹在 (u_low, u_high] 内；随后标准二分。任何一步都不出现外推，
    u 永远严格大于零。
    """
    u_low = 1.0
    x_low, t_low = _half_offset_and_time(u_low, terms)
    if x_low >= target_half_offset:  # 目标为零：垂直射线
        return u_low, x_low, t_low

    u_high = 0.5
    x_high = t_high = 0.0
    for _ in range(_MAX_BISECTION_STEPS):
        x_high, t_high = _half_offset_and_time(u_high, terms)
        if math.isfinite(x_high) and x_high >= target_half_offset:
            break
        u_low, x_low, t_low = u_high, x_high, t_high
        u_high *= 0.5
        if u_high <= 0.0:  # 有限输入不可达：2^-200 对应远超 DBL_MAX 的炮检距
            raise NmoError(
                "炮检距超出可计算范围：射线参数已逼近临界值 1/v_max 仍未达到该炮检距"
            )
    else:
        raise NmoError(  # pragma: no cover - 有限正数输入理论上不可达
            f"炮检距超出可计算范围：射线参数已逼近临界值 1/v_max 仍未达到该炮检距"
        )

    # 标准二分。u 为二进制对分，区间塌成同一个浮点数时即到机器精度。
    for _ in range(_MAX_BISECTION_STEPS):
        if u_high <= 0.0:  # pragma: no cover - 对分不到 0
            break
        u_mid = (u_low + u_high) * 0.5
        if u_mid == u_low or u_mid == u_high:
            break
        x_mid, t_mid = _half_offset_and_time(u_mid, terms)
        if not math.isfinite(x_mid):
            u_high = u_mid  # 越过临界发散侧，向 u=1 收
            continue
        residual = x_mid - target_half_offset
        if abs(residual) <= _OFFSET_RESIDUAL_TOLERANCE:
            return u_mid, x_mid, t_mid
        if residual < 0.0:
            u_low, x_low, t_low = u_mid, x_mid, t_mid
        else:
            u_high, x_high, t_high = u_mid, x_mid, t_mid

    # 取夹住根的两端中残差更小的一端
    if abs(x_low - target_half_offset) <= abs(x_high - target_half_offset):
        return u_low, x_low, t_low
    return u_high, x_high, t_high


def trace_ray(
    model: LayeredModel,
    interface: int,
    offset: float,
) -> RayPoint:
    """带校验的单点精确射线追踪。"""
    interface_value = validation.validate_interface(interface, model.layer_count)
    offset_value = validation.validate_offset(offset)
    terms, t0, vrms, v_max = _prepare(model, interface_value)

    requested = abs(offset_value)
    if requested == 0.0:
        return RayPoint(
            interface=interface_value,
            offset=offset_value,
            ray_parameter=0.0,
            exact_time=t0,
            t0=t0,
            vrms=vrms,
            hyperbolic_time=t0,
            difference=0.0,
            recomputed_offset=0.0,
        )

    target_half = requested * 0.5
    u, half_offset, exact_time = _solve_u(target_half, terms)
    if not math.isfinite(exact_time):  # pragma: no cover - 稳定公式下不应触发
        raise NmoError("该炮检距下精确走时超出可计算范围（射线过临界）")
    p = math.sqrt((1.0 - u) * (1.0 + u)) / v_max
    hyperbolic = hyperbolic_traveltime(t0, vrms, requested)
    return RayPoint(
        interface=interface_value,
        offset=offset_value,
        ray_parameter=p,
        exact_time=exact_time,
        t0=t0,
        vrms=vrms,
        hyperbolic_time=hyperbolic,
        difference=exact_time - hyperbolic,
        recomputed_offset=2.0 * half_offset,
    )


def trace_curve(
    model: LayeredModel,
    interface: int,
    offsets: list[float],
) -> RayCurve:
    """一排严格递增的炮检距一次算完整条曲线。

    每个点都是与 :func:`trace_ray` 完全相同的一次单点请求，
    逐点结果与相同输入下的单点调用逐位一致。
    """
    interface_value = validation.validate_interface(interface, model.layer_count)
    grid = validation.validate_offset_grid(offsets)
    points = tuple(trace_ray(model, interface_value, offset) for offset in grid)
    return RayCurve(
        interface=interface_value,
        t0=points[0].t0,
        vrms=points[0].vrms,
        points=points,
    )
