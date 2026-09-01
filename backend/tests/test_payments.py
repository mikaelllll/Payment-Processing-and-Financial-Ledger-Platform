from fastapi.testclient import TestClient


def payment_payload(**overrides):
    payload = {
        "merchant_id": "mer_demo",
        "amount": 10000,
        "currency": "BRL",
        "customer_reference": "customer-test",
        "idempotency_key": "order-test-1",
        "scenario": "success",
        "capture_method": "automatic",
    }
    return payload | overrides


def test_payment_capture_posts_balanced_ledger(client: TestClient):
    result = client.post(
        "/api/payments", headers={"X-Demo-Role": "merchant_owner"}, json=payment_payload()
    )
    assert result.status_code == 201
    body = result.json()
    assert body["payment"]["status"] == "captured"
    ledger = client.get(
        f"/api/payments/{body['payment']['id']}/ledger", headers={"X-Demo-Role": "merchant_owner"}
    )
    assert ledger.status_code == 200
    assert ledger.json()["balanced"] is True
    assert sum(row["debit"] for row in ledger.json()["entries"]) == 10000
    assert sum(row["credit"] for row in ledger.json()["entries"]) == 10000


def test_idempotent_replay_does_not_charge_twice(client: TestClient):
    first = client.post(
        "/api/payments", headers={"X-Demo-Role": "merchant_owner"}, json=payment_payload()
    ).json()
    second = client.post(
        "/api/payments", headers={"X-Demo-Role": "merchant_owner"}, json=payment_payload()
    ).json()
    assert second["replayed"] is True
    assert second["payment"]["id"] == first["payment"]["id"]
    ledger = client.get(
        f"/api/payments/{first['payment']['id']}/ledger", headers={"X-Demo-Role": "merchant_owner"}
    ).json()
    assert len(ledger["entries"]) == 3


def test_idempotency_key_conflict_is_rejected(client: TestClient):
    client.post("/api/payments", headers={"X-Demo-Role": "merchant_owner"}, json=payment_payload())
    conflict = client.post(
        "/api/payments",
        headers={"X-Demo-Role": "merchant_owner"},
        json=payment_payload(amount=20000),
    )
    assert conflict.status_code == 409


def test_ambiguous_result_recovers_without_duplicate(client: TestClient):
    result = client.post(
        "/api/payments",
        headers={"X-Demo-Role": "merchant_developer"},
        json=payment_payload(scenario="ambiguous"),
    ).json()
    assert result["payment"]["status"] == "captured"
    assert any(step["key"] == "recovery" for step in result["steps"])
    ledger = client.get(
        f"/api/payments/{result['payment']['id']}/ledger",
        headers={"X-Demo-Role": "merchant_developer"},
    ).json()
    assert ledger["balanced"] is True
    assert len({entry["transaction_id"] for entry in ledger["entries"]}) == 1


def test_decline_creates_no_ledger_movement(client: TestClient):
    result = client.post(
        "/api/payments",
        headers={"X-Demo-Role": "merchant_owner"},
        json=payment_payload(scenario="declined"),
    ).json()
    ledger = client.get(
        f"/api/payments/{result['payment']['id']}/ledger", headers={"X-Demo-Role": "merchant_owner"}
    ).json()
    assert result["payment"]["status"] == "failed"
    assert ledger["entries"] == []


def test_partial_and_full_refund_preserve_balance(client: TestClient):
    payment = client.post(
        "/api/payments", headers={"X-Demo-Role": "merchant_owner"}, json=payment_payload()
    ).json()["payment"]
    partial = client.post(
        f"/api/payments/{payment['id']}/refund",
        headers={"X-Demo-Role": "merchant_owner"},
        json={"amount": 4000, "idempotency_key": "refund-1"},
    )
    assert partial.json()["payment"]["status"] == "partially_refunded"
    final = client.post(
        f"/api/payments/{payment['id']}/refund",
        headers={"X-Demo-Role": "merchant_owner"},
        json={"amount": 6000, "idempotency_key": "refund-2"},
    )
    assert final.json()["payment"]["status"] == "refunded"
    ledger = client.get(
        f"/api/payments/{payment['id']}/ledger", headers={"X-Demo-Role": "merchant_owner"}
    ).json()
    assert ledger["balanced"] is True


def test_refund_cannot_exceed_capture(client: TestClient):
    payment = client.post(
        "/api/payments", headers={"X-Demo-Role": "merchant_owner"}, json=payment_payload()
    ).json()["payment"]
    response = client.post(
        f"/api/payments/{payment['id']}/refund",
        headers={"X-Demo-Role": "merchant_owner"},
        json={"amount": 10001, "idempotency_key": "refund-too-large"},
    )
    assert response.status_code == 409


def test_refund_replay_does_not_post_twice(client: TestClient):
    payment = client.post(
        "/api/payments",
        headers={"X-Demo-Role": "merchant_owner"},
        json=payment_payload(),
    ).json()["payment"]
    payload = {"amount": 2500, "idempotency_key": "stable-refund-key"}
    first = client.post(
        f"/api/payments/{payment['id']}/refund",
        headers={"X-Demo-Role": "merchant_owner"},
        json=payload,
    ).json()
    second = client.post(
        f"/api/payments/{payment['id']}/refund",
        headers={"X-Demo-Role": "merchant_owner"},
        json=payload,
    ).json()
    assert second["replayed"] is True
    assert second["payment"]["refunded_amount"] == first["payment"]["refunded_amount"]


def test_read_only_role_cannot_create_payment(client: TestClient):
    response = client.post(
        "/api/payments", headers={"X-Demo-Role": "auditor"}, json=payment_payload()
    )
    assert response.status_code == 403


def test_unknown_payment_ledger_returns_not_found(client: TestClient):
    response = client.get(
        "/api/payments/pay_missing/ledger",
        headers={"X-Demo-Role": "merchant_owner"},
    )
    assert response.status_code == 404
