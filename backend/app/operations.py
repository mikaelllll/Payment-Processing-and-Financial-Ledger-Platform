import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ApiKey,
    AuditEvent,
    Dispute,
    FraudRule,
    LedgerEntry,
    Merchant,
    OutboxEvent,
    Payment,
    PaymentStatus,
    Processor,
    RiskCase,
    Settlement,
    WebhookDelivery,
    WebhookEndpoint,
    new_id,
)
from .services import post_balanced_entries, save_run, step


async def merchant_balance(session: AsyncSession, merchant_id: str = "mer_demo") -> int:
    credit, debit = (
        await session.execute(
            select(
                func.coalesce(func.sum(LedgerEntry.credit), 0),
                func.coalesce(func.sum(LedgerEntry.debit), 0),
            ).where(
                LedgerEntry.merchant_id == merchant_id,
                LedgerEntry.account == "merchant_payable",
            )
        )
    ).one()
    return int(credit) - int(debit)


async def capture_payment(
    session: AsyncSession, payment_id: str, amount: int | None, actor: str
) -> tuple[Payment, list[dict], str]:
    payment = await session.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")
    if payment.status != PaymentStatus.AUTHORIZED:
        raise HTTPException(409, "Only authorized payments can be captured")
    pending_risk = await session.scalar(
        select(RiskCase.id).where(
            RiskCase.payment_id == payment.id,
            RiskCase.status == "pending",
        )
    )
    if pending_risk:
        raise HTTPException(409, "Payment remains blocked by a pending risk review")
    capture_amount = amount or payment.amount
    if capture_amount > payment.amount:
        raise HTTPException(409, "Capture exceeds the authorized amount")
    fee = max(30, capture_amount * 3 // 100)
    txn = await post_balanced_entries(
        session,
        payment,
        "Manual capture",
        [
            ("processor_receivable", capture_amount, 0),
            ("merchant_payable", 0, capture_amount - fee),
            ("platform_fee_revenue", 0, fee),
        ],
    )
    payment.captured_amount = capture_amount
    payment.status = PaymentStatus.CAPTURED
    steps = [
        step(
            "lock",
            "Authorization locked",
            "Concurrent capture attempts serialize on the payment row.",
            "success",
            21,
        ),
        step(
            "validation",
            "Capture boundary validated",
            f"Capture {capture_amount} is within authorization {payment.amount}.",
            "success",
            14,
        ),
        step(
            "processor",
            "Processor capture confirmed",
            "A definitive external reference was persisted before accounting.",
            "success",
            420,
            payment.processor,
        ),
        step(
            "ledger",
            "Balanced capture committed",
            "Merchant payable and platform fee were posted atomically.",
            "success",
            32,
            txn,
        ),
        step(
            "event",
            "Capture event queued",
            "Transactional outbox delivery can retry without repeating the capture.",
            "info",
            18,
            "payment.captured",
        ),
    ]
    session.add(
        OutboxEvent(
            id=new_id("evt"),
            event_type="payment.captured",
            aggregate_id=payment.id,
            payload={"payment_id": payment.id, "amount": capture_amount},
        )
    )
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action="payment.captured",
            resource_type="payment",
            resource_id=payment.id,
            details={"amount": capture_amount},
        )
    )
    run_id = await save_run(session, payment, "manual_capture", "captured", steps)
    await session.commit()
    await session.refresh(payment)
    return payment, steps, run_id


