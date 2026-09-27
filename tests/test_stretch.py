"""浅层大偏移拉伸告警：超过阈值只标记、不拒绝，走时照实返回。"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient


def test_shallow_large_offset_flags_stretch_but_returns_value(client: TestClient) -> None:
    # t0=0.5 s、v=2000、x=2000 m：Δt/t0 明显超过 10%
    t0, velocity, offset = 0.5, 2000.0, 2000.0
    response = client.post(
        "/nmo/point",
        json={"t0": t0, "velocity": velocity, "offset": offset},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["stretched"] is True
    assert data["stretch_ratio"] > data["stretch_threshold"]
    # 走时值照实给，与开方公式一致
    assert data["traveltime"] == math.sqrt(t0**2 + (offset / velocity) ** 2)
    assert data["moveout"] == data["traveltime"] - t0


def test_below_threshold_not_flagged(client: TestClient) -> None:
    response = client.post(
        "/nmo/point",
        json={"t0": 2.0, "velocity": 2000.0, "offset": 1000.0},
    )
    data = response.json()
    assert data["stretched"] is False
    assert math.isclose(data["stretch_ratio"], (math.sqrt(4.25) - 2.0) / 2.0)


def test_custom_threshold(client: TestClient) -> None:
    body = {"t0": 2.0, "velocity": 2000.0, "offset": 1000.0}
    loose = client.post("/nmo/point", json={**body, "stretch_threshold": 0.02}).json()
    strict = client.post("/nmo/point", json={**body, "stretch_threshold": 0.5}).json()
    assert loose["stretched"] is True
    assert strict["stretched"] is False


def test_curve_carries_stretch_flags(client: TestClient) -> None:
    response = client.post(
        "/nmo/curve",
        json={
            "t0": 0.5,
            "velocity": 2000.0,
            "offsets": [0.0, 200.0, 1000.0, 2000.0],
            "stretch_threshold": 0.1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["stretched"] == [False, False, True, True]
    assert data["stretch_ratios"][0] == 0.0
    assert data["traveltimes"][0] == 0.5
