"""第三块能力：从层状模型界面生成动校档，原有三个接口照常可用。"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient


def _create_base(client: TestClient) -> None:
    client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )


def test_generate_profile_carries_t0_vrms(client: TestClient) -> None:
    _create_base(client)
    response = client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 1, "profile_name": "event2"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["profile_name"] == "event2"
    assert data["model"] == "base"
    assert data["interface"] == 1
    assert math.isclose(data["t0"], 5.0 / 3.0, abs_tol=1e-12)
    assert math.isclose(data["velocity"], math.sqrt(6_000_000), abs_tol=1e-9)


def test_generated_profile_works_with_legacy_point(client: TestClient) -> None:
    _create_base(client)
    client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 1, "profile_name": "event2"},
    )
    ray = client.post(
        "/ray/point", json={"model": "base", "interface": 1, "offset": 1200.0}
    ).json()
    legacy = client.post(
        "/nmo/point", json={"profile": "event2", "offset": 1200.0}
    ).json()
    # 老接口走双曲，与射线接口给出的双曲近似逐位一致
    assert legacy["t0"] == ray["t0"]
    assert legacy["velocity"] == ray["vrms"]
    assert legacy["traveltime"] == ray["hyperbolic_traveltime"]
    assert legacy["moveout"] == ray["hyperbolic_traveltime"] - ray["t0"]


def test_generated_profile_works_with_legacy_curve(client: TestClient) -> None:
    _create_base(client)
    client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 0, "profile_name": "event1"},
    )
    offsets = [0.0, 250.0, 1000.0, 3000.0]
    legacy = client.post(
        "/nmo/curve", json={"profile": "event1", "offsets": offsets}
    ).json()
    # 第一界面 t0=1 s, v=2000
    assert legacy["t0"] == 1.0
    assert legacy["velocity"] == 2000.0
    expected = [
        math.sqrt(1.0 + x * x / 2000.0**2) for x in offsets
    ]
    assert legacy["traveltimes"] == expected
    assert legacy["moveouts"] == [t - 1.0 for t in expected]
    assert legacy["stretched"][0] is False


def test_generated_profile_works_with_legacy_scan(client: TestClient) -> None:
    _create_base(client)
    client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 1, "profile_name": "event2"},
    )
    vrms = math.sqrt(6_000_000)
    offsets = [0.0, 500.0, 1000.0, 2000.0]
    response = client.post(
        "/nmo/scan",
        json={
            "profile": "event2",
            "offsets": offsets,
            "velocities": [2000.0, vrms, 3000.0],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["best_velocity"] == vrms
    assert data["best_flatness"] == 0.0
    assert data["t0"] == client.get("/profiles/event2").json()["t0"]


def test_generated_profiles_for_different_interfaces(client: TestClient) -> None:
    _create_base(client)
    client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 0, "profile_name": "i0"},
    )
    client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 1, "profile_name": "i1"},
    )
    p0 = client.get("/profiles/i0").json()
    p1 = client.get("/profiles/i1").json()
    assert p0 == {"name": "i0", "t0": 1.0, "velocity": 2000.0}
    assert math.isclose(p1["t0"], 5.0 / 3.0, abs_tol=1e-12)
    assert math.isclose(p1["velocity"], math.sqrt(6_000_000), abs_tol=1e-9)


def test_profile_name_collides_only_with_profiles(client: TestClient) -> None:
    """生成档名取自档名字空间；与同名模型互不覆盖，同名再生成则覆盖该档。"""
    _create_base(client)
    # 模型叫 base，也允许生成一个叫 base 的动校档
    response = client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 0, "profile_name": "base"},
    )
    assert response.status_code == 200
    # 模型仍是两层
    model = client.get("/velocity-models/base").json()
    assert len(model["layers"]) == 2
    # 档是第一层界面参数
    profile = client.get("/profiles/base").json()
    assert profile["velocity"] == 2000.0

    # 再次生成到同档名：按动校档 PUT 语义覆盖
    client.post(
        "/velocity-models/profile",
        json={"model": "base", "interface": 1, "profile_name": "base"},
    )
    profile = client.get("/profiles/base").json()
    assert math.isclose(profile["velocity"], math.sqrt(6_000_000), abs_tol=1e-9)
    assert len(client.get("/velocity-models/base").json()["layers"]) == 2