async def resolve_risk(
    session: AsyncSession, case_id: str, decision: str, note: str, actor: str
) -> tuple[RiskCase, list[dict]]:
    case = await session.scalar(select(RiskCase).where(RiskCase.id == case_id).with_for_update())
    if not case:
        raise HTTPException(404, "Risk case not found")
    if case.status != "pending":
        raise HTTPException(409, "Risk case is already resolved")
    if decision not in {"approve", "reject"}:
        raise HTTPException(422, "Decision must be approve or reject")
    payment = await session.get(Payment, case.payment_id)
    case.status = "approved" if decision == "approve" else "rejected"
    case.resolution_note = note
    case.resolved_by = actor
    case.resolved_at = datetime.now(UTC)
    payment.status = PaymentStatus.AUTHORIZED if decision == "approve" else PaymentStatus.FAILED
    steps = [
        step(
            "review",
            "Evidence reviewed",
            f"{len(case.signals)} explainable risk signals were reviewed.",
            "success",
            120,
        ),
        step(
            "decision",
            f"Case {case.status}",
            note or "Manual analyst decision",
            "success" if decision == "approve" else "warning",
            25,
            f"Risk score {case.score}",
        ),
        step(
            "state",
            "Payment state updated",
            f"Payment moved to {payment.status.value}; no hidden capture occurred.",
            "info",
            18,
            payment.id,
        ),
        step(
            "audit",
            "Decision audit recorded",
            "Actor, evidence, note and timestamp are immutable.",
            "success",
            12,
            actor,
        ),
    ]
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action=f"risk.{case.status}",
            resource_type="risk_case",
            resource_id=case.id,
            details={"note": note, "payment_id": payment.id},
        )
    )
    session.add(
        OutboxEvent(
            id=new_id("evt"),
            event_type=f"risk.{case.status}",
            aggregate_id=case.id,
            payload={"payment_id": payment.id, "decision": case.status},
        )
    )
    await session.commit()
    await session.refresh(case)
    return case, steps


async def create_settlement(
    session: AsyncSession, amount: int, key: str, actor: str
) -> tuple[Settlement, list[dict], bool]:
    # Serialize balance reservations on the merchant row so the balance check
    # and its ledger posting cannot be interleaved by concurrent settlements.
    merchant = await session.scalar(
        select(Merchant).where(Merchant.id == "mer_demo").with_for_update()
    )
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    existing = await session.scalar(
        select(Settlement).where(
            Settlement.merchant_id == "mer_demo", Settlement.idempotency_key == key
        )
    )
    if existing:
        return (
            existing,
            [
                step(
                    "idempotency",
                    "Settlement safely replayed",
                    "The original settlement is returned without reserving funds again.",
                    "warning",
                    15,
                    key,
                )
            ],
            True,
        )
    available = await merchant_balance(session)
    if amount > available:
        raise HTTPException(409, f"Settlement exceeds available balance of {available}")
    settlement = Settlement(
        id=new_id("set"),
        merchant_id="mer_demo",
        amount=amount,
        currency="BRL",
        status="pending",
        idempotency_key=key,
    )
    session.add(settlement)
    synthetic_payment = await session.scalar(
        select(Payment).where(Payment.merchant_id == "mer_demo").limit(1)
    )
    txn = await post_balanced_entries(
        session,
        synthetic_payment,
        "Settlement reservation",
        [("merchant_payable", amount, 0), ("settlement_payable", 0, amount)],
    )
    steps = [
        step(
            "balance",
            "Available balance calculated",
            "Balance was derived from immutable merchant-payable entries.",
            "success",
            24,
            str(available),
        ),
        step(
            "reserve",
            "Funds reserved atomically",
            "Concurrent payouts cannot reserve the same merchant balance.",
            "success",
            22,
            txn,
        ),
        step(
            "bank",
            "Simulated bank transfer submitted",
            "Settlement remains pending until a definitive bank result arrives.",
            "info",
            340,
        ),
        step(
            "outbox",
            "Settlement event queued",
            "Merchant notification is independent from financial commit.",
            "success",
            16,
            "settlement.pending",
        ),
    ]
    session.add(
        OutboxEvent(
            id=new_id("evt"),
            event_type="settlement.pending",
            aggregate_id=settlement.id,
            payload={"settlement_id": settlement.id, "amount": amount},
        )
    )
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action="settlement.created",
            resource_type="settlement",
            resource_id=settlement.id,
            details={"amount": amount},
        )
    )
    await session.commit()
    return settlement, steps, False


