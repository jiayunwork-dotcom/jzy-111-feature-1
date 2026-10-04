"""层状速度模型：存取、重启易失、与动校档名字空间相互独立。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _put_base(client: TestClient) -> object:
    return client.put(
        "/velocity-models/base",
        json={
            "layers": [
                {"thickness": 1000.0, "velocity": 2000.0},
                {"thickness": 1000.0, "velocity": 3000.0},
            ]
        },
    )


def test_model_lifecycle(client: TestClient) -> None:
    assert client.get("/velocity-models").json()["models"] == []

    response = _put_base(client)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "base"
    assert data["layers"] == [
        {"index": 0, "thickness": 1000.0, "velocity": 2000.0},
        {"index": 1, "thickness": 1000.0, "velocity": 3000.0},
    ]

    response = client.get("/velocity-models/base")
    assert response.status_code == 200
    assert response.json()["name"] == "base"

    # 覆盖更新
    client.put(
        "/velocity-models/base",
        json={"layers": [{"thickness": 500.0, "velocity": 1800.0}]},
    )
    updated = client.get("/velocity-models/base").json()
    assert len(updated["layers"]) == 1
    assert updated["layers"][0]["velocity"] == 1800.0

    assert client.delete("/velocity-models/base").status_code == 200
    missing = client.get("/velocity-models/base")
    assert missing.status_code == 404
    assert "不存在" in missing.json()["reason"]
    assert client.delete("/velocity-models/base").status_code == 404


def test_models_are_ephemeral() -> None:
    """重启（新应用实例）后速度模型与动校档一样丢失。"""
    first = TestClient(create_app())
    _put_base(first)
    assert first.get("/velocity-models/base").status_code == 200

    restarted = TestClient(create_app())
    assert restarted.get("/velocity-models/base").status_code == 404


def test_model_and_profile_namespaces_independent(client: TestClient) -> None:
    """同名 model 与 profile 互不覆盖；删一个不动另一个。"""
    _put_base(client)
    client.put("/profiles/base", json={"t0": 1.0, "velocity": 999.0})

    # 模型侧仍是两层 2000/3000
    model = client.get("/velocity-models/base").json()
    assert len(model["layers"]) == 2
    assert model["layers"][1]["velocity"] == 3000.0

    # 动校档侧仍是 (1.0, 999)
    profile = client.get("/profiles/base").json()
    assert profile == {"name": "base", "t0": 1.0, "velocity": 999.0}

    # 删模型不删档，删档不删模型
    client.delete("/velocity-models/base")
    assert client.get("/profiles/base").status_code == 200
    client.put("/profiles/other", json={"t0": 2.0, "velocity": 2000.0})
    _put_base(client)
    client.delete("/profiles/other")
    assert client.get("/velocity-models/base").status_code == 200


def test_model_name_validation(client: TestClient) -> None:
    response = client.put(
        "/velocity-models/   ",
        json={"layers": [{"thickness": 1.0, "velocity": 1000.0}]},
    )
    # 路径里只有空白：空白名字在领域校验处带原因打回
    assert response.status_code == 400
    assert "非空字符串" in response.json()["reason"]


def test_list_returns_all_models(client: TestClient) -> None:
    _put_base(client)
    client.put(
        "/velocity-models/other",
        json={"layers": [{"thickness": 100.0, "velocity": 1500.0}]},
    )
    names = {m["name"] for m in client.get("/velocity-models").json()["models"]}
    assert names == {"base", "other"}
