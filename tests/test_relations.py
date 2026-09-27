"""钉死动校关系与基准算例（含需求点名的三条核心关系）。"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from app import curve, nmo

T0 = 2.0
VELOCITY = 2000.0


def test_zero_offset_moveout_is_zero(client: TestClient) -> None:
    """关系一：炮检距为零，校正量为零（走时严格等于 t0）。"""
    response = client.post(
        "/nmo/point",
        json={"t0": T0, "velocity": VELOCITY, "offset": 0.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["moveout"] == 0.0
    assert data["traveltime"] == T0
    assert data["stretched"] is False

    # 不同 t0/速度再验一遍内核本身
    for t0, v in [(0.5, 1500.0), (3.0, 3200.0)]:
        point = nmo.compute(t0, v, 0.0)
        assert point["moveout"] == 0.0
        assert point["traveltime"] == t0


def test_offset_abs_doubled_quadruples_offset_square_term(client: TestClient) -> None:
    """关系二：炮检距绝对值放大一倍，公式里的炮检距平方项（t²-t0²）变四倍。

    不做 t²-t0² 反算（4 附近相消会吞掉精度），而是直接核对：
    炮检距翻倍后，平方项应当等于原平方项的 4 倍——即
    t(2x)² == t0² + 4·(t(x)²-t0²)；负号炮检距进公式的是平方，同样成立。
    """
    for x in (250.0, 1000.0):
        small = client.post(
            "/nmo/point", json={"t0": T0, "velocity": VELOCITY, "offset": x}
        ).json()
        for doubled in (2 * x, -2 * x):  # 正负炮检距都验
            big = client.post(
                "/nmo/point",
                json={"t0": T0, "velocity": VELOCITY, "offset": doubled},
            ).json()
            expected_sq = T0 * T0 + 4.0 * (small["traveltime"] ** 2 - T0 * T0)
            assert math.isclose(big["traveltime"] ** 2, expected_sq, rel_tol=0.0, abs_tol=1e-12)
        # 正负同绝对值走时完全一致
        plus = client.post(
            "/nmo/point", json={"t0": T0, "velocity": VELOCITY, "offset": x}
        ).json()
        minus = client.post(
            "/nmo/point", json={"t0": T0, "velocity": VELOCITY, "offset": -x}
        ).json()
        assert plus["traveltime"] == minus["traveltime"]


def test_velocity_doubled_quarters_offset_square_term(client: TestClient) -> None:
    """附加关系：叠加速度放大一倍，x²/v² 项变四分之一。

    直接核对 t(v)²-t0² = 4·(t(2v)²-t0²)，避免近 4 处相消放大误差。
    """
    x = 1000.0
    t_v = client.post(
        "/nmo/point", json={"t0": T0, "velocity": VELOCITY, "offset": x}
    ).json()["traveltime"]
    t_2v = client.post(
        "/nmo/point", json={"t0": T0, "velocity": 2 * VELOCITY, "offset": x}
    ).json()["traveltime"]
    assert math.isclose(
        t_v**2 - T0 * T0,
        4.0 * (t_2v**2 - T0 * T0),
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    # 极限情形（小 t0）下也要成立
    t_v = nmo.traveltime(0.2, 1500.0, 600.0)
    t_2v = nmo.traveltime(0.2, 3000.0, 600.0)
    assert math.isclose(
        t_v**2 - 0.04, 4.0 * (t_2v**2 - 0.04), rel_tol=0.0, abs_tol=1e-12
    )


def test_curve_matches_single_point_everywhere(client: TestClient) -> None:
    """关系三：整条双曲线各点取值与单点接口同参结果完全一致。"""
    offsets = [0.0, 250.0, -500.0, 1000.0, 1750.0, 3000.0]
    # 接口层曲线用严格递增网格；负号炮检距由单点接口侧另验平方等价
    curve_offsets = [0.0, 250.0, 500.0, 1000.0, 1750.0, 3000.0]

    response = client.post(
        "/nmo/curve",
        json={"t0": T0, "velocity": VELOCITY, "offsets": curve_offsets},
    )
    assert response.status_code == 200
    curve_data = response.json()

    for offset, curve_t, curve_moveout in zip(
        curve_offsets, curve_data["traveltimes"], curve_data["moveouts"]
    ):
        point = client.post(
            "/nmo/point",
            json={"t0": T0, "velocity": VELOCITY, "offset": offset},
        ).json()
        assert curve_t == point["traveltime"]
        assert curve_moveout == point["moveout"]

    # 负炮检距与正炮检距走时相同（平方项）
    for offset in offsets:
        assert nmo.traveltime(T0, VELOCITY, offset) == nmo.traveltime(
            T0, VELOCITY, -offset
        )

    # 再直测曲线块与单点块，逐位完全相等（不设容差）
    built = curve.build_curve(T0, VELOCITY, curve_offsets)
    for offset, curve_t in zip(curve_offsets, built["traveltimes"]):
        assert curve_t == nmo.traveltime(T0, VELOCITY, offset)


def test_baseline_case_regression() -> None:
    """基准算例：t0=2 s、v=2000 m/s、x=1000 m。

    t = sqrt(2^2 + 1000^2/2000^2) = sqrt(4.25)
    Δt = sqrt(4.25) - 2
    """
    point = nmo.compute(T0, VELOCITY, 1000.0)
    expected_traveltime = math.sqrt(4.25)
    assert point["traveltime"] == expected_traveltime
    assert math.isclose(point["traveltime"], 2.0615528128088303, rel_tol=0.0, abs_tol=1e-15)
    assert point["moveout"] == expected_traveltime - T0
    assert math.isclose(point["moveout"], 0.0615528128088303, rel_tol=0.0, abs_tol=1e-15)
    # 拉伸比约 0.0308，低于默认 0.10 阈值，不告警
    assert point["moveout"] / T0 < 0.10
