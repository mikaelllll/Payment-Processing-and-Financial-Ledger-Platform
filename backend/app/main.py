from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import Base, engine, get_session
from .models import (
    ApiKey,
    AuditEvent,
    Dispute,
    FraudRule,
    LedgerEntry,
    OutboxEvent,
    Payment,
    PaymentStatus,
    Processor,
    ReconciliationCase,
    RiskCase,
    Settlement,
    SimulationRun,
    WebhookDelivery,
    WebhookEndpoint,
)
from .operations import (
    capture_payment,
    create_api_key,
    create_settlement,
    create_webhook,
    dispute_action,
    merchant_balance,
    resolve_risk,
    serialize_model,
    settlement_action,
)
from .roles import ROLES, current_role, require_permission
from .schemas import (
    ActionRequest,
    MoneyOperation,
    PaymentCreate,
    PaymentRead,
    ResourceCreate,
    SeedRequest,
    SimulationResult,
)
from .services import create_payment, dashboard, refund_payment, seed_demo, step


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # Idempotently backfill newly introduced demo resources for existing
        # Codespaces as well as populate completely fresh databases.
        await seed_demo(session, "small", False)
    yield
    await engine.dispose()


app = FastAPI(
    title="LedgerFlow Payment Platform",
    version="1.0.0",
    description="Safe payment orchestration, immutable double-entry accounting and failure simulation.",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Role", "Idempotency-Key"],
)


