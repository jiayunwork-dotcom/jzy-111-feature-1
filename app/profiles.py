"""动校档存取块：把常用的（零偏移走时, 叠加速度）组合命名反复调用。

纯内存、易失存储：重启即丢，服务重启后为空，不做持久化。
两份档相互独立——扫描 A 档只取 A 的 t0/速度，绝不串到 B 档的曲线。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from . import validation
from .errors import NotFoundError


@dataclass(frozen=True)
class NmoProfile:
    """命名动校档：零偏移双程走时 + 叠加速度。"""

    name: str
    t0: float
    velocity: float


class ProfileStore:
    """线程安全的内存动校档表。"""

    def __init__(self) -> None:
        self._profiles: dict[str, NmoProfile] = {}
        self._lock = threading.Lock()

    def put(self, name: str, t0: float, velocity: float) -> NmoProfile:
        """创建或覆盖一档，入参在写入前完成校验。"""
        if not isinstance(name, str) or not name.strip():
            raise validation.NmoError("动校档名 name 必须是非空字符串")
        t0_value = validation.validate_t0(t0)
        velocity_value = validation.validate_velocity(velocity)
        profile = NmoProfile(name=name.strip(), t0=t0_value, velocity=velocity_value)
        with self._lock:
            self._profiles[profile.name] = profile
        return profile

    def get(self, name: str) -> NmoProfile:
        if not isinstance(name, str):
            raise NotFoundError(f"动校档 {name!r} 不存在")
        with self._lock:
            profile = self._profiles.get(name)
        if profile is None:
            raise NotFoundError(f"动校档 {name!r} 不存在")
        return profile

    def delete(self, name: str) -> None:
        with self._lock:
            existed = self._profiles.pop(name, None) is not None
        if not existed:
            raise NotFoundError(f"动校档 {name!r} 不存在")

    def list(self) -> list[NmoProfile]:
        with self._lock:
            return list(self._profiles.values())
