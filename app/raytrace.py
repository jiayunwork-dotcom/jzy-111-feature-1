"""精确射线走时块：水平层状介质、斯奈尔折射、目标界面反射。

模型自上而下若干水平层，每层给厚度 h_i、层速度 v_i。射线参数 p 在整条
射线上守恒（斯奈尔定律）::

    sin θ_i = p · v_i

给定 p，单程半炮检距与双程走时为::

    X(p) = Σ p · h_i · v_i / sqrt(1 − (p v_i)²)
    T(p) = Σ 2 · h_i / (v_i · sqrt(1 − (p v_i)²)

求和只取从地表到目标界面的各层（反射点以下不参与）。求射线就是解
X(p) = |x|/2；走时对炮检距的斜率恒等于 p，即 dt/dx = p（见测试）。

射线参数的求法（选择与代价）
----------------------------

直接对 p 求根时，物理允许范围是 p ∈ [0, 1/v_max)，其中 v_max 是被穿过
各层中的最快层速度。射线越接近临界值，1−(p v_i)² 越接近零，开方与除法
数值上容易溢出或跑飞。这里把变量换成**归一化射线参数**::

    s = p · v_max ∈ [0, 1)

并把开方写成 ``sqrt((1−r)(1+r))``：r→1 时 1−r 是独立保存的浮点量（不是
1−r² 相消出来的），在所有有限 s<1 下根号内都不丢精度、不产生负值，配合
下方“几何括住 + 二分”的求根，整个过程不出现除零与溢出。

代价有两点：
1. 不用现成的高阶求根（如 Brent），改用二分：X(s) 关于 s 严格单调，
   二分必然收敛；一次请求约 60 次迭代、每次最多 30 层求和，对在线
   单炮检距请求可以忽略；不引入 scipy 等重依赖，镜像保持一键构建。
2. s→1 时 X(s) 以 1/sqrt(1−s) 发散，因此任何有限炮检距都有唯一根；
   真正的临界射线（x→∞）物理上就不存在，若浮点上已无法再把括住区间
   向 1 推进而炮检距仍未达到，则抛出明确错误，而不是返回一条错误射线。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import validation
from .errors import NmoError
from .nmo import traveltime as hyperbolic_traveltime

# 二分迭代上限：60 次后区间相对宽度约 1e-18，远高于炮检距毫米级复算的需要。
_MAX_BISECTION_ITERATIONS = 80
# 初始上界与几何扩张因子：区间从 s=0.5 起，每次吃掉剩余 (1−s) 的一半。
_INITIAL_UPPER = 0.5
_EXPANSION_FACTOR = 0.5


def _safe_sqrt_one_minus_r2(r: float) -> float:
    """稳定计算 sqrt(1−r²)：写成 (1−r)(1+r)，r→1 也不相消、不出现负值。"""
    value = (1.0 - r) * (1.0 + r)
    if value <= 0.0:
        # 数学上仅在 r==1（临界射线，炮检距无穷）时取等；给出明确错误而非跑飞。
        raise NmoError("射线已达到最快层临界角，该有限炮检距不存在物理射线")
    return math.sqrt(value)


@dataclass(frozen=True)
class LayeredModel:
    """水平层状速度模型：层（厚度, 层速度）自地表向下排列。"""

    name: str
    layers: tuple[tuple[float, float], ...]

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    def interface_stats(self, interface: int) -> tuple[float, float]:
        """第 ``interface`` 层底界面的垂直双程走时 t0 与均方根速度 vrms。

        界面编号自 0 起（0 即第一层底），按 Dix 均方根定义::

            t0   = Σ_{i≤I} 2 h_i / v_i
            vrms = sqrt( Σ_{i≤I} v_i² · (2 h_i / v_i) / t0 )
        """
        t0 = 0.0
        weighted = 0.0
        for thickness, velocity in self.layers[: interface + 1]:
            vertical = 2.0 * thickness / velocity
            t0 += vertical
            weighted += velocity * velocity * vertical
        return t0, math.sqrt(weighted / t0)

    def all_interfaces(self) -> list[tuple[float, float]]:
        """每个层底界面的 (垂直双程走时, 均方根速度)，自上而下。"""
        stats: list[tuple[float, float]] = []
        t0 = 0.0
        weighted = 0.0
        for thickness, velocity in self.layers:
            vertical = 2.0 * thickness / velocity
            t0 += vertical
            weighted += velocity * velocity * vertical
            stats.append((t0, math.sqrt(weighted / t0)))
        return stats


def _max_velocity(layers: tuple[tuple[float, float], ...], interface: int) -> float:
    return max(velocity for _, velocity in layers[: interface + 1])


def _half_offset_and_time(
    s: float,
    layers: tuple[tuple[float, float], ...],
    interface: int,
    v_max: float,
) -> tuple[float, float]:
    """给定归一化射线参数 s，返回（单程半炮检距 X，双程走时 T）。"""
    p = s / v_max
    half_offset = 0.0
    travel_time = 0.0
    for thickness, velocity in layers[: interface + 1]:
        root = _safe_sqrt_one_minus_r2(s * (velocity / v_max))
        half_offset += p * thickness * velocity / root
        travel_time += 2.0 * thickness / (velocity * root)
    return half_offset, travel_time


def _solve_normalized_p(
    half_target: float,
    layers: tuple[tuple[float, float], ...],
    interface: int,
    v_max: float,
) -> float:
    """在 s ∈ [0,1) 上二分求解 X(s) = half_target，返回归一化射线参数 s。

    先几何扩张括住根（上界每次向 1 推进剩余距离的一半），再二分到底。
    """
    lower = 0.0
    upper = _INITIAL_UPPER
    while _half_offset_and_time(upper, layers, interface, v_max)[0] < half_target:
        lower = upper
        upper = upper + (1.0 - upper) * _EXPANSION_FACTOR
        if upper >= 1.0 or (1.0 - upper) == 0.0:
            raise NmoError("炮检距超出射线可及范围：射线参数已逼近临界角")
    for _ in range(_MAX_BISECTION_ITERATIONS):
        middle = (lower + upper) * 0.5
        if middle == lower or middle == upper:
            break  # 区间已窄到机器精度，再分无收益
        if _half_offset_and_time(middle, layers, interface, v_max)[0] < half_target:
            lower = middle
        else:
            upper = middle
    return (lower + upper) * 0.5


@dataclass(frozen=True)
class RayResult:
    """单炮检距精确射线结果（炮检距按绝对值处理，p 非负）。"""

    offset: float                # 原样回显的请求炮检距（保留正负号）
    ray_parameter: float         # s/v_max；零炮检距严格为 0
    exact_traveltime: float      # 精确射线双程走时
    hyperbolic_traveltime: float # 该界面 t0、vrms 套双曲近似的走时
    traveltime_difference: float # 精确 − 双曲
    t0: float                    # 目标界面垂直双程走时
    vrms: float                  # 目标界面均方根速度
    recomputed_offset: float     # 由射线参数复算回的全炮检距（=|offset|）


def trace_ray(model: LayeredModel, interface: object, offset: object) -> RayResult:
    """带校验地求一条反射射线：界面越界、炮检距非有限都在计算前打回。"""
    target_interface = validation.validate_interface(interface, model.layer_count)
    target_offset = validation.validate_offset(offset)
    t0, vrms = model.interface_stats(target_interface)

    absolute = abs(target_offset)
    if absolute == 0.0:
        exact = t0
        ray_parameter = 0.0
        recomputed = 0.0
    else:
        v_max = _max_velocity(model.layers, target_interface)
        s = _solve_normalized_p(
            absolute * 0.5, model.layers, target_interface, v_max
        )
        half_offset, exact = _half_offset_and_time(
            s, model.layers, target_interface, v_max
        )
        ray_parameter = s / v_max
        recomputed = 2.0 * half_offset

    hyperbolic = hyperbolic_traveltime(t0, vrms, absolute)
    return RayResult(
        offset=target_offset,
        ray_parameter=ray_parameter,
        exact_traveltime=exact,
        hyperbolic_traveltime=hyperbolic,
        traveltime_difference=exact - hyperbolic,
        t0=t0,
        vrms=vrms,
        recomputed_offset=recomputed,
    )


def interface_kinematics(
    model: LayeredModel, interface: object
) -> tuple[float, float]:
    """某界面的 (垂直双程走时, 均方根速度)，带界面越界校验。

    供“从界面生成动校档”复用，避免借道单点射线计算。
    """
    target_interface = validation.validate_interface(interface, model.layer_count)
    return model.interface_stats(target_interface)


def trace_curve(
    model: LayeredModel, interface: object, offsets: object
) -> list[RayResult]:
    """一排严格递增炮检距整条曲线。

    网格先做与动校曲线同一套严格递增校验，再逐点调用单点内核，
    保证曲线每个点与单点请求同参结果完全一致（逐位相等）。
    """
    target_interface = validation.validate_interface(interface, model.layer_count)
    grid = validation.validate_offset_grid(offsets)
    return [trace_ray(model, target_interface, value) for value in grid]