@app.get("/api/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(select(1))
    return {"status": "healthy", "service": settings.app_name, "environment": settings.environment}


@app.get("/api/roles")
async def roles() -> dict:
    return {"roles": ROLES}


@app.get("/api/dashboard")
async def get_dashboard(
    role: str = Depends(current_role), session: AsyncSession = Depends(get_session)
) -> dict:
    result = await dashboard(session)
    result["payments"] = [PaymentRead.model_validate(payment) for payment in result["payments"]]
    result["role"] = role
    return result


@app.post("/api/payments", response_model=SimulationResult, status_code=201)
async def post_payment(
    payload: PaymentCreate,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> SimulationResult:
    require_permission(role, "payments:create")
    payment, steps, replayed, run_id = await create_payment(session, payload, role)
    return SimulationResult(run_id=run_id, payment=payment, steps=steps, replayed=replayed)


@app.post("/api/payments/{payment_id}/refund", response_model=SimulationResult)
async def post_refund(
    payment_id: str,
    payload: MoneyOperation,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> SimulationResult:
    require_permission(role, "refunds:create")
    payment, steps, run_id, replayed = await refund_payment(
        session, payment_id, payload.amount, payload.idempotency_key, role
    )
    return SimulationResult(run_id=run_id, payment=payment, steps=steps, replayed=replayed)


@app.post("/api/demo/seed")
async def seed(
    payload: SeedRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if role not in {"operations_admin", "merchant_owner"}:
        raise HTTPException(
            status_code=403, detail="Only owners and operations administrators can seed demo data"
        )
    return await seed_demo(session, payload.size, payload.reset)


@app.get("/api/payments/{payment_id}/ledger")
async def payment_ledger(
    payment_id: str,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "ledger:read" if role == "auditor" else "payments:read")
    entries = (
        await session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.payment_id == payment_id)
            .order_by(LedgerEntry.created_at)
        )
    ).all()
    return {
        "entries": [
            {
                "id": item.id,
                "transaction_id": item.transaction_id,
                "account": item.account,
                "debit": item.debit,
                "credit": item.credit,
                "currency": item.currency,
                "description": item.description,
            }
            for item in entries
        ],
        "balanced": sum(x.debit for x in entries) == sum(x.credit for x in entries),
    }


@app.get("/api/simulations")
async def simulations(session: AsyncSession = Depends(get_session)) -> dict:
    runs = (
        await session.scalars(
            select(SimulationRun).order_by(SimulationRun.created_at.desc()).limit(20)
        )
    ).all()
    return {
        "runs": [
            {
                "id": run.id,
                "payment_id": run.payment_id,
                "scenario": run.scenario,
                "outcome": run.outcome,
                "steps": run.steps,
                "created_at": run.created_at,
            }
            for run in runs
        ]
    }


@app.get("/api/workspace")
async def workspace(
    role: str = Depends(current_role), session: AsyncSession = Depends(get_session)
) -> dict:
    """Return the operational read model appropriate for the active role."""
    base = {"role": role, "generated_at": datetime.now(UTC)}
    if role == "merchant_owner":
        settlements = (
            await session.scalars(
                select(Settlement).order_by(Settlement.created_at.desc()).limit(20)
            )
        ).all()
        disputes = (
            await session.scalars(
                select(Dispute)
                .where(Dispute.merchant_id == "mer_demo")
                .order_by(Dispute.created_at.desc())
            )
        ).all()
        authorized = (
            await session.scalars(
                select(Payment)
                .where(Payment.status == PaymentStatus.AUTHORIZED)
                .order_by(Payment.created_at.desc())
                .limit(20)
            )
        ).all()
        pending_risk_payment_ids = set(
            await session.scalars(select(RiskCase.payment_id).where(RiskCase.status == "pending"))
        )
        authorized = [
            payment for payment in authorized if payment.id not in pending_risk_payment_ids
        ]
        base.update(
            {
                "available_balance": await merchant_balance(session),
                "settlements": [serialize_model(x) for x in settlements],
                "disputes": [serialize_model(x) for x in disputes],
                "authorized_payments": [serialize_model(x) for x in authorized],
            }
        )
    elif role == "merchant_developer":
        endpoints = (
            await session.scalars(
                select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())
            )
        ).all()
        deliveries = (
            await session.scalars(
                select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(40)
            )
        ).all()
        keys = (await session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()))).all()
        runs = (
            await session.scalars(
                select(SimulationRun).order_by(SimulationRun.created_at.desc()).limit(15)
            )
        ).all()
        base.update(
            {
                "webhook_endpoints": [serialize_model(x) for x in endpoints],
                "deliveries": [serialize_model(x) for x in deliveries],
                "api_keys": [serialize_model(x) for x in keys],
                "request_traces": [serialize_model(x) for x in runs],
            }
        )
    elif role == "operations_admin":
        processors = (await session.scalars(select(Processor).order_by(Processor.id))).all()
        recovery = (
            await session.scalars(
                select(Payment)
                .where(Payment.status == PaymentStatus.CONFIRMATION_REQUIRED)
                .order_by(Payment.updated_at.desc())
            )
        ).all()
        reconciliation = (
            await session.scalars(
                select(ReconciliationCase).order_by(ReconciliationCase.created_at.desc())
            )
        ).all()
        settlements = (
            await session.scalars(
                select(Settlement).order_by(Settlement.created_at.desc()).limit(30)
            )
        ).all()
        pending_outbox = await session.scalar(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "pending")
        )
        base.update(
            {
                "processors": [serialize_model(x) for x in processors],
                "recovery_queue": [serialize_model(x) for x in recovery],
                "reconciliation": [serialize_model(x) for x in reconciliation],
                "settlements": [serialize_model(x) for x in settlements],
                "pending_outbox": pending_outbox or 0,
            }
        )
    elif role == "risk_analyst":
        cases = (await session.scalars(select(RiskCase).order_by(RiskCase.created_at.desc()))).all()
        rules = (
            await session.scalars(select(FraudRule).order_by(FraudRule.created_at.desc()))
        ).all()
        disputes = (
            await session.scalars(select(Dispute).order_by(Dispute.created_at.desc()))
        ).all()
        base.update(
            {
                "risk_cases": [serialize_model(x) for x in cases],
                "fraud_rules": [serialize_model(x) for x in rules],
                "disputes": [serialize_model(x) for x in disputes],
            }
        )
    else:
        entries = (
            await session.scalars(
                select(LedgerEntry).order_by(LedgerEntry.created_at.desc()).limit(100)
            )
        ).all()
        events = (
            await session.scalars(
                select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)
            )
        ).all()
        debits, credits = (
            await session.execute(
                select(
                    func.coalesce(func.sum(LedgerEntry.debit), 0),
                    func.coalesce(func.sum(LedgerEntry.credit), 0),
                )
            )
        ).one()
        base.update(
            {
                "ledger_entries": [serialize_model(x) for x in entries],
                "audit_events": [serialize_model(x) for x in events],
                "visible_debits": debits,
                "visible_credits": credits,
                "visible_balanced": debits == credits,
            }
        )
    return base


