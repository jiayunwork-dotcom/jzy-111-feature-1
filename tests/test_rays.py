"""层状模型与精确射线：钉住需求点名的全部核对关系。

两层基准模型：上层 h=1000 m、v=2000 m/s，下层 h=1000 m、v=3000 m/s。
第二界面：
    t0   = 2(1000/2000 + 1000/3000) = 5/3 s
    vrms = sqrt((2000·1000 + 3000·1000) / (1000/2000 + 1000/3000))
         = sqrt(6_000_000) ≈ 2449.4897 m/s
"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from app import nmo, rays
from app.layers import Layer, LayeredModel

BASE_LAYERS = (Layer(1000.0, 2000.0), Layer(1000.0, 3000.0))
T0_IF2 = 5.0 / 3.0
VRMS2_SQ = 6_000_000.0


def _model() -> LayeredModel:
    return LayeredModel(name="base", layers=BASE_LAYERS)


# --------------------------------------------------------------------------
# 基准模型手算值
# --------------------------------------------------------------------------


def test_two_layer_baseline_t0_and_vrms() -> None:
    """手算核对：第二界面 t0=5/3 s，vrms=sqrt(6e6)。"""
    summary = _model().interface(2)
    assert summary.depth == 2000.0
    assert math.isclose(summary.t0, T0_IF2, rel_tol=0.0, abs_tol=1e-15)
    assert math.isclose(summary.vrms ** 2, VRMS2_SQ, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(summary.vrms, 2449.489742783178, rel_tol=0.0, abs_tol=1e-9)


def test_first_interface_is_single_layer_vertical() -> None:
    summary = _model().interface(1)
    assert summary.t0 == 1.0
    assert summary.vrms == 2000.0


def test_all_interfaces_listed_top_down(client: TestClient) -> None:
    response = client.put(
        "/models/base",
        json={"layers": [
            {"thickness": 1000.0, "velocity": 2000.0},
            {"thickness": 1000.0, "velocity": 3000.0},
        ]},
    )
    assert response.status_code == 200
    interfaces = response.json()["interfaces"]
    assert [row["index"] for row in interfaces] == [1, 2]
    assert math.isclose(interfaces[1]["t0"], T0_IF2, abs_tol=1e-15)
    assert math.isclose(interfaces[1]["vrms"] ** 2, VRMS2_SQ, abs_tol=1e-9)


# --------------------------------------------------------------------------
# 关系一：单层时精确走时与原单点双曲走时一致（≤ 1e-9 s）
# --------------------------------------------------------------------------


def test_single_layer_exact_matches_hyperbolic_point() -> None:
    model = LayeredModel(name="one", layers=(Layer(1200.0, 2350.0),))
    for offset in (0.0, 1.0, 250.0, 3000.0, 60000.0):
        point = rays.trace_ray(model, 1, offset)
        expected = nmo.traveltime(model.interface(1).t0, 2350.0, abs(offset))
        assert abs(point.exact_time - expected) <= 1e-9
        assert abs(point.difference) <= 1e-9


# --------------------------------------------------------------------------
# 关系二：dt/dx = p（小步长中心差分，相对误差 ≤ 1e-6）
# --------------------------------------------------------------------------


def test_traveltime_slope_equals_ray_parameter() -> None:
    model = _model()
    for offset in (100.0, 500.0, 2000.0, 8000.0, 20000.0):
        point = rays.trace_ray(model, 2, offset)
        step = offset * 1e-5
        forward = rays.trace_ray(model, 2, offset + step).exact_time
        backward = rays.trace_ray(model, 2, offset - step).exact_time
        slope = (forward - backward) / (2.0 * step)
        assert point.ray_parameter > 0.0
        assert abs(slope - point.ray_parameter) / point.ray_parameter <= 1e-6


# --------------------------------------------------------------------------
# 关系三：小偏移残差按四次方缩，炮检距减半差至少缩小到 1/8
# --------------------------------------------------------------------------


def test_small_offset_difference_shrinks_quartically() -> None:
    model = _model()
    for offset in (200.0, 100.0, 50.0):
        big = abs(rays.trace_ray(model, 2, offset).difference)
        small = abs(rays.trace_ray(model, 2, offset / 2.0).difference)
        assert big > 0.0
        # 四次方缩的理论比值是 16；口径只要求 ≥ 8
        assert small * 8.0 <= big
    # x=0 时差严格为零
    assert rays.trace_ray(model, 2, 0.0).difference == 0.0


def test_exact_time_is_below_hyperbola_at_far_offsets() -> None:
    """远道精确走时小于双曲近似——单速度双曲把远道过校正，残差非候选速度可消。"""
    model = _model()
    point = rays.trace_ray(model, 2, 3000.0)
    assert point.difference < 0.0
    assert point.exact_time < point.hyperbolic_time


# --------------------------------------------------------------------------
# 关系四：20 倍界面深度、层间速度比 5 倍以上仍收敛，复算炮检距误差 ≤ 1 mm
# --------------------------------------------------------------------------


def test_extreme_offset_and_velocity_contrast_converges() -> None:
    model = LayeredModel(
        name="hard",
        layers=(Layer(1000.0, 1000.0), Layer(1000.0, 5001.0)),  # 速度比 5.001
    )
    depth = model.interface(2).depth
    offset = 20.0 * depth  # 40000 m
    point = rays.trace_ray(model, 2, offset)
    assert math.isfinite(point.exact_time)
    assert math.isfinite(point.ray_parameter)
    assert abs(point.recomputed_offset - offset) <= 1e-3  # 1 mm

    # 最快层在上覆、目标层更慢的情形同样收敛
    flipped = LayeredModel(
        name="flipped",
        layers=(Layer(800.0, 5200.0), Layer(1200.0, 1000.0)),
    )
    offset = 20.0 * flipped.interface(2).depth
    point = rays.trace_ray(flipped, 2, offset)
    assert abs(point.recomputed_offset - offset) <= 1e-3

    # 更硬：速度比 10、40 倍界面深度且高速层仅 50 m 厚，p·v_fast 已极接近 1
    sharp = LayeredModel(
        name="sharp",
        layers=(Layer(2000.0, 1800.0), Layer(50.0, 18000.0)),
    )
    offset = 40.0 * sharp.interface(2).depth
    point = rays.trace_ray(sharp, 2, offset)
    assert math.isfinite(point.exact_time)
    assert abs(point.recomputed_offset - offset) <= 1e-3


# --------------------------------------------------------------------------
# 零偏移、正负炮检距
# --------------------------------------------------------------------------


def test_zero_offset_is_vertical_ray() -> None:
    model = _model()
    point = rays.trace_ray(model, 2, 0.0)
    vertical_t0 = model.interface(2).t0
    assert point.ray_parameter == 0.0
    assert point.exact_time == vertical_t0
    assert point.hyperbolic_time == vertical_t0
    assert point.difference == 0.0
    assert point.recomputed_offset == 0.0
    assert math.isclose(point.exact_time, T0_IF2, rel_tol=0.0, abs_tol=1e-15)


def test_offset_sign_equivalent() -> None:
    model = _model()
    plus = rays.trace_ray(model, 2, 2500.0)
    minus = rays.trace_ray(model, 2, -2500.0)
    assert minus.offset == -2500.0  # 请求符号保留
    assert minus.exact_time == plus.exact_time
    assert minus.ray_parameter == plus.ray_parameter
    assert minus.recomputed_offset == plus.recomputed_offset


# --------------------------------------------------------------------------
# 曲线逐点与单点完全一致
# --------------------------------------------------------------------------


def test_curve_points_identical_to_single_requests() -> None:
    model = _model()
    offsets = [0.0, 125.0, 1000.0, 3333.0, 12000.0]
    curve = rays.trace_curve(model, 2, offsets)
    assert math.isclose(curve.t0, T0_IF2, rel_tol=0.0, abs_tol=1e-15)
    assert [point.offset for point in curve.points] == offsets
    for offset, point in zip(offsets, curve.points):
        single = rays.trace_ray(model, 2, offset)
        assert point == single


def test_extreme_case_recomputed_offset_via_http(client: TestClient) -> None:
    client.put(
        "/models/hard",
        json={"layers": [
            {"thickness": 1000.0, "velocity": 1000.0},
            {"thickness": 1000.0, "velocity": 5001.0},
        ]},
    )
    offset = 40000.0
    data = client.post(
        "/models/hard/interfaces/2/ray/point",
        json={"model": "hard", "interface": 2, "offset": offset},
    ).json()
    assert abs(data["recomputed_offset"] - offset) <= 1e-3
    assert data["ray_parameter"] > 0.0
    assert data["difference"] <= 0.0  # 多层远道：精确不高于双曲


def test_curve_via_http_matches_single_endpoint(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [
            {"thickness": 1000.0, "velocity": 2000.0},
            {"thickness": 1000.0, "velocity": 3000.0},
        ]},
    )
    offsets = [0.0, 500.0, 2000.0, 6000.0]
    curve = client.post(
        "/models/base/interfaces/2/ray/curve",
        json={"model": "base", "interface": 2, "offsets": offsets},
    ).json()
    for offset, point in zip(offsets, curve["points"]):
        single = client.post(
            "/models/base/interfaces/2/ray/point",
            json={"model": "base", "interface": 2, "offset": offset},
        ).json()
        assert point == single


# --------------------------------------------------------------------------
# 非法输入：计算启动前带原因打回
# --------------------------------------------------------------------------


def test_interface_out_of_range_rejected(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [
            {"thickness": 1000.0, "velocity": 2000.0},
            {"thickness": 1000.0, "velocity": 3000.0},
        ]},
    )
    for bad in (0, 3, -1):
        response = client.post(
            f"/models/base/interfaces/{bad}/ray/point",
            json={"model": "base", "interface": bad, "offset": 100.0},
        )
        assert response.status_code == 400
        assert "界面" in response.json()["reason"]

    # 路径不是整数写法
    response = client.post(
        "/models/base/interfaces/2x/ray/point",
        json={"model": "base", "interface": 2, "offset": 100.0},
    )
    assert response.status_code == 400


def test_offset_grid_empty_or_unordered_rejected(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [{"thickness": 1000.0, "velocity": 2000.0}]},
    )
    body = {"model": "base", "interface": 1, "offsets": []}
    response = client.post("/models/base/interfaces/1/ray/curve", json=body)
    assert response.status_code == 400
    assert "不能为空" in response.json()["reason"]

    body["offsets"] = [2000.0, 1000.0]
    response = client.post("/models/base/interfaces/1/ray/curve", json=body)
    assert response.status_code == 400
    assert "严格递增" in response.json()["reason"]


def test_layer_count_out_of_range_rejected(client: TestClient) -> None:
    response = client.put("/models/empty", json={"layers": []})
    assert response.status_code == 400
    assert "不能为空" in response.json()["reason"]

    response = client.put(
        "/models/toomany",
        json={"layers": [{"thickness": 100.0, "velocity": 2000.0}] * 31},
    )
    assert response.status_code == 400
    assert "最多 30" in response.json()["reason"]


def test_thickness_velocity_must_be_finite_positive(client: TestClient) -> None:
    for bad_layer, fragment in (
        ({"thickness": 0.0, "velocity": 2000.0}, "thickness 必须为有限正数"),
        ({"thickness": -5.0, "velocity": 2000.0}, "thickness 必须为有限正数"),
        ({"thickness": 100.0, "velocity": 0.0}, "velocity 必须为有限正数"),
        ({"thickness": 100.0, "velocity": -2.0}, "velocity 必须为有限正数"),
        ({"thickness": "nan", "velocity": 2000.0}, "有限数值"),
        ({"thickness": 100.0, "velocity": "infinity"}, "有限数值"),
    ):
        response = client.put("/models/bad", json={"layers": [bad_layer]})
        assert response.status_code == 400
        assert fragment in response.json()["reason"]

    # 缺字段、形状不对也在计算前拦下
    assert client.put("/models/bad", json={"layers": [{"thickness": 1.0}]}).status_code == 400
    assert client.put("/models/bad", json={"layers": [1.0, 2.0]}).status_code == 400


def test_ray_offset_must_be_finite(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [{"thickness": 1000.0, "velocity": 2000.0}]},
    )
    response = client.post(
        "/models/base/interfaces/1/ray/point",
        json={"model": "base", "interface": 1, "offset": "nan"},
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# 模型命名空间与易失性
# --------------------------------------------------------------------------


def test_model_store_lifecycle(client: TestClient) -> None:
    assert client.get("/models").json()["models"] == []
    response = client.put(
        "/models/A",
        json={"layers": [{"thickness": 500.0, "velocity": 1800.0}]},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "A"
    assert client.get("/models/A").status_code == 200
    assert client.delete("/models/A").status_code == 200
    assert client.get("/models/A").status_code == 404


def test_models_ephemeral() -> None:
    from app.main import create_app

    first = TestClient(create_app())
    first.put("/models/A", json={"layers": [{"thickness": 1.0, "velocity": 2.0}]})
    assert first.get("/models/A").status_code == 200
    restarted = TestClient(create_app())
    assert restarted.get("/models/A").status_code == 404


def test_model_and_profile_namespaces_independent(client: TestClient) -> None:
    """同名模型与动校档互不覆盖。"""
    client.put(
        "/models/same",
        json={"layers": [{"thickness": 1000.0, "velocity": 2000.0}]},
    )
    client.put("/profiles/same", json={"t0": 9.0, "velocity": 4242.0})

    model = client.get("/models/same").json()
    profile = client.get("/profiles/same").json()
    assert model["interfaces"][0]["vrms"] == 2000.0
    assert profile["velocity"] == 4242.0

    # 删模型不影响动校档，反之亦然
    client.delete("/models/same")
    assert client.get("/profiles/same").status_code == 200
    assert client.get("/models/same").status_code == 404


# --------------------------------------------------------------------------
# 从界面生动校档，接回原有三个接口
# --------------------------------------------------------------------------


def test_profile_generated_from_interface_works_everywhere(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [
            {"thickness": 1000.0, "velocity": 2000.0},
            {"thickness": 1000.0, "velocity": 3000.0},
        ]},
    )
    response = client.post("/models/base/interfaces/2/profile", json={"profile": "if2"})
    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "if2"
    assert math.isclose(created["t0"], T0_IF2, abs_tol=1e-15)
    assert math.isclose(created["velocity"] ** 2, VRMS2_SQ, abs_tol=1e-9)

    offset = 1500.0
    via_profile = client.post(
        "/nmo/point", json={"profile": "if2", "offset": offset}
    ).json()
    inline = client.post(
        "/nmo/point",
        json={"t0": created["t0"], "velocity": created["velocity"], "offset": offset},
    ).json()
    assert via_profile == inline

    curve = client.post(
        "/nmo/curve", json={"profile": "if2", "offsets": [0.0, 1500.0]}
    ).json()
    assert curve["traveltimes"] == [inline["t0"], inline["traveltime"]]

    # 扫描以该界面的 (t0, vrms) 定义同相轴：vrms 候选必须最平（评分 0）
    scan = client.post(
        "/nmo/scan",
        json={
            "profile": "if2",
            "offsets": [0.0, 500.0, 1000.0, 2000.0],
            "velocities": [2200.0, created["velocity"], 2700.0],
        },
    ).json()
    assert scan["best_velocity"] == created["velocity"]
    assert scan["best_flatness"] == 0.0


def test_profile_generated_with_default_name_uses_model_name(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [{"thickness": 1000.0, "velocity": 2000.0}]},
    )
    response = client.post("/models/base/interfaces/1/profile")
    assert response.status_code == 200
    assert response.json()["name"] == "base"
    # 落在动校档命名空间，模型本身不受影响
    assert client.get("/models/base").status_code == 200
    assert client.get("/profiles/base").status_code == 200


def test_profile_generation_bad_interface_rejected(client: TestClient) -> None:
    client.put(
        "/models/base",
        json={"layers": [{"thickness": 1000.0, "velocity": 2000.0}]},
    )
    response = client.post("/models/base/interfaces/2/profile")
    assert response.status_code == 400
    assert "越界" in response.json()["reason"]
