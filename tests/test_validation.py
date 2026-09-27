"""不合法输入：必须在计算启动前拦住，返回带原因的错误响应。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import curve, nmo
from app.errors import NmoError


def test_nonpositive_velocity_rejected(client: TestClient) -> None:
    for bad in (0.0, -1500.0):
        response = client.post(
            "/nmo/point", json={"t0": 2.0, "velocity": bad, "offset": 1000.0}
        )
        assert response.status_code == 400
        assert "velocity 必须为正" in response.json()["reason"]


def test_negative_t0_rejected(client: TestClient) -> None:
    response = client.post(
        "/nmo/point", json={"t0": -0.001, "velocity": 2000.0, "offset": 1000.0}
    )
    assert response.status_code == 400
    assert "t0 不能为负" in response.json()["reason"]


def test_non_finite_inputs_rejected(client: TestClient) -> None:
    # 非数值类型：请求体解析阶段即 400
    response = client.post(
        "/nmo/point", json={"t0": 2.0, "velocity": 2000.0, "offset": "far"}
    )
    assert response.status_code == 400

    # Pydantic 接受 "nan"/"infinity" 字符串并转成 NaN/Inf，
    # 由领域校验在计算前拦下
    for bad_offset in ("nan", "infinity", "-infinity"):
        response = client.post(
            "/nmo/point",
            json={"t0": 2.0, "velocity": 2000.0, "offset": bad_offset},
        )
        assert response.status_code == 400
        assert "有限数值" in response.json()["reason"]

    # 内核直验 NaN/Inf
    with pytest.raises(NmoError):
        nmo.compute(float("nan"), 2000.0, 0.0)
    with pytest.raises(NmoError):
        nmo.compute(2.0, float("inf"), 0.0)


def test_offset_sign_equivalent() -> None:
    """炮检距正负都行：进公式的是平方，结果完全一致。"""
    assert nmo.compute(2.0, 2000.0, 1000.0)["traveltime"] == nmo.compute(
        2.0, 2000.0, -1000.0
    )["traveltime"]


def test_curve_grid_must_be_nonempty_strictly_increasing(client: TestClient) -> None:
    response = client.post(
        "/nmo/curve", json={"t0": 2.0, "velocity": 2000.0, "offsets": []}
    )
    assert response.status_code == 400
    assert "不能为空" in response.json()["reason"]

    response = client.post(
        "/nmo/curve",
        json={"t0": 2.0, "velocity": 2000.0, "offsets": [3000.0, 2000.0, 1000.0]},
    )
    assert response.status_code == 400
    assert "严格递增" in response.json()["reason"]


def test_kernel_unit_validation() -> None:
    with pytest.raises(NmoError):
        nmo.compute(2.0, 0.0, 1000.0)
    with pytest.raises(NmoError):
        curve.build_curve(-1.0, 2000.0, [0.0, 1000.0])
