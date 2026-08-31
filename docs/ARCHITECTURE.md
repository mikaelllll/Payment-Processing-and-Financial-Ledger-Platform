# Architecture

## Design goals

LedgerFlow prioritizes correctness, explainability and recoverability. Components are separated when they have different consistency or operational responsibilities, not merely to increase the apparent number of services.

## Runtime components

| Component | Responsibility |
|---|---|
| Frontend | Role-aware operational UI, payment laboratory, execution traces and ledger inspection |
| API | Validation, authorization boundary, orchestration and read models |
| PostgreSQL | Source of truth for payment state, accounting entries, audit events and outbox records |
| Worker | Claims committed outbox records and publishes them to Redis without blocking payments |
| Redis | Bounded event stream for downstream delivery and inspection |
| Simulated processors | Deterministic external success, decline, timeout and ambiguity behavior |

The API and worker share the domain package in this portfolio deployment. In a larger organization, scaling or ownership pressure could justify deploying selected bounded contexts independently. Starting with a modular service avoids distributed transactions without losing explicit domain boundaries.

## Consistency boundaries

A payment state change, ledger posting, audit event and outbox event are committed in one PostgreSQL transaction. External notification is intentionally asynchronous. If Redis is unavailable, committed outbox rows remain pending and the worker safely retries later.

Ledger transactions contain multiple immutable entries. The posting service verifies debit and credit totals before the entries enter the session. Payments use a unique `(merchant_id, idempotency_key)` constraint as the final concurrency guard.

## Why PostgreSQL and Redis

PostgreSQL provides transactions, row locks, constraints and auditable relational history for money-related state. Redis is not the financial source of truth; it carries disposable/replayable event delivery data after durable PostgreSQL commit.

## Scaling direction

- Stateless API replicas behind a load balancer.
- Outbox workers using `FOR UPDATE SKIP LOCKED` to divide delivery work.
- Read replicas or warehouse exports for expensive analytics.
- Partitioned ledger and payment tables after measured need.
- Per-merchant quotas and worker fairness.
- Processor-specific circuit breakers and isolated connection pools.

