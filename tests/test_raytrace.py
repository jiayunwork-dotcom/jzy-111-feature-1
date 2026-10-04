"""精确射线走时：钉死需求点名的全部物理关系与极端收敛。

基准两层模型（上层 1000 m/2000 m·s⁻¹，下层 1000 m/3000 m·s⁻¹）::

    t0(界面1) = 2·1000/2000 + 2·1000/3000 = 5/3 s
    vrms(界面1)² = (2000²·1 + 3000²·(2/3)) / (5/3) = 6 000 000
    vrms(界面1) = sqrt(6 000 000) ≈ 2449.4897 m/s
"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from app.raytrace import LayeredModel, trace_curve, trace_ray

TWO_LAYER = LayeredModel(
    name="base",
    layers=((1000.0, 2000.0), (1000.0, 3000.0)),
)
T0_BASELINE = 5.0 / 3.0
VRMS_BASELINE = math.sqrt(6_000_000)


# ---------- 基准回归：手算可核的 t0 / vrms ----------

def test_baseline_two_layer_interfaces(client: TestClient) -> None:
    """第二个界面 t0=5/3 s、vrms=sqrt(6,000,000)≈2449.49 m/s，钉进回归。"""
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
    interfaces = response.json()["interfaces"]

    first = interfaces[0]
    assert first["interface"] == 0
    assert first["depth"] == 1000.0
    assert math.isclose(first["t0"], 1.0, abs_tol=1e-12)
    assert math.isclose(first["vrms"], 2000.0, abs_tol=1e-9)

    second = interfaces[1]
    assert second["interface"] == 1
    assert second["depth"] == 2000.0
    assert math.isclose(second["t0"], T0_BASELINE, abs_tol=1e-12)
    assert math.isclose(second["vrms"], VRMS_BASELINE, abs_tol=1e-9)
    assert math.isclose(second["vrms"], 2449.489742783178, rel_tol=1e-9)


def test_baseline_kernel_values() -> None:
    """内核直算，绕开 HTTP 序列化再钉一遍。"""
    t0, vrms = TWO_LAYER.interface_stats(1)
    # 逐层累加 1.0 + 2/3 与直接 5/3 相差一个 ulp，按机器精度核
    assert math.isclose(t0, T0_BASELINE, abs_tol=1e-15)
    assert math.isclose(vrms, VRMS_BASELINE, rel_tol=1e-15)
    # 第一层底：垂直走时 1 s，rms 速度即层速度
    t0_0, vrms_0 = TWO_LAYER.interface_stats(0)
    assert t0_0 == 1.0
    assert vrms_0 == 2000.0


# ---------- 关系一：单层精确走时与原有单点双曲线一致（≤1e-9 s） ----------

def test_single_layer_exact_matches_legacy_point(client: TestClient) -> None:
    client.put(
        "/velocity-models/single",
        json={"layers": [{"thickness": 2000.0, "velocity": 2500.0}]},
    )
    single_t0 = 2.0 * 2000.0 / 2500.0
    for offset in (0.0, 1.0, 100.0, 1000.0, 4000.0, 10000.0, -2500.0):
        ray = client.post(
            "/ray/point",
            json={"model": "single", "interface": 0, "offset": offset},
        ).json()
        legacy = client.post(
            "/nmo/point",
            json={"t0": single_t0, "velocity": 2500.0, "offset": offset},
        ).json()
        assert abs(ray["exact_traveltime"] - legacy["traveltime"]) <= 1e-9, (
            f"offset={offset}: exact={ray['exact_traveltime']!r} "
            f"legacy={legacy['traveltime']!r}"
        )
        # 与双曲近似之差也在 1e-9 内
        assert abs(ray["traveltime_difference"]) <= 1e-9


def test_single_layer_exact_kernel_identity() -> None:
    """单层模型数学上就是双曲，内核逐点恒等（仅舍入级差异）。"""
    model = LayeredModel(name="s", layers=((300.0, 1700.0),))
    t0 = 2.0 * 300.0 / 1700.0
    for offset in (0.0, 50.0, 3000.0, 9000.0):
        result = trace_ray(model, 0, offset)
        expected = math.sqrt(t0 * t0 + offset * offset / 1700.0**2)
        assert abs(result.exact_traveltime - expected) <= 1e-12


# ---------- 关系二：dt/dx = p（中心差分，相对误差 ≤1e-6） ----------

def test_traveltime_slope_equals_ray_parameter(client: TestClient) -> None:
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )

    def exact_at(x: float) -> tuple[float, float]:
        data = client.post(
            "/ray/point", json={"model": "base", "interface": 1, "offset": x}
        ).json()
        return data["exact_traveltime"], data["ray_parameter"]

    step = 0.01  # 1 cm：截断误差 O(h²) 与舍入误差都远小于 1e-6
    for offset in (100.0, 500.0, 1500.0, 3000.0, 6000.0):
        t_plus, _ = exact_at(offset + step)
        t_minus, _ = exact_at(offset - step)
        _, p = exact_at(offset)
        slope = (t_plus - t_minus) / (2.0 * step)
        relative_error = abs(slope - p) / p
        assert relative_error <= 1e-6, (
            f"x={offset}: slope={slope!r} p={p!r} relerr={relative_error}"
        )


def test_traveltime_slope_equals_ray_parameter_kernel() -> None:
    """内核层再多验几个模型，包括速度倒转与 30 层。"""
    models = [
        LayeredModel("inv", ((800.0, 3000.0), (600.0, 1800.0), (900.0, 2600.0))),
        LayeredModel(
            "thirty",
            tuple((100.0, 1500.0 + 100.0 * i) for i in range(30)),
        ),
    ]
    step = 0.01
    for model in models:
        interface = model.layer_count - 1
        for offset in (200.0, 2000.0, 10000.0):
            t_plus = trace_ray(model, interface, offset + step).exact_traveltime
            t_minus = trace_ray(model, interface, offset - step).exact_traveltime
            p = trace_ray(model, interface, offset).ray_parameter
            slope = (t_plus - t_minus) / (2.0 * step)
            assert abs(slope - p) / p <= 1e-8


# ---------- 关系三：小偏移时差 ~ O(x⁴)，减半至少缩到 1/8 ----------

def test_small_offset_difference_vanishes_quartically(client: TestClient) -> None:
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )

    def difference(x: float) -> float:
        return client.post(
            "/ray/point", json={"model": "base", "interface": 1, "offset": x}
        ).json()["traveltime_difference"]

    for offset in (50.0, 100.0, 200.0, 400.0):
        full = abs(difference(offset))
        half = abs(difference(offset / 2.0))
        assert half <= full / 8.0, f"x={offset}: d(x)={full}, d(x/2)={half}"
        # 小偏移时差本身很小且为负（精确走时位于 RMS 双曲线之下）
        assert difference(offset) < 0.0


def test_zero_offset_is_vertical_ray(client: TestClient) -> None:
    """零炮检距：p=0，精确走时严格等于垂直双程走时，与双曲之差为零。"""
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )
    data = client.post(
        "/ray/point", json={"model": "base", "interface": 1, "offset": 0.0}
    ).json()
    assert data["ray_parameter"] == 0.0
    assert math.isclose(data["exact_traveltime"], T0_BASELINE, abs_tol=1e-15)
    assert data["exact_traveltime"] == data["hyperbolic_traveltime"]
    assert data["traveltime_difference"] == 0.0
    assert data["recomputed_offset"] == 0.0


def test_negative_offset_uses_absolute_value(client: TestClient) -> None:
    """炮检距正负按绝对值处理：p 非负，结果与正炮检距完全一致。"""
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )
    for offset in (100.0, 1500.0, 5000.0):
        positive = client.post(
            "/ray/point", json={"model": "base", "interface": 1, "offset": offset}
        ).json()
        negative = client.post(
            "/ray/point",
            json={"model": "base", "interface": 1, "offset": -offset},
        ).json()
        assert negative["ray_parameter"] >= 0.0
        assert negative["exact_traveltime"] == positive["exact_traveltime"]
        assert negative["hyperbolic_traveltime"] == positive["hyperbolic_traveltime"]
        assert negative["ray_parameter"] == positive["ray_parameter"]
        assert negative["offset"] == -offset  # 原符号回显


# ---------- 关系四：20 倍深度、5 倍以上速度差也要收敛，复算误差 ≤1 mm ----------

def test_strong_contrast_twenty_times_depth_converges(client: TestClient) -> None:
    client.put(
        "/velocity-models/strong",
        json={
            "layers": [
                {"thickness": 500.0, "velocity": 1000.0},
                {"thickness": 500.0, "velocity": 5200.0},  # 5.2 倍速度差
            ]
        },
    )
    depth = 1000.0
    offset = 20.0 * depth  # 20 倍深度
    data = client.post(
        "/ray/point", json={"model": "strong", "interface": 1, "offset": offset}
    ).json()
    assert data["ray_parameter"] > 0.0
    assert abs(data["recomputed_offset"] - offset) <= 1e-3
    assert math.isfinite(data["exact_traveltime"])
    assert math.isfinite(data["ray_parameter"])
    assert data["ray_parameter"] * 5200.0 < 1.0  # 严格在临界角之内


def test_thirty_layers_large_offset_converges() -> None:
    """30 层、大炮检距也要毫米级复算。"""
    model = LayeredModel(
        "thirty",
        tuple((100.0, 1500.0 + 100.0 * i) for i in range(30)),
    )
    depth = 3000.0
    for offset in (20.0 * depth, 60000.0):
        result = trace_ray(model, 29, offset)
        assert abs(result.recomputed_offset - offset) <= 1e-3
        assert math.isfinite(result.exact_traveltime)
        assert result.ray_parameter * 4400.0 < 1.0


# ---------- 关系五：曲线逐点与单点请求完全一致 ----------

def test_curve_points_identical_to_single_point(client: TestClient) -> None:
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )
    grid = [0.0, 100.0, 500.0, 1000.0, 2500.0, 4000.0, 7500.0]
    curve = client.post(
        "/ray/curve", json={"model": "base", "interface": 1, "offsets": grid}
    ).json()
    for offset, point in zip(grid, curve["points"]):
        single = client.post(
            "/ray/point", json={"model": "base", "interface": 1, "offset": offset}
        ).json()
        assert point["exact_traveltime"] == single["exact_traveltime"]
        assert point["hyperbolic_traveltime"] == single["hyperbolic_traveltime"]
        assert point["ray_parameter"] == single["ray_parameter"]
        assert point["traveltime_difference"] == single["traveltime_difference"]
        assert point["recomputed_offset"] == single["recomputed_offset"]


def test_curve_kernel_reuses_point_kernel() -> None:
    """批量曲线与单点调用同一内核，逐位相等（不设容差）。"""
    grid = [0.0, 250.0, 3000.0]
    points = trace_curve(TWO_LAYER, 1, grid)
    for offset, point in zip(grid, points):
        single = trace_ray(TWO_LAYER, 1, offset)
        assert point.exact_traveltime == single.exact_traveltime
        assert point.ray_parameter == single.ray_parameter


def test_curve_with_signed_grid(client: TestClient) -> None:
    """带负值的严格递增网格同样可用，且逐点等于单点请求。"""
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )
    grid = [-3000.0, -1000.0, 0.0, 500.0, 2000.0]
    curve = client.post(
        "/ray/curve", json={"model": "base", "interface": 1, "offsets": grid}
    ).json()
    assert len(curve["points"]) == len(grid)
    for offset, point in zip(grid, curve["points"]):
        single = client.post(
            "/ray/point", json={"model": "base", "interface": 1, "offset": offset}
        ).json()
        assert point["exact_traveltime"] == single["exact_traveltime"]
        assert point["ray_parameter"] == single["ray_parameter"]
        assert point["offset"] == offset


def test_recomputed_offset_matches_request_everywhere(client: TestClient) -> None:
    """常规炮检距范围内复算炮检距与请求值之差不超过一毫米。"""
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )
    for offset in (1.0, 10.0, 1000.0, 10000.0, 30000.0):
        data = client.post(
            "/ray/point", json={"model": "base", "interface": 1, "offset": offset}
        ).json()
        assert abs(data["recomputed_offset"] - offset) <= 1e-3


def test_ray_parameter_monotonic_and_below_critical() -> None:
    """p 随炮检距单调增大且始终在最快层临界值之内。"""
    previous = -1.0
    for offset in (0.0, 100.0, 1000.0, 5000.0, 20000.0):
        result = trace_ray(TWO_LAYER, 1, offset)
        assert result.ray_parameter > previous or offset == 0.0
        assert result.ray_parameter * 3000.0 <= 1.0
        previous = result.ray_parameter
