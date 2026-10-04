"""层状速度模型块：水平层状介质的结构描述与界面派生量。

模型自上而下若干层（1～30 层），每层只给两个量：

- ``thickness``：层厚 h_i（长度量纲，如米），必须是有限正数；
- ``velocity``：层速度 v_i（如 m/s），必须是有限正数。

对第 k 个层底界面（界面编号自 1 起）给出：

- 界面深度            depth_k  = Σ_{i≤k} h_i
- 垂直双程走时        t0_k     = 2 Σ_{i≤k} h_i / v_i
- 均方根速度          vrms_k²  = (Σ_{i≤k} v_i h_i) / (Σ_{i≤k} h_i / v_i)

精确射线走时块（``rays``）与“从界面生动校档”都只准引用这里的派生量，
保证全服务对同一个模型说同一套 t0 / vrms。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_LAYERS = 30


@dataclass(frozen=True)
class Layer:
    """一个水平层：层厚与层速度。入组前已完成有限正数校验。"""

    thickness: float
    velocity: float


@dataclass(frozen=True)
class InterfaceSummary:
    """第 ``index`` 个层底界面的垂直走时与均方根速度。"""

    index: int
    depth: float
    t0: float
    vrms: float


@dataclass(frozen=True)
class LayeredModel:
    """命名层状速度模型。层序自上而下，构造即不可变。"""

    name: str
    layers: tuple[Layer, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.layers) <= MAX_LAYERS:
            raise ValueError(f"层数必须在 1～{MAX_LAYERS} 之间")

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    def interface(self, index: int) -> InterfaceSummary:
        """第 index 个层底界面（1 起算）的深度、垂直双程走时与均方根速度。"""
        if not 1 <= index <= len(self.layers):
            raise IndexError(index)
        depth = 0.0
        slow_time = 0.0   # Σ h_i / v_i：垂直单程走时
        weighted = 0.0    # Σ v_i h_i
        for layer in self.layers[:index]:
            depth += layer.thickness
            slow_time += layer.thickness / layer.velocity
            weighted += layer.velocity * layer.thickness
        t0 = 2.0 * slow_time
        vrms = math.sqrt(weighted / slow_time)
        return InterfaceSummary(index=index, depth=depth, t0=t0, vrms=vrms)

    def interfaces(self) -> list[InterfaceSummary]:
        """每个层底界面一份摘要，自上而下。"""
        return [self.interface(k) for k in range(1, len(self.layers) + 1)]
