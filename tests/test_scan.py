"""速度扫描：正确速度把双曲线拉得最平。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import scan


GRID = [0.0, 250.0, 500.0, 1000.0, 1500.0, 2000.0, 2500.0]
EVENT_VELOCITY = 2200.0
T0 = 2.0
CANDIDATES = [1600.0, 1800.0, 2000.0, 2200.0, 2400.0, 2800.0, 3200.0]


def test_scan_picks_true_velocity_flattest(client: TestClient) -> None:
    response = client.post(
        "/nmo/scan",
        json={
            "t0": T0,
            "event_velocity": EVENT_VELOCITY,
            "offsets": GRID,
            "velocities": CANDIDATES,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["best_velocity"] == EVENT_VELOCITY
    best = data["candidates"][data["best_index"]]
    # 用真实速度做动校正，各道残差应为零（完全校平）
    assert best["flatness"] == 0.0
    assert best["max_abs_deviation"] == 0.0

    # 其他候选速度的平整度严格更差，且离正确速度越远越不平
    flatnesses = [c["flatness"] for c in data["candidates"]]
    for i, v in enumerate(CANDIDATES):
        if v != EVENT_VELOCITY:
            assert flatnesses[i] > 0.0
    true_index = CANDIDATES.index(EVENT_VELOCITY)
    assert flatnesses[true_index - 1] < flatnesses[true_index - 2]
    assert flatnesses[true_index + 1] < flatnesses[true_index + 2]


def test_scan_with_direct_observed_times(client: TestClient) -> None:
    """直接给观测走时，扫描仍能找回事件速度。"""
    result_with_event = scan.scan_velocities(
        offsets=GRID,
        candidate_velocities=CANDIDATES,
        t0=T0,
        event_velocity=EVENT_VELOCITY,
    )
    observed = result_with_event.observed_times

    response = client.post(
        "/nmo/scan",
        json={"offsets": GRID, "velocities": CANDIDATES, "observed_times": observed},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["best_velocity"] == EVENT_VELOCITY
    assert data["t0"] == T0  # 取零偏移道观测值


def test_scan_empty_velocities_rejected_upfront(client: TestClient) -> None:
    """候选速度为空必须提前挡下，不能进循环。"""
    response = client.post(
        "/nmo/scan",
        json={"t0": T0, "event_velocity": EVENT_VELOCITY, "offsets": GRID, "velocities": []},
    )
    assert response.status_code == 400
    assert "不能为空" in response.json()["reason"]


def test_scan_bad_grid_rejected_upfront(client: TestClient) -> None:
    """网格端点次序不对 / 首端非零偏移，提前挡下。"""
    response = client.post(
        "/nmo/scan",
        json={
            "t0": T0,
            "event_velocity": EVENT_VELOCITY,
            "offsets": [3000.0, 0.0, 1000.0],
            "velocities": CANDIDATES,
        },
    )
    assert response.status_code == 400
    assert "递增" in response.json()["reason"]

    response = client.post(
        "/nmo/scan",
        json={
            "t0": T0,
            "event_velocity": EVENT_VELOCITY,
            "offsets": [250.0, 1000.0],
            "velocities": CANDIDATES,
        },
    )
    assert response.status_code == 400
    assert "首端为零" in response.json()["reason"]


def test_scan_requires_observation_source(client: TestClient) -> None:
    response = client.post(
        "/nmo/scan", json={"offsets": GRID, "velocities": CANDIDATES}
    )
    assert response.status_code == 400
    assert "event_velocity 或 observed_times" in response.json()["reason"]


def test_scan_profile_rejects_inline_event_params(client: TestClient) -> None:
    client.put("/profiles/A", json={"t0": 2.0, "velocity": 2000.0})
    response = client.post(
        "/nmo/scan",
        json={
            "profile": "A",
            "t0": 1.0,
            "event_velocity": 3000.0,
            "offsets": GRID,
            "velocities": CANDIDATES,
        },
    )
    assert response.status_code == 400
    assert "必须留空" in response.json()["reason"]
