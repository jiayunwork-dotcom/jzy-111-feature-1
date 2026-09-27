"""领域错误与错误处理工具。

计算启动前发现的不合法输入统一抛 :class:`NmoError`，
由路由层转成带 ``reason`` 的错误响应；资源不存在用
:class:`NotFoundError` 映射为 404。
"""

from __future__ import annotations


class NmoError(ValueError):
    """动校正领域错误：输入不合法，需带原因打回。"""

    status_code = 400

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NotFoundError(NmoError):
    """命名动校档不存在。"""

    status_code = 404
