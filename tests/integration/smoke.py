"""End-to-end smoke test for a running LedgerFlow Docker Compose stack."""

from __future__ import annotations

import json
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:3000"


def request(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    role: str | None = None,
    expected: int = 200,
) -> dict[str, object] | str | None:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if role:
        headers["X-Demo-Role"] = role
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as response:
            status = response.status
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        status = exc.code
        raw = exc.read()
        content_type = exc.headers.get("Content-Type", "")

    assert status == expected, f"{method} {url}: expected {expected}, got {status}: {raw!r}"
    if not raw:
        return None
    return json.loads(raw) if "json" in content_type else raw.decode()


def main() -> None:
    health = request("GET", API_URL + "/api/health")
    assert isinstance(health, dict) and health["status"] == "healthy"
    assert request("GET", FRONTEND_URL + "/healthz") == "ok"

    suffix = uuid.uuid4().hex
    payment_payload = {
        "merchant_id": "mer_demo",
        "amount": 10000,
        "currency": "BRL",
        "customer_reference": f"integration-{suffix}",
        "idempotency_key": f"integration-payment-{suffix}",
        "scenario": "success",
        "capture_method": "automatic",
    }

    created = request(
        "POST",
        FRONTEND_URL + "/api/payments",
        payload=payment_payload,
        role="merchant_owner",
        expected=201,
    )
    assert isinstance(created, dict)
    assert created["payment"]["status"] == "captured"
    assert created["replayed"] is False
    payment_id = created["payment"]["id"]

    replayed = request(
        "POST",
        API_URL + "/api/payments",
        payload=payment_payload,
        role="merchant_owner",
        expected=201,
    )
    assert isinstance(replayed, dict)
    assert replayed["replayed"] is True
    assert replayed["payment"]["id"] == payment_id

    ledger = request(
        "GET",
        API_URL + f"/api/payments/{payment_id}/ledger",
        role="auditor",
    )
    assert isinstance(ledger, dict) and ledger["balanced"] is True
    entries = ledger["entries"]
    assert sum(entry["debit"] for entry in entries) == 10000
    assert sum(entry["credit"] for entry in entries) == 10000
    assert len({entry["transaction_id"] for entry in entries}) == 1

    denied_payload = {**payment_payload, "idempotency_key": f"auditor-denied-{suffix}"}
    request(
        "POST",
        API_URL + "/api/payments",
        payload=denied_payload,
        role="auditor",
        expected=403,
    )

    auditor_workspace = request(
        "GET",
        API_URL + "/api/workspace",
        role="auditor",
    )
    assert isinstance(auditor_workspace, dict)
    assert auditor_workspace["visible_balanced"] is True

    print("LedgerFlow live-stack integration test passed")


if __name__ == "__main__":
    main()