async def settlement_action(
    session: AsyncSession, settlement_id: str, action: str, actor: str
) -> tuple[Settlement, list[dict]]:
    settlement = await session.scalar(
        select(Settlement).where(Settlement.id == settlement_id).with_for_update()
    )
    if not settlement:
        raise HTTPException(404, "Settlement not found")
    if action not in {"complete", "fail", "retry"}:
        raise HTTPException(422, "Unsupported settlement action")
    if action == "retry":
        if settlement.status != "failed":
            raise HTTPException(409, "Only failed settlements can be retried")
        settlement.status, settlement.failure_reason = "pending", None
        title, detail = (
            "Settlement resubmitted",
            "The same reserved funds were reused; no second balance reservation occurred.",
        )
    elif action == "fail":
        if settlement.status != "pending":
            raise HTTPException(409, "Only pending settlements can fail")
        settlement.status, settlement.failure_reason = (
            "failed",
            "Simulated beneficiary account rejection",
        )
        title, detail = (
            "Bank rejected transfer",
            "Funds remain reserved while operations decides whether to retry or release them.",
        )
    else:
        if settlement.status != "pending":
            raise HTTPException(409, "Only pending settlements can complete")
        settlement.status = "paid"
        settlement.bank_reference = new_id("bank")
        settlement.completed_at = datetime.now(UTC)
        payment = await session.scalar(
            select(Payment).where(Payment.merchant_id == settlement.merchant_id).limit(1)
        )
        await post_balanced_entries(
            session,
            payment,
            "Settlement completion",
            [("settlement_payable", settlement.amount, 0), ("platform_cash", 0, settlement.amount)],
        )
        title, detail = (
            "Bank confirmed settlement",
            "Reserved liability was cleared through a new balanced ledger transaction.",
        )
    steps = [
        step(
            "lock",
            "Settlement locked",
            "Concurrent operational actions are serialized.",
            "success",
            18,
        ),
        step("bank", title, detail, "success" if action != "fail" else "error", 310),
        step(
            "audit",
            "Operational action recorded",
            "The previous state remains reconstructable from audit history.",
            "success",
            12,
            actor,
        ),
    ]
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action=f"settlement.{action}",
            resource_type="settlement",
            resource_id=settlement.id,
            details={"status": settlement.status},
        )
    )
    await session.commit()
    await session.refresh(settlement)
    return settlement, steps


async def dispute_action(
    session: AsyncSession, dispute_id: str, action: str, note: str, actor: str
) -> tuple[Dispute, list[dict]]:
    dispute = await session.scalar(
        select(Dispute).where(Dispute.id == dispute_id).with_for_update()
    )
    if not dispute:
        raise HTTPException(404, "Dispute not found")
    payment = await session.get(Payment, dispute.payment_id)
    if action == "evidence":
        if dispute.status in {"won", "lost"}:
            raise HTTPException(409, "Evidence cannot be added to a resolved dispute")
        if not note.strip():
            raise HTTPException(422, "Evidence note is required")
        dispute.evidence = [
            *dispute.evidence,
            {"note": note, "submitted_by": actor, "at": datetime.now(UTC).isoformat()},
        ]
        dispute.status = "under_review"
        title = "Evidence submitted"
    elif action in {"win", "lose"}:
        if dispute.status in {"won", "lost"}:
            raise HTTPException(409, "Dispute is already resolved")
        dispute.status = "won" if action == "win" else "lost"
        dispute.resolved_at = datetime.now(UTC)
        if action == "win":
            await post_balanced_entries(
                session,
                payment,
                "Dispute won",
                [("dispute_reserve", dispute.amount, 0), ("merchant_payable", 0, dispute.amount)],
            )
        else:
            await post_balanced_entries(
                session,
                payment,
                "Chargeback finalized",
                [
                    ("dispute_reserve", dispute.amount, 0),
                    ("processor_chargeback_payable", 0, dispute.amount),
                ],
            )
        title = f"Dispute {dispute.status}"
    else:
        raise HTTPException(422, "Unsupported dispute action")
    steps = [
        step(
            "lock",
            "Dispute locked",
            "Competing evidence and resolution actions cannot race.",
            "success",
            18,
        ),
        step("case", title, note, "success" if action != "lose" else "warning", 80),
        step(
            "ledger",
            "Financial consequence applied",
            "A balanced entry was added when the outcome changed ownership of reserved funds.",
            "success",
            25,
        ),
        step(
            "audit",
            "Case timeline updated",
            "Actor, note and result are permanently attributable.",
            "info",
            10,
            actor,
        ),
    ]
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action=f"dispute.{action}",
            resource_type="dispute",
            resource_id=dispute.id,
            details={"note": note},
        )
    )
    await session.commit()
    return dispute, steps


async def create_api_key(
    session: AsyncSession, name: str, scopes: list[str], actor: str
) -> tuple[ApiKey, str]:
    secret = f"lf_live_{secrets.token_urlsafe(24)}"
    key = ApiKey(
        id=new_id("key"),
        merchant_id="mer_demo",
        name=name,
        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        key_last4=secret[-4:],
        scopes=scopes,
    )
    session.add(key)
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action="api_key.created",
            resource_type="api_key",
            resource_id=key.id,
            details={"name": name, "scopes": scopes},
        )
    )
    await session.commit()
    return key, secret


