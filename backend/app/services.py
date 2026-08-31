import hashlib
import json
import random
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
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
    ReconciliationCase,
    Refund,
    RiskCase,
    Settlement,
    SimulationRun,
    WebhookDelivery,
    WebhookEndpoint,
    new_id,
)
from .schemas import PaymentCreate, SimulationStep


def fingerprint(payload: PaymentCreate) -> str:
    stable = payload.model_dump(exclude={"scenario"}, mode="json")
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def step(
    key: str, title: str, detail: str, status: str, duration: int, evidence: str | None = None
) -> dict:
    return SimulationStep(
        key=key, title=title, detail=detail, status=status, duration_ms=duration, evidence=evidence
    ).model_dump()


def choose_processor(payload: PaymentCreate) -> tuple[str, str]:
    if payload.currency == "BRL" and payload.amount <= 500_000:
        return (
            "aurora_pay",
            "BRL transaction below R$5,000 routed to the lowest-cost healthy processor.",
        )
    if payload.currency in {"USD", "EUR"}:
        return "global_pay", "Cross-border currency requires the global settlement processor."
    return (
        "fast_card",
        "Higher-value transaction routed to the processor with enhanced risk controls.",
    )


async def post_balanced_entries(
    session: AsyncSession,
    payment: Payment,
    description: str,
    lines: list[tuple[str, int, int]],
) -> str:
    total_debit = sum(line[1] for line in lines)
    total_credit = sum(line[2] for line in lines)
    if total_debit != total_credit:
        raise ValueError("Unbalanced ledger transaction rejected")
    transaction_id = new_id("txn")
    for account, debit, credit in lines:
        session.add(
            LedgerEntry(
                id=new_id("le"),
                transaction_id=transaction_id,
                payment_id=payment.id,
                merchant_id=payment.merchant_id,
                account=account,
                debit=debit,
                credit=credit,
                currency=payment.currency,
                description=description,
            )
        )
    return transaction_id


