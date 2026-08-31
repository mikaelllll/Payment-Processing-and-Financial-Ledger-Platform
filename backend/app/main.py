from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import Base, engine, get_session
from .models import AuditEvent, LedgerEntry, Merchant, SimulationRun
from .roles import ROLES, current_role, require_permission
from .schemas import MoneyOperation, PaymentCreate, PaymentRead, SeedRequest, SimulationResult
from .services import create_payment, dashboard, refund_payment, seed_demo


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if not await session.get(Merchant, "mer_demo"):
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
