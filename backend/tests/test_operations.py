from fastapi.testclient import TestClient


def headers(role: str) -> dict[str, str]:
    return {"X-Demo-Role": role}


def test_every_role_receives_a_distinct_workspace(client: TestClient):
    expected = {
        "merchant_owner": {"available_balance", "settlements", "disputes", "authorized_payments"},
        "merchant_developer": {"webhook_endpoints", "deliveries", "api_keys", "request_traces"},
        "operations_admin": {"processors", "recovery_queue", "reconciliation", "pending_outbox"},
        "risk_analyst": {"risk_cases", "fraud_rules", "disputes"},
        "auditor": {"ledger_entries", "audit_events", "visible_balanced"},
    }
    for role, fields in expected.items():
        response = client.get("/api/workspace", headers=headers(role))
        assert response.status_code == 200
        assert fields <= response.json().keys()


def test_high_risk_review_can_be_approved_then_captured(client: TestClient):
    payment = client.post(
        "/api/payments",
        headers=headers("merchant_developer"),
        json={
            "merchant_id": "mer_demo",
            "amount": 25000,
            "currency": "BRL",
            "customer_reference": "risk-customer",
            "idempotency_key": "risk-payment-1",
            "scenario": "high_risk",
            "capture_method": "automatic",
        },
    ).json()["payment"]
    assert payment["status"] == "authorized"
    workspace = client.get("/api/workspace", headers=headers("risk_analyst")).json()
    case = next(item for item in workspace["risk_cases"] if item["payment_id"] == payment["id"])
    decision = client.post(
        f"/api/risk-cases/{case['id']}/decision",
        headers=headers("risk_analyst"),
        json={"action": "approve", "note": "Evidence accepted"},
    )
    assert decision.status_code == 200
    capture = client.post(
        f"/api/payments/{payment['id']}/capture",
        headers=headers("merchant_owner"),
        json={"action": "capture"},
    )
    assert capture.status_code == 200
    assert capture.json()["payment"]["status"] == "captured"


def test_settlement_is_idempotent_and_operations_controls_outcome(client: TestClient):
    payload = {"action": "create", "amount": 1000, "idempotency_key": "settlement-test-1"}
    first = client.post("/api/settlements", headers=headers("merchant_owner"), json=payload)
    assert first.status_code == 200
    second = client.post("/api/settlements", headers=headers("merchant_owner"), json=payload)
    assert second.json()["replayed"] is True
    settlement_id = first.json()["resource"]["id"]
    failed = client.post(
        f"/api/settlements/{settlement_id}/action",
        headers=headers("operations_admin"),
        json={"action": "fail"},
    )
    assert failed.json()["resource"]["status"] == "failed"
    retried = client.post(
        f"/api/settlements/{settlement_id}/action",
        headers=headers("operations_admin"),
        json={"action": "retry"},
    )
    assert retried.json()["resource"]["status"] == "pending"
    completed = client.post(
        f"/api/settlements/{settlement_id}/action",
        headers=headers("operations_admin"),
        json={"action": "complete"},
    )
    assert completed.json()["resource"]["status"] == "paid"


def test_developer_can_manage_hashed_credentials_and_webhooks(client: TestClient):
    created_key = client.post(
        "/api/api-keys",
        headers=headers("merchant_developer"),
        json={"name": "Test service", "value": "payments:read,payments:write"},
    )
    assert created_key.status_code == 200
    assert created_key.json()["secret"].startswith("lf_live_")
    assert "key_hash" in created_key.json()["resource"]
    key_id = created_key.json()["resource"]["id"]
    revoked = client.post(f"/api/api-keys/{key_id}/revoke", headers=headers("merchant_developer"))
    assert revoked.json()["resource"]["status"] == "revoked"

    webhook = client.post(
        "/api/webhooks",
        headers=headers("merchant_developer"),
        json={"name": "Production", "value": "https://merchant.example/webhooks"},
    )
    assert webhook.status_code == 200
    assert webhook.json()["secret"].startswith("whsec_")


def test_dispute_evidence_and_resolution_change_financial_state(client: TestClient):
    owner_view = client.get("/api/workspace", headers=headers("merchant_owner")).json()
    dispute = owner_view["disputes"][0]
    evidence = client.post(
        f"/api/disputes/{dispute['id']}/action",
        headers=headers("merchant_owner"),
        json={"action": "evidence", "note": "Proof of fulfillment"},
    )
    assert evidence.json()["resource"]["status"] == "under_review"
    won = client.post(
        f"/api/disputes/{dispute['id']}/action",
        headers=headers("risk_analyst"),
        json={"action": "win", "note": "Evidence accepted"},
    )
    assert won.json()["resource"]["status"] == "won"
    auditor = client.get("/api/workspace", headers=headers("auditor")).json()
    assert auditor["visible_balanced"] is True


def test_operations_controls_are_not_available_to_merchants(client: TestClient):
    operations = client.get("/api/workspace", headers=headers("operations_admin")).json()
    processor = operations["processors"][0]
    forbidden = client.post(
        f"/api/processors/{processor['id']}/health",
        headers=headers("merchant_owner"),
        json={"action": "offline"},
    )
    assert forbidden.status_code == 403
    changed = client.post(
        f"/api/processors/{processor['id']}/health",
        headers=headers("operations_admin"),
        json={"action": "offline"},
    )
    assert changed.json()["resource"]["health"] == "offline"