async def create_payment(
    session: AsyncSession, payload: PaymentCreate, actor_role: str
) -> tuple[Payment, list[dict], bool, str]:
    request_hash = fingerprint(payload)
    existing = await session.scalar(
        select(Payment).where(
            Payment.merchant_id == payload.merchant_id,
            Payment.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.request_fingerprint != request_hash:
            raise HTTPException(
                status_code=409, detail="Idempotency key was reused with a different request"
            )
        replay_steps = [
            step(
                "received",
                "Request received",
                "Authenticated request accepted at the payment boundary.",
                "success",
                70,
            ),
            step(
                "idempotency",
                "Duplicate safely intercepted",
                "The stored fingerprint matches. The original payment is returned without contacting a processor.",
                "warning",
                18,
                f"Idempotency-Key: {payload.idempotency_key}",
            ),
            step(
                "replay",
                "Original response replayed",
                "No ledger entry or external charge was created during this replay.",
                "success",
                25,
                existing.id,
            ),
        ]
        run_id = await save_run(session, existing, "idempotent_replay", "replayed", replay_steps)
        await session.commit()
        return existing, replay_steps, True, run_id

    processor, route_reason = choose_processor(payload)
    payment = Payment(
        id=new_id("pay"),
        merchant_id=payload.merchant_id,
        amount=payload.amount,
        currency=payload.currency,
        status=PaymentStatus.PROCESSING,
        processor=processor,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=request_hash,
        customer_reference=payload.customer_reference,
        metadata_json={"capture_method": payload.capture_method},
    )
    session.add(payment)
    try:
        # Reserve the unique merchant/key pair before any external side effect.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        concurrent = await session.scalar(
            select(Payment).where(
                Payment.merchant_id == payload.merchant_id,
                Payment.idempotency_key == payload.idempotency_key,
            )
        )
        if concurrent and concurrent.request_fingerprint == request_hash:
            replay_steps = [
                step(
                    "idempotency",
                    "Concurrent duplicate intercepted",
                    "The database uniqueness boundary selected the reserved operation.",
                    "warning",
                    20,
                ),
                step(
                    "replay",
                    "Original payment returned",
                    "No second processor submission or ledger posting was created.",
                    "success",
                    18,
                    concurrent.id,
                ),
            ]
            run_id = await save_run(
                session, concurrent, "concurrent_replay", "replayed", replay_steps
            )
            await session.commit()
            return concurrent, replay_steps, True, run_id
        raise HTTPException(
            status_code=409, detail="Idempotency key reservation conflict"
        ) from None
    steps = [
        step(
            "received",
            "Request authenticated",
            "API key scope, merchant status, schema and amount boundaries passed validation.",
            "success",
            85,
            actor_role,
        ),
        step(
            "idempotency",
            "Idempotency reservation acquired",
            "The merchant/key pair was atomically reserved before external work began.",
            "success",
            22,
            payload.idempotency_key,
        ),
        step(
            "risk",
            "Deterministic risk rules evaluated",
            "Velocity, amount, customer age and simulated deny lists were evaluated with an explainable decision.",
            "warning" if payload.scenario == "high_risk" else "success",
            140,
            "Decision: manual review" if payload.scenario == "high_risk" else "Decision: allow",
        ),
        step("routing", f"Routed to {processor}", route_reason, "info", 35, "Routing policy v3"),
    ]

    if payload.scenario == "declined":
        payment.status = PaymentStatus.FAILED
        steps += [
            step(
                "processor",
                "Processor declined definitively",
                "The simulated processor returned an explicit insufficient-funds response.",
                "error",
                510,
                "DECLINED_INSUFFICIENT_FUNDS",
            ),
            step(
                "ledger",
                "No financial posting created",
                "Definitive failure means no balance movement. The attempt remains auditable.",
                "success",
                15,
            ),
        ]
        outcome = "declined"
    elif payload.scenario == "timeout_before":
        payment.status = PaymentStatus.FAILED
        steps += [
            step(
                "processor",
                "Connection failed before submission",
                "The connection could not be established, proving the processor never received the request.",
                "error",
                1_200,
                "Safe-to-retry classification",
            ),
            step(
                "retry",
                "Retry policy exhausted safely",
                "Retries used the same provider idempotency reference; no ledger posting was made.",
                "warning",
                640,
            ),
        ]
        outcome = "failed_before_submission"
    elif payload.scenario == "ambiguous":
        payment.status = PaymentStatus.CONFIRMATION_REQUIRED
        steps += [
            step(
                "processor",
                "Response lost after submission",
                "The processor may have authorized the payment; blind fallback is prohibited.",
                "warning",
                1_500,
                "Ambiguous network outcome",
            ),
            step(
                "recovery",
                "Recovery query confirmed authorization",
                "A background-safe status lookup used the stable processor reference instead of charging again.",
                "success",
                730,
                processor,
            ),
        ]
        payment.status = (
            PaymentStatus.CAPTURED
            if payload.capture_method == "automatic"
            else PaymentStatus.AUTHORIZED
        )
        if payload.capture_method == "automatic":
            payment.captured_amount = payload.amount
            fee = max(30, payload.amount * 3 // 100)
            txn = await post_balanced_entries(
                session,
                payment,
                "Recovered capture",
                [
                    ("processor_receivable", payload.amount, 0),
                    ("merchant_payable", 0, payload.amount - fee),
                    ("platform_fee_revenue", 0, fee),
                ],
            )
            steps.append(
                step(
                    "ledger",
                    "Balanced capture posted once",
                    "Recovery produced one immutable transaction after processor confirmation.",
                    "success",
                    42,
                    txn,
                )
            )
        outcome = "recovered_without_duplicate"
    elif payload.scenario == "high_risk":
        payment.status = PaymentStatus.AUTHORIZED
        session.add(
            RiskCase(
                id=new_id("risk"),
                payment_id=payment.id,
                score=82,
                status="pending",
                signals=[
                    "Transaction amount exceeds new-customer threshold",
                    "Three declines observed in the previous ten minutes",
                    "Billing location differs from recent profile",
                ],
            )
        )
        steps += [
            step(
                "review",
                "Manual review required",
                "Funds were authorized but capture is blocked until a risk analyst resolves the case.",
                "warning",
                280,
                "Risk score: 82/100",
            ),
            step(
                "ledger",
                "Capture posting intentionally withheld",
                "An authorization is not merchant revenue; no payable balance was created.",
                "success",
                18,
            ),
        ]
        outcome = "manual_review"
    else:
        payment.status = (
            PaymentStatus.CAPTURED
            if payload.capture_method == "automatic"
            else PaymentStatus.AUTHORIZED
        )
        steps.append(
            step(
                "processor",
                "Processor authorization succeeded",
                "The external reference and definitive authorization response were persisted.",
                "success",
                460,
                f"{processor}: approved",
            )
        )
        if payload.capture_method == "automatic":
            payment.captured_amount = payload.amount
            fee = max(30, payload.amount * 3 // 100)
            txn = await post_balanced_entries(
                session,
                payment,
                "Payment capture",
                [
                    ("processor_receivable", payload.amount, 0),
                    ("merchant_payable", 0, payload.amount - fee),
                    ("platform_fee_revenue", 0, fee),
                ],
            )
            steps.append(
                step(
                    "ledger",
                    "Double-entry transaction committed",
                    "Debit and credit totals were verified inside the same database transaction.",
                    "success",
                    38,
                    txn,
                )
            )
        else:
            steps.append(
                step(
                    "ledger",
                    "Authorization recorded without balance movement",
                    "Ledger posting waits for capture because reserved funds are not yet merchant funds.",
                    "success",
                    18,
                )
            )
        steps.append(
            step(
                "event",
                "Webhook event queued",
                "A signed event was placed in the delivery outbox atomically with the payment result.",
                "info",
                24,
                "payment.captured"
                if payload.capture_method == "automatic"
                else "payment.authorized",
            )
        )
        outcome = payment.status.value

    run_id = await save_run(session, payment, payload.scenario, outcome, steps)
    session.add(
        OutboxEvent(
            id=new_id("evt"),
            event_type=f"payment.{payment.status.value}",
            aggregate_id=payment.id,
            payload={
                "payment_id": payment.id,
                "status": payment.status.value,
                "amount": payment.amount,
                "currency": payment.currency,
            },
        )
    )
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor_role,
            action="payment.created",
            resource_type="payment",
            resource_id=payment.id,
            details={"scenario": payload.scenario, "outcome": outcome},
        )
    )
    await session.commit()
    await session.refresh(payment)
    return payment, steps, False, run_id


async def refund_payment(
    session: AsyncSession,
    payment_id: str,
    amount: int,
    idempotency_key: str,
    actor_role: str,
) -> tuple[Payment, list[dict], str, bool]:
    existing_refund = await session.scalar(
        select(Refund).where(
            Refund.payment_id == payment_id,
            Refund.idempotency_key == idempotency_key,
        )
    )
    if existing_refund:
        if existing_refund.amount != amount:
            raise HTTPException(
                status_code=409,
                detail="Refund idempotency key was reused with a different amount",
            )
        payment = await session.get(Payment, payment_id)
        replay_steps = [
            step(
                "idempotency",
                "Duplicate refund intercepted",
                "The completed refund is returned without contacting the processor.",
                "warning",
                16,
                idempotency_key,
            ),
            step(
                "replay",
                "Original refund outcome replayed",
                "No additional reversing entry or merchant balance change was created.",
                "success",
                14,
                existing_refund.id,
            ),
        ]
        run_id = await save_run(
            session, payment, "refund_replay", payment.status.value, replay_steps
        )
        await session.commit()
        return payment, replay_steps, run_id, True
    payment = await session.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    refundable = payment.captured_amount - payment.refunded_amount
    if (
        payment.status not in {PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED}
        or amount > refundable
    ):
        raise HTTPException(
            status_code=409, detail=f"Refund exceeds refundable amount of {refundable}"
        )
    txn = await post_balanced_entries(
        session,
        payment,
        "Payment refund",
        [("merchant_payable", amount, 0), ("processor_refund_payable", 0, amount)],
    )
    payment.refunded_amount += amount
    payment.status = (
        PaymentStatus.REFUNDED
        if payment.refunded_amount == payment.captured_amount
        else PaymentStatus.PARTIALLY_REFUNDED
    )
    session.add(
        Refund(
            id=new_id("re"),
            payment_id=payment.id,
            amount=amount,
            idempotency_key=idempotency_key,
        )
    )
    steps = [
        step(
            "lock",
            "Payment row locked",
            "Concurrent refunds cannot spend the same refundable balance.",
            "success",
            25,
        ),
        step(
            "validation",
            "Refund boundary validated",
            f"Requested {amount}; refundable before operation {refundable}.",
            "success",
            15,
        ),
        step(
            "processor",
            "Processor refund accepted",
            "The refund used a stable external reference and definitive response.",
            "success",
            390,
        ),
        step(
            "ledger",
            "Reversing ledger entry committed",
            "The original entry was preserved; a new balanced transaction records the refund.",
            "success",
            36,
            txn,
        ),
        step(
            "event",
            "Refund webhook queued",
            "Merchant notification is delivered asynchronously with retry and signature verification.",
            "info",
            20,
            "payment.refunded",
        ),
    ]
    run_id = await save_run(session, payment, "refund", payment.status.value, steps)
    session.add(
        OutboxEvent(
            id=new_id("evt"),
            event_type="payment.refunded",
            aggregate_id=payment.id,
            payload={
                "payment_id": payment.id,
                "refunded_amount": amount,
                "currency": payment.currency,
            },
        )
    )
    session.add(
        AuditEvent(
            id=new_id("aud"),
            actor_role=actor_role,
            action="payment.refunded",
            resource_type="payment",
            resource_id=payment.id,
            details={"amount": amount},
        )
    )
    await session.commit()
    await session.refresh(payment)
    return payment, steps, run_id, False


async def save_run(
    session: AsyncSession, payment: Payment, scenario: str, outcome: str, steps: list[dict]
) -> str:
    run_id = new_id("sim")
    session.add(
        SimulationRun(
            id=run_id, payment_id=payment.id, scenario=scenario, outcome=outcome, steps=steps
        )
    )
    return run_id


async def seed_demo(session: AsyncSession, size: str, reset: bool) -> dict:
    if reset:
        for model in (
            AuditEvent,
            SimulationRun,
            OutboxEvent,
            WebhookDelivery,
            WebhookEndpoint,
            ApiKey,
            ReconciliationCase,
            Dispute,
            RiskCase,
            Settlement,
            FraudRule,
            Processor,
            LedgerEntry,
            Refund,
            Payment,
            Merchant,
        ):
            await session.execute(delete(model))
    merchant = await session.get(Merchant, "mer_demo")
    if not merchant:
        session.add(
            Merchant(id="mer_demo", name="Northstar Outdoor", email="finance@northstar.example")
        )
        await session.flush()
    count = {"small": 12, "medium": 60, "large": 250}[size]
    statuses = [
        PaymentStatus.CAPTURED,
        PaymentStatus.CAPTURED,
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
        PaymentStatus.REFUNDED,
        PaymentStatus.AUTHORIZED,
    ]
    rng = random.Random(731)
    created = 0
    for index in range(count):
        key = f"seed-{size}-{index}"
        if await session.scalar(
            select(Payment.id).where(
                Payment.merchant_id == "mer_demo", Payment.idempotency_key == key
            )
        ):
            continue
        amount = rng.randint(1_500, 180_000)
        status = rng.choice(statuses)
        captured = amount if status in {PaymentStatus.CAPTURED, PaymentStatus.REFUNDED} else 0
        refunded = amount if status == PaymentStatus.REFUNDED else 0
        payment = Payment(
            id=new_id("pay"),
            merchant_id="mer_demo",
            amount=amount,
            currency="BRL",
            status=status,
            processor=rng.choice(["aurora_pay", "fast_card", "global_pay"]),
            idempotency_key=key,
            request_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            captured_amount=captured,
            refunded_amount=refunded,
            customer_reference=f"customer-{1000 + index}",
            created_at=datetime.now(UTC) - timedelta(hours=rng.randint(0, 240)),
        )
        session.add(payment)
        await session.flush()
        if captured:
            fee = max(30, amount * 3 // 100)
            await post_balanced_entries(
                session,
                payment,
                "Seeded capture",
                [
                    ("processor_receivable", amount, 0),
                    ("merchant_payable", 0, amount - fee),
                    ("platform_fee_revenue", 0, fee),
                ],
            )
            if refunded:
                await post_balanced_entries(
                    session,
                    payment,
                    "Seeded refund",
                    [("merchant_payable", amount, 0), ("processor_refund_payable", 0, amount)],
                )
        created += 1
    from .operations import seed_operations

    await seed_operations(session)
    await session.flush()

    captured_payment = await session.scalar(
        select(Payment)
        .where(Payment.status == PaymentStatus.CAPTURED)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    if captured_payment and not await session.scalar(select(Dispute.id).limit(1)):
        dispute_amount = min(captured_payment.captured_amount, 5_000)
        session.add(
            Dispute(
                id=new_id("dp"),
                payment_id=captured_payment.id,
                merchant_id=captured_payment.merchant_id,
                amount=dispute_amount,
                reason="product_not_received",
                status="needs_response",
                evidence=[],
                due_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await post_balanced_entries(
            session,
            captured_payment,
            "Dispute reserve",
            [
                ("merchant_payable", dispute_amount, 0),
                ("dispute_reserve", 0, dispute_amount),
            ],
        )
    if captured_payment and not await session.scalar(select(ReconciliationCase.id).limit(1)):
        session.add_all(
            [
                ReconciliationCase(
                    id=new_id("rec"),
                    payment_id=captured_payment.id,
                    processor=captured_payment.processor,
                    case_type="status_mismatch",
                    internal_amount=captured_payment.amount,
                    processor_amount=captured_payment.amount,
                    status="open",
                ),
                ReconciliationCase(
                    id=new_id("rec"),
                    payment_id=None,
                    processor="fast_card",
                    case_type="processor_only_transaction",
                    internal_amount=0,
                    processor_amount=12_500,
                    status="open",
                ),
            ]
        )
    await session.commit()
    return {"created": created, "requested": count, "size": size, "reset": reset}


async def dashboard(session: AsyncSession) -> dict:
    total, captured, failed, volume = (
        await session.execute(
            select(
                func.count(Payment.id),
                func.count(Payment.id).filter(
                    Payment.status.in_(
                        [
                            PaymentStatus.CAPTURED,
                            PaymentStatus.PARTIALLY_REFUNDED,
                            PaymentStatus.REFUNDED,
                        ]
                    )
                ),
                func.count(Payment.id).filter(Payment.status == PaymentStatus.FAILED),
                func.coalesce(func.sum(Payment.captured_amount), 0),
            )
        )
    ).one()
    payments = (
        await session.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(25))
    ).all()
    activity_start = datetime.now(UTC) - timedelta(days=9)
    activity_payments = (
        await session.scalars(select(Payment).where(Payment.created_at >= activity_start))
    ).all()
    activity_by_date: dict[str, dict[str, int | str]] = {}
    for payment in activity_payments:
        date_key = payment.created_at.date().isoformat()
        bucket = activity_by_date.setdefault(
            date_key, {"date": date_key, "volume": 0, "payments": 0}
        )
        bucket["volume"] = int(bucket["volume"]) + payment.captured_amount
        bucket["payments"] = int(bucket["payments"]) + 1
    debits, credits = (
        await session.execute(
            select(
                func.coalesce(func.sum(LedgerEntry.debit), 0),
                func.coalesce(func.sum(LedgerEntry.credit), 0),
            )
        )
    ).one()
    return {
        "metrics": {
            "payments": total,
            "captured": captured,
            "failed": failed,
            "volume": volume,
            "ledger_balanced": debits == credits,
            "ledger_debits": debits,
            "ledger_credits": credits,
        },
        "payments": payments,
        "activity": list(activity_by_date.values()),
    }
