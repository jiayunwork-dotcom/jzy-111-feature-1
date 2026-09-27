"""动校档：命名存取、重启易失、两份档扫描互不串参数。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_profile_lifecycle(client: TestClient) -> None:
    # 初始为空
    assert client.get("/profiles").json()["profiles"] == []

    response = client.put("/profiles/shallow-a", json={"t0": 0.6, "velocity": 1800.0})
    assert response.status_code == 200
    assert response.json() == {"name": "shallow-a", "t0": 0.6, "velocity": 1800.0}

    response = client.get("/profiles/shallow-a")
    assert response.status_code == 200
    assert response.json()["velocity"] == 1800.0

    # 覆盖更新
    client.put("/profiles/shallow-a", json={"t0": 0.8, "velocity": 1900.0})
    assert client.get("/profiles/shallow-a").json()["t0"] == 0.8

    assert client.delete("/profiles/shallow-a").status_code == 200
    assert client.get("/profiles/shallow-a").status_code == 404
    assert "不存在" in client.get("/profiles/shallow-a").json()["reason"]


def test_profile_invalid_params_rejected(client: TestClient) -> None:
    response = client.put("/profiles/bad", json={"t0": -1.0, "velocity": 2000.0})
    assert response.status_code == 400
    response = client.put("/profiles/bad", json={"t0": 1.0, "velocity": 0.0})
    assert response.status_code == 400


def test_profile_used_by_point_and_curve(client: TestClient) -> None:
    client.put("/profiles/base", json={"t0": 2.0, "velocity": 2000.0})

    via_profile = client.post(
        "/nmo/point", json={"profile": "base", "offset": 1000.0}
    ).json()
    inline = client.post(
        "/nmo/point", json={"t0": 2.0, "velocity": 2000.0, "offset": 1000.0}
    ).json()
    assert via_profile["traveltime"] == inline["traveltime"]

    curve_profile = client.post(
        "/nmo/curve", json={"profile": "base", "offsets": [0.0, 1000.0]}
    ).json()
    assert curve_profile["velocity"] == 2000.0
    assert curve_profile["traveltimes"] == [inline["t0"], inline["traveltime"]]


def test_profile_cannot_mix_with_inline(client: TestClient) -> None:
    client.put("/profiles/base", json={"t0": 2.0, "velocity": 2000.0})
    response = client.post(
        "/nmo/point", json={"profile": "base", "t0": 3.0, "offset": 0.0}
    )
    assert response.status_code == 400
    assert "不能同时" in response.json()["reason"]

    response = client.post(
        "/nmo/curve",
        json={"profile": "base", "velocity": 3000.0, "offsets": [0.0, 100.0]},
    )
    assert response.status_code == 400


def test_two_profiles_scans_do_not_cross_contaminate(client: TestClient) -> None:
    """两套动校档同时扫描，各自走自己的 t0/速度曲线，互不干扰。"""
    client.put("/profiles/A", json={"t0": 2.0, "velocity": 2000.0})
    client.put("/profiles/B", json={"t0": 1.2, "velocity": 2800.0})

    offsets = [0.0, 500.0, 1000.0, 1800.0, 2600.0]
    candidates = [1600.0, 2000.0, 2400.0, 2800.0, 3200.0]

    scan_a = client.post(
        "/nmo/scan", json={"profile": "A", "offsets": offsets, "velocities": candidates}
    ).json()
    scan_b = client.post(
        "/nmo/scan", json={"profile": "B", "offsets": offsets, "velocities": candidates}
    ).json()

    assert scan_a["best_velocity"] == 2000.0
    assert scan_b["best_velocity"] == 2800.0
    assert scan_a["t0"] == 2.0
    assert scan_b["t0"] == 1.2
    # 观测走时曲线各自来自本档，不串
    assert scan_a["observed_times"] != scan_b["observed_times"]
    assert scan_a["candidates"][0]["corrected_times"] != scan_b["candidates"][0]["corrected_times"]

    # A 档的曲线不会用到 B 档的速度
    curve_a = client.post(
        "/nmo/curve", json={"profile": "A", "offsets": offsets}
    ).json()
    expected_a = client.post(
        "/nmo/curve",
        json={"t0": 2.0, "velocity": 2000.0, "offsets": offsets},
    ).json()
    assert curve_a["traveltimes"] == expected_a["traveltimes"]


def test_profiles_are_ephemeral() -> None:
    """重启（新应用实例）后动校档丢失也没关系。"""
    from app.main import create_app

    first = TestClient(create_app())
    first.put("/profiles/base", json={"t0": 2.0, "velocity": 2000.0})
    assert first.get("/profiles/base").status_code == 200

    restarted = TestClient(create_app())
    assert restarted.get("/profiles/base").status_code == 404
