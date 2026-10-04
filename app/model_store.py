"""层状模型内存存取块：与动校档平行的一份独立命名空间。

纯内存、易失存储：重启即丢，和 ``profiles.ProfileStore`` 一模一样；
但两者各管各的名字——同名的层状模型与动校档互不覆盖、互不可见。
"""

from __future__ import annotations

import threading

from . import validation
from .errors import NotFoundError
from .layers import Layer, LayeredModel


class ModelStore:
    """线程安全的内存层状模型表。"""

    def __init__(self) -> None:
        self._models: dict[str, LayeredModel] = {}
        self._lock = threading.Lock()

    def put(self, name: str, layers: list[tuple[float, float]]) -> LayeredModel:
        """创建或覆盖一个模型；层厚/层速度在写入前完成校验。"""
        if not isinstance(name, str) or not name.strip():
            raise validation.NmoError("模型名 name 必须是非空字符串")
        checked = validation.validate_layers(layers)
        model = LayeredModel(
            name=name.strip(),
            layers=tuple(Layer(thickness=h, velocity=v) for h, v in checked),
        )
        with self._lock:
            self._models[model.name] = model
        return model

    def get(self, name: str) -> LayeredModel:
        if not isinstance(name, str):
            raise NotFoundError(f"层状模型 {name!r} 不存在")
        with self._lock:
            model = self._models.get(name)
        if model is None:
            raise NotFoundError(f"层状模型 {name!r} 不存在")
        return model

    def delete(self, name: str) -> None:
        with self._lock:
            existed = self._models.pop(name, None) is not None
        if not existed:
            raise NotFoundError(f"层状模型 {name!r} 不存在")

    def list(self) -> list[LayeredModel]:
        with self._lock:
            return list(self._models.values())