async def create_webhook(
    session: AsyncSession, url: str, actor: str
) -> tuple[WebhookEndpoint, str]:
    if not url.startswith("https://") and not url.startswith("http://demo-merchant"):
        raise HTTPException(422, "Webhook URL must use HTTPS")
    secret = f"whsec_{secrets.token_urlsafe(24)}"
    endpoint = WebhookEndpoint(
        id=new_id("we"),
        merchant_id="mer_demo",
        url=url,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        secret_last4=secret[-4:],
    )
    session.add(endpoint)
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor,
            action="webhook.created",
            resource_type="webhook",
            resource_id=endpoint.id,
            details={"url": url},
        )
    )
    await session.commit()
    return endpoint, secret


async def seed_operations(session: AsyncSession) -> None:
    if not await session.get(Processor, "aurora_pay"):
        session.add_all(
            [
                Processor(
                    id="aurora_pay",
                    display_name="Aurora Pay",
                    health="healthy",
                    success_rate=99,
                    latency_ms=285,
                    fee_bps=300,
                    currencies=["BRL"],
                ),
                Processor(
                    id="fast_card",
                    display_name="FastCard",
                    health="degraded",
                    success_rate=94,
                    latency_ms=510,
                    fee_bps=340,
                    currencies=["BRL", "USD"],
                ),
                Processor(
                    id="global_pay",
                    display_name="Global Pay",
                    health="healthy",
                    success_rate=98,
                    latency_ms=430,
                    fee_bps=390,
                    currencies=["BRL", "USD", "EUR"],
                ),
            ]
        )
    if not await session.scalar(select(FraudRule.id).limit(1)):
        session.add_all(
            [
                FraudRule(
                    id=new_id("rule"),
                    name="High amount from new customer",
                    field="amount",
                    operator="greater_than",
                    threshold="500000",
                    action="manual_review",
                ),
                FraudRule(
                    id=new_id("rule"),
                    name="Rapid decline velocity",
                    field="declines_10m",
                    operator="greater_than",
                    threshold="3",
                    action="block",
                ),
                FraudRule(
                    id=new_id("rule"),
                    name="Trusted returning customer",
                    field="account_age_days",
                    operator="greater_than",
                    threshold="365",
                    action="allow",
                ),
            ]
        )
    if not await session.scalar(select(WebhookEndpoint.id).limit(1)):
        endpoint = WebhookEndpoint(
            id=new_id("we"),
            merchant_id="mer_demo",
            url="http://demo-merchant/webhooks",
            secret_hash=hashlib.sha256(b"demo-webhook-secret").hexdigest(),
            secret_last4="cret",
        )
        session.add(endpoint)
        await session.flush()
        session.add_all(
            [
                WebhookDelivery(
                    id=new_id("wd"),
                    endpoint_id=endpoint.id,
                    event_id=new_id("evt"),
                    event_type="payment.captured",
                    status="delivered",
                    response_code=200,
                    attempts=1,
                ),
                WebhookDelivery(
                    id=new_id("wd"),
                    endpoint_id=endpoint.id,
                    event_id=new_id("evt"),
                    event_type="payment.refunded",
                    status="retrying",
                    response_code=503,
                    attempts=2,
                    next_retry_at=datetime.now(UTC) + timedelta(minutes=5),
                ),
            ]
        )
    if not await session.scalar(select(ApiKey.id).limit(1)):
        session.add(
            ApiKey(
                id=new_id("key"),
                merchant_id="mer_demo",
                name="Demo store production",
                key_hash=hashlib.sha256(b"unavailable-demo-key").hexdigest(),
                key_last4="7Kp2",
                scopes=["payments:write", "payments:read"],
                status="active",
            )
        )
    await session.flush()


SENSITIVE_RESPONSE_FIELDS = {"key_hash", "secret_hash"}


def serialize_model(item) -> dict:
    """Serialize a demo resource without exposing stored credential material."""
    return {
        column.name: getattr(item, column.name)
        for column in item.__table__.columns
        if column.name not in SENSITIVE_RESPONSE_FIELDS
    }