@app.post("/api/payments/{payment_id}/capture", response_model=SimulationResult)
async def post_capture(
    payment_id: str,
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> SimulationResult:
    require_permission(role, "payments:capture")
    payment, steps, run_id = await capture_payment(session, payment_id, payload.amount, role)
    return SimulationResult(run_id=run_id, payment=payment, steps=steps)


@app.post("/api/risk-cases/{case_id}/decision")
async def risk_decision(
    case_id: str,
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "risk:review")
    case, steps = await resolve_risk(session, case_id, payload.action, payload.note or "", role)
    return {"resource": serialize_model(case), "steps": steps}


@app.post("/api/settlements")
async def post_settlement(
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "settlements:create")
    if not payload.amount or not payload.idempotency_key:
        raise HTTPException(422, "Amount and idempotency_key are required")
    settlement, steps, replayed = await create_settlement(
        session, payload.amount, payload.idempotency_key, role
    )
    return {"resource": serialize_model(settlement), "steps": steps, "replayed": replayed}


@app.post("/api/settlements/{settlement_id}/action")
async def update_settlement(
    settlement_id: str,
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if role != "operations_admin":
        raise HTTPException(403, "Only operations administrators manage bank outcomes")
    settlement, steps = await settlement_action(session, settlement_id, payload.action, role)
    return {"resource": serialize_model(settlement), "steps": steps}


@app.post("/api/disputes/{dispute_id}/action")
async def update_dispute(
    dispute_id: str,
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    required = "disputes:evidence" if payload.action == "evidence" else "disputes:manage"
    require_permission(role, required)
    dispute, steps = await dispute_action(
        session, dispute_id, payload.action, payload.note or "", role
    )
    return {"resource": serialize_model(dispute), "steps": steps}


@app.post("/api/api-keys")
async def post_api_key(
    payload: ResourceCreate,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "api_keys:write")
    key, secret = await create_api_key(session, payload.name, payload.value.split(","), role)
    return {
        "resource": serialize_model(key),
        "secret": secret,
        "warning": "This key is shown once and only its SHA-256 hash is stored.",
    }


@app.post("/api/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "api_keys:write")
    key = await session.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API key not found")
    key.status = "revoked"
    key.revoked_at = datetime.now(UTC)
    await session.commit()
    return {"resource": serialize_model(key)}


@app.post("/api/webhooks")
async def post_webhook(
    payload: ResourceCreate,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "webhooks:write")
    endpoint, secret = await create_webhook(session, payload.value, role)
    return {
        "resource": serialize_model(endpoint),
        "secret": secret,
        "warning": "Signing secret is shown once.",
    }


@app.post("/api/webhook-deliveries/{delivery_id}/replay")
async def replay_webhook(
    delivery_id: str,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    require_permission(role, "webhooks:write")
    delivery = await session.get(WebhookDelivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "Delivery not found")
    delivery.status = "delivered"
    delivery.response_code = 200
    delivery.attempts += 1
    delivery.next_retry_at = None
    await session.commit()
    return {
        "resource": serialize_model(delivery),
        "steps": [
            step(
                "sign",
                "Fresh signature generated",
                "Timestamped HMAC prevents replay outside the accepted window.",
                "success",
                14,
            ),
            step(
                "delivery",
                "Endpoint returned HTTP 200",
                "Manual replay creates a new delivery attempt without duplicating the financial event.",
                "success",
                240,
            ),
        ],
    }


@app.post("/api/processors/{processor_id}/health")
async def processor_health(
    processor_id: str,
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if role != "operations_admin":
        raise HTTPException(403, "Only operations administrators configure processors")
    processor = await session.get(Processor, processor_id)
    if not processor:
        raise HTTPException(404, "Processor not found")
    if payload.action not in {"healthy", "degraded", "offline"}:
        raise HTTPException(422, "Unsupported processor health")
    processor.health = payload.action
    processor.enabled = payload.action != "offline"
    await session.commit()
    return {
        "resource": serialize_model(processor),
        "steps": [
            step(
                "circuit",
                "Routing circuit updated",
                "New payments immediately exclude offline processors while existing references remain recoverable.",
                "success",
                20,
                payload.action,
            )
        ],
    }


@app.post("/api/reconciliation/{case_id}/resolve")
async def resolve_reconciliation(
    case_id: str,
    payload: ActionRequest,
    role: str = Depends(current_role),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if role != "operations_admin":
        raise HTTPException(403, "Only operations administrators resolve reconciliation")
    case = await session.get(ReconciliationCase, case_id)
    if not case:
        raise HTTPException(404, "Reconciliation case not found")
    case.status = "resolved"
    case.resolution = payload.note or "Confirmed against processor report"
    case.resolved_at = datetime.now(UTC)
    await session.commit()
    return {
        "resource": serialize_model(case),
        "steps": [
            step(
                "compare",
                "Evidence compared",
                "Internal and processor references were matched deterministically.",
                "success",
                35,
            ),
            step("resolution", "Case resolved", case.resolution, "success", 15),
        ],
    }


@app.get("/api/audit")
async def audit(
    role: str = Depends(current_role), session: AsyncSession = Depends(get_session)
) -> dict:
    require_permission(role, "audit:read")
    events = (
        await session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100))
    ).all()
    return {
        "events": [
            {
                "id": event.id,
                "actor_role": event.actor_role,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "details": event.details,
                "created_at": event.created_at,
            }
            for event in events
        ]
    }
