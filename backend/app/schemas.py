from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import PaymentStatus


class PaymentCreate(BaseModel):
    merchant_id: str = "mer_demo"
    amount: int = Field(ge=100, le=100_000_000)
    currency: Literal["BRL", "USD", "EUR"] = "BRL"
    customer_reference: str = Field(min_length=2, max_length=120)
    idempotency_key: str = Field(min_length=4, max_length=120)
    scenario: Literal["success", "declined", "timeout_before", "ambiguous", "high_risk"] = "success"
    capture_method: Literal["automatic", "manual"] = "automatic"


class MoneyOperation(BaseModel):
    amount: int = Field(gt=0)
    idempotency_key: str = Field(min_length=4, max_length=120)


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    merchant_id: str
    amount: int
    currency: str
    status: PaymentStatus
    processor: str
    captured_amount: int
    refunded_amount: int
    customer_reference: str
    created_at: datetime


class SimulationStep(BaseModel):
    key: str
    title: str
    detail: str
    status: Literal["success", "warning", "error", "info"]
    duration_ms: int = Field(ge=0)
    evidence: str | None = None


class SimulationResult(BaseModel):
    run_id: str
    payment: PaymentRead
    replayed: bool = False
    steps: list[SimulationStep]


class SeedRequest(BaseModel):
    size: Literal["small", "medium", "large"] = "medium"
    reset: bool = False


class RoleContext(BaseModel):
    role: Literal[
        "merchant_owner", "merchant_developer", "operations_admin", "risk_analyst", "auditor"
    ]

    @model_validator(mode="after")
    def known_role(self) -> "RoleContext":
        return self
