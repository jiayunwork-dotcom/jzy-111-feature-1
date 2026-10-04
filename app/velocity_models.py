"""层状速度模型存取块：命名模型反复调用，纯内存、重启即丢。

与动校档（:class:`app.profiles.ProfileStore`）各管各的名字空间：
模型叫 ``A`` 与动校档叫 ``A`` 互不覆盖、互不可见。存储线程安全，
层定义在写入前完成全部领域校验。
"""

from __future__ import annotations

import threading

from . import validation
from .errors import NotFoundError
from .raytrace import LayeredModel


class VelocityModelStore:
    """线程安全的内存层状速度模型表。"""

    def __init__(self) -> None:
        self._models: dict[str, LayeredModel] = {}
        self._lock = threading.Lock()

    def put(self, name: object, layers: object) -> LayeredModel:
        """创建或覆盖一套模型，层数与每层数值在写入前完成校验。"""
        model_name = validation.validate_model_name(name)
        specs = validation.validate_layer_specs(layers)
        model = LayeredModel(name=model_name, layers=tuple(specs))
        with self._lock:
            self._models[model_name] = model
        return model

    def get(self, name: object) -> LayeredModel:
        if not isinstance(name, str):
            raise NotFoundError(f"速度模型 {name!r} 不存在")
        with self._lock:
            model = self._models.get(name)
        if model is None:
            raise NotFoundError(f"速度模型 {name!r} 不存在")
        return model

    def delete(self, name: str) -> None:
        with self._lock:
            existed = self._models.pop(name, None) is not None
        if not existed:
            raise NotFoundError(f"速度模型 {name!r} 不存在")

    def list(self) -> list[LayeredModel]:
        with self._lock:
            return list(self._models.values())
