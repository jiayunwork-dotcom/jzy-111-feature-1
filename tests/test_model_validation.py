"""层状模型 / 精确射线接口：不合法输入必须在计算启动前带原因打回。

覆盖需求点名的六类：界面越界、炮检距序列为空或次序不对、层数越界、
厚度或速度不是有限正数。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.errors import NmoError
from app.raytrace import LayeredModel, trace_curve, trace_ray

MODEL = LayeredModel("base", ((1000.0, 2000.0), (1000.0, 3000.0)))


@pytest.fixture
def ready_client(client: TestClient) -> TestClient:
    response = client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )
    assert response.status_code == 200
    return client


# ---------- 界面编号越界 ----------

def test_interface_out_of_range_rejected(ready_client: TestClient) -> None:
    for bad_interface in (-1, 2, 99):
        response = ready_client.post(
            "/ray/point",
            json={"model": "base", "interface": bad_interface, "offset": 1000.0},
        )
        assert response.status_code == 400
        assert "越界" in response.json()["reason"]


def test_interface_out_of_range_curve_rejected(ready_client: TestClient) -> None:
    response = ready_client.post(
        "/ray/curve",
        json={"model": "base", "interface": 2, "offsets": [0.0, 1000.0]},
    )
    assert response.status_code == 400
    assert "越界" in response.json()["reason"]


def test_interface_bool_rejected(ready_client: TestClient) -> None:
    # Pydantic 边界处直接挡下布尔值，不让 True 混作界面 1
    response = ready_client.post(
        "/ray/point", json={"model": "base", "interface": True, "offset": 1.0}
    )
    assert response.status_code == 400
    assert "布尔" in response.json()["reason"]


def test_interface_out_of_range_kernel() -> None:
    with pytest.raises(NmoError) as exc_info:
        trace_ray(MODEL, 2, 1000.0)
    assert "越界" in exc_info.value.reason
    with pytest.raises(NmoError):
        trace_ray(MODEL, -1, 1000.0)
    with pytest.raises(NmoError):
        trace_curve(MODEL, 0, [])  # 先校界面还是网格都应拦住
    single = LayeredModel("s", ((10.0, 1000.0),))
    with pytest.raises(NmoError):
        trace_ray(single, 1, 5.0)


# ---------- 炮检距序列为空或次序不对 ----------

def test_curve_empty_offsets_rejected(ready_client: TestClient) -> None:
    response = ready_client.post(
        "/ray/curve", json={"model": "base", "interface": 1, "offsets": []}
    )
    assert response.status_code == 400
    assert "不能为空" in response.json()["reason"]


def test_curve_offsets_must_strictly_increase(ready_client: TestClient) -> None:
    for bad_grid in ([3000.0, 1000.0], [0.0, 1000.0, 1000.0], [5.0, 2.0, 9.0]):
        response = ready_client.post(
            "/ray/curve",
            json={"model": "base", "interface": 1, "offsets": bad_grid},
        )
        assert response.status_code == 400
        assert "严格递增" in response.json()["reason"]


def test_curve_non_finite_offset_rejected(ready_client: TestClient) -> None:
    response = ready_client.post(
        "/ray/curve",
        content=b'{"model":"base","interface":1,"offsets":[0.0,"NaN"]}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "有限数值" in response.json()["reason"]


def test_point_non_finite_offset_rejected(ready_client: TestClient) -> None:
    response = ready_client.post(
        "/ray/point",
        content=b'{"model":"base","interface":1,"offset":"Infinity"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "有限数值" in response.json()["reason"]


# ---------- 层数越界 ----------

def test_no_layers_rejected(client: TestClient) -> None:
    response = client.put(
        "/velocity-models/empty", json={"layers": []}
    )
    assert response.status_code == 400
    assert "至少要有一层" in response.json()["reason"]


def test_too_many_layers_rejected(client: TestClient) -> None:
    response = client.put(
        "/velocity-models/huge",
        json={"layers": [{"thickness": 1.0, "velocity": 1000.0}] * 31},
    )
    assert response.status_code == 400
    assert "超过上限 30" in response.json()["reason"]


def test_exactly_thirty_layers_accepted(client: TestClient) -> None:
    response = client.put(
        "/velocity-models/max",
        json={
            "layers": [
                {"thickness": 100.0, "velocity": 1500.0 + 100.0 * i}
                for i in range(30)
            ]
        },
    )
    assert response.status_code == 200
    assert len(response.json()["interfaces"]) == 30


def test_layer_count_kernel_validation() -> None:
    from app.validation import validate_layer_specs

    with pytest.raises(NmoError):
        validate_layer_specs([])
    with pytest.raises(NmoError):
        validate_layer_specs([{"thickness": 1.0, "velocity": 1.0}] * 31)
    # 非序列 / 元素不是层对象
    with pytest.raises(NmoError):
        validate_layer_specs("not-a-list")
    with pytest.raises(NmoError):
        validate_layer_specs([(1.0, 1000.0)])


# ---------- 厚度或速度不是有限正数 ----------

def test_non_positive_thickness_rejected(client: TestClient) -> None:
    for bad in (0.0, -100.0):
        response = client.put(
            "/velocity-models/bad",
            json={
                "layers": [
                    {"thickness": bad, "velocity": 2000.0},
                ]
            },
        )
        assert response.status_code == 400
        assert "厚度" in response.json()["reason"] and "有限正数" in response.json()["reason"]


def test_non_positive_velocity_rejected(client: TestClient) -> None:
    for bad in (0.0, -2000.0):
        response = client.put(
            "/velocity-models/bad",
            json={"layers": [{"thickness": 100.0, "velocity": bad}]},
        )
        assert response.status_code == 400
        assert "层速度" in response.json()["reason"] and "有限正数" in response.json()["reason"]


def test_non_finite_layer_values_rejected(client: TestClient) -> None:
    for token, field in (("NaN", "thickness"), ("Infinity", "velocity")):
        body = (
            f'{{"layers":[{{"thickness":1.0,"velocity":2000.0}},'
            f'{{"{field}":{token},"velocity":2000.0}}]}}'
            if field == "thickness"
            else f'{{"layers":[{{"thickness":1.0,"velocity":{token}}} ]}}'
        )
        response = client.put(
            "/velocity-models/bad",
            content=body.encode(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "有限数值" in response.json()["reason"]


def test_bool_layer_values_rejected(client: TestClient) -> None:
    for payload in (
        {"layers": [{"thickness": True, "velocity": 2000.0}]},
        {"layers": [{"thickness": 1.0, "velocity": False}]},
    ):
        response = client.put("/velocity-models/bad", json=payload)
        assert response.status_code == 400


def test_wrong_layer_shape_rejected(client: TestClient) -> None:
    response = client.put(
        "/velocity-models/bad",
        json={"layers": [{"thickness": 100.0}]},  # 缺 velocity
    )
    assert response.status_code == 400
    response = client.put(
        "/velocity-models/bad",
        json={"layers": [1000.0, 2000.0]},  # 不是层对象
    )
    assert response.status_code == 400


# ---------- 资源不存在 / 生成档参数 ----------

def test_ray_request_unknown_model_404(ready_client: TestClient) -> None:
    assert (
        ready_client.post(
            "/ray/point", json={"model": "nope", "interface": 0, "offset": 1.0}
        ).status_code
        == 404
    )
    assert (
        ready_client.post(
            "/ray/curve", json={"model": "nope", "interface": 0, "offsets": [0.0, 1.0]}
        ).status_code
        == 404
    )


def test_profile_from_interface_validation(ready_client: TestClient) -> None:
    # 界面越界先于档生成
    response = ready_client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 3, "profile_name": "P"},
    )
    assert response.status_code == 400
    assert "越界" in response.json()["reason"]

    # 模型不存在 404
    response = ready_client.post(
        "/velocity-models/profile",
        json={"model": "missing", "interface": 0, "profile_name": "P"},
    )
    assert response.status_code == 404

    # 空档名打回
    response = ready_client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 0, "profile_name": "   "},
    )
    assert response.status_code == 400
    assert "非空字符串" in response.json()["reason"]
