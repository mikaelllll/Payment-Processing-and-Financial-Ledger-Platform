def seed(client, size: str) -> dict:
    response = client.post(
        "/api/demo/seed",
        headers={"X-Demo-Role": "merchant_owner"},
        json={"size": size, "reset": True},
    )
    assert response.status_code == 200
    return response.json()


def dashboard_count(client) -> int:
    response = client.get(
        "/api/dashboard", headers={"X-Demo-Role": "merchant_owner"}
    )
    assert response.status_code == 200
    return response.json()["metrics"]["payments"]


def test_dataset_sizes_replace_one_another_in_both_directions(client):
    for size, expected in (("small", 12), ("medium", 60), ("large", 250), ("small", 12)):
        result = seed(client, size)
        assert result["created"] == expected
        assert result["requested"] == expected
        assert result["reset"] is True
        assert dashboard_count(client) == expected


def test_reselecting_same_dataset_recreates_exact_size(client):
    first = seed(client, "medium")
    second = seed(client, "medium")

    assert first["created"] == second["created"] == 60
    assert dashboard_count(client) == 60
