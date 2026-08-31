from fastapi import Header, HTTPException

ROLES = {
    "merchant_owner": {
        "label": "Merchant owner",
        "description": "Business overview, payments, refunds, balances and settlements.",
        "permissions": [
            "payments:read",
            "payments:create",
            "payments:capture",
            "refunds:create",
            "settlements:read",
            "settlements:create",
            "disputes:read",
            "disputes:evidence",
            "webhooks:read",
            "api_keys:read",
        ],
    },
    "merchant_developer": {
        "label": "Merchant developer",
        "description": "API integrations, idempotency, events and webhook delivery diagnostics.",
        "permissions": [
            "payments:read",
            "payments:create",
            "webhooks:read",
            "webhooks:write",
            "api_keys:read",
            "api_keys:write",
        ],
    },
    "operations_admin": {
        "label": "Operations administrator",
        "description": "System-wide processor health, recovery, reconciliation and settlements.",
        "permissions": ["*"],
    },
    "risk_analyst": {
        "label": "Risk analyst",
        "description": "Fraud signals, manual reviews and disputes without merchant secrets.",
        "permissions": [
            "payments:read",
            "risk:review",
            "risk:rules",
            "disputes:read",
            "disputes:manage",
        ],
    },
    "auditor": {
        "label": "Read-only auditor",
        "description": "Immutable financial records, balance proofs and audit history.",
        "permissions": ["ledger:read", "audit:read"],
    },
}


async def current_role(x_demo_role: str = Header(default="merchant_owner")) -> str:
    if x_demo_role not in ROLES:
        raise HTTPException(status_code=403, detail="Unknown demonstration role")
    return x_demo_role


def require_permission(role: str, permission: str) -> None:
    permissions = ROLES[role]["permissions"]
    if "*" not in permissions and permission not in permissions:
        raise HTTPException(status_code=403, detail=f"Role '{role}' cannot perform '{permission}'")
