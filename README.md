# LedgerFlow — Payment Processing & Financial Ledger Platform

LedgerFlow is a production-style payment infrastructure simulation built to make normally invisible financial-safety decisions observable. It accepts merchant payment requests, applies idempotency and risk controls, routes them through simulated processors, recovers ambiguous outcomes without duplicate charges, and records money movement in an immutable double-entry ledger.

The project is intentionally **not connected to real payment methods or money**. It is an engineering portfolio system for exploring correctness, failure recovery, financial accounting, and asynchronous integration patterns.

## Run in GitHub Codespaces

1. Select **Code → Codespaces → Create codespace on main**.
2. If GitHub asks whether you trust the repository, accept it and wait for the terminal to become available.
3. The dev container automatically builds and starts PostgreSQL, Redis, the API, outbox worker, and frontend. No manual installation is required.
4. After every service passes its health check, the terminal prints the complete frontend URL and attempts to open it automatically.
5. If the browser did not open, Ctrl+click the printed URL. If its initial terminal message was missed, print it again with:

   ```bash
   bash .devcontainer/show-url.sh
   ```

The application runs on forwarded port `3000`; API documentation is available through the printed `/api/docs` URL. Codespaces can finish its startup hook before a browser session is attached, so the manual command remains the reliable fallback.

To inspect service health:

```bash
docker compose ps
docker compose logs --tail=100 api worker
```

## What you can test

- Switch between Merchant owner, Merchant developer, Operations administrator, Risk analyst, and Auditor perspectives.
- Use a genuinely different operational workspace for every role rather than a shared dashboard with cosmetic labels.
- Generate small, medium, or large deterministic datasets with one click.
- Run successful, declined, high-risk, pre-submission failure, and ambiguous-timeout payments.
- Replay a successful request with the same idempotency key and observe that no second charge or ledger transaction is created.
- Inspect the exact debit and credit entries behind captured and refunded payments.
- Capture authorizations, create settlements, simulate bank outcomes, submit dispute evidence, resolve risk reviews and reconcile processor exceptions.
- Create and revoke hashed API keys, configure signed webhook endpoints and replay failed deliveries.
- Explore API contracts interactively in Swagger UI.

Every simulation presents an animated execution trace covering authentication, validation, idempotency, fraud rules, processor routing, uncertainty classification, recovery, accounting, and transactional event delivery.

## Architecture at a glance

```text
React + TypeScript dashboard
            │
            ▼
       FastAPI boundary
            │
  ┌─────────┼───────────┐
  ▼         ▼           ▼
Payment   PostgreSQL   Redis Stream
engine    + ledger     + worker
  │          │           │
  ▼          ▼           ▼
Simulated  Immutable   Transactional
processors journal     outbox delivery
```

Money is stored as integer minor units. Financial entries are append-only and accepted only when total debits equal total credits. External timeouts are classified by whether submission occurred, because retrying an ambiguous result through another processor can charge a customer twice.

## Key engineering decisions

- **Represent money as integer minor units:** financial calculations avoid binary floating-point rounding errors.
- **Use an append-only double-entry ledger:** every accepted transaction must balance total debits and credits, preserving an auditable accounting history.
- **Make payment requests idempotent:** merchant keys bind retries to the original result so network repetition cannot create a second logical charge.
- **Distinguish pre-submission and ambiguous failures:** requests known not to have reached a processor may be retried safely; uncertain outcomes require reconciliation before another charge attempt.
- **Publish through a transactional outbox:** payment state and events commit atomically before the worker delivers them through Redis Streams.
- **Model role-specific workspaces:** operational permissions and workflows differ by role rather than being cosmetic dashboard filters.

## Trade-offs

- Strong idempotency requires retaining request fingerprints and prior responses, increasing storage and lifecycle complexity.
- An immutable ledger corrects mistakes through compensating entries instead of updates, producing more records but preserving history.
- Asynchronous outbox delivery is reliable but introduces eventual consistency between a committed payment and downstream consumers.
- Simulated processors make failure modes deterministic and safe to demonstrate, but do not reproduce every behavior of real acquiring networks.
- The project demonstrates financial invariants and recovery patterns; real processing would additionally require PCI DSS controls, managed secrets, compliance review, and external reconciliation.

## Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Components, data flow, consistency boundaries and technology decisions |
| [Payment lifecycle](docs/PAYMENT_LIFECYCLE.md) | Authorization, capture, ambiguity, refunds, idempotency and accounting |
| [Roles and demo guide](docs/DEMO_GUIDE.md) | What each perspective can access and suggested demonstrations |
| [Operations and Codespaces](docs/OPERATIONS.md) | Startup, service health, database reset and troubleshooting |
| [Security model](docs/SECURITY.md) | Demo boundaries, threat model, secret handling and production gaps |
| [Testing strategy](docs/TESTING.md) | Financial invariants, failure paths, CI and local commands |
| [Role workflows](docs/ROLE_WORKFLOWS.md) | Complete capabilities and operational journeys for all five perspectives |

## Technology stack

- Python 3.12, FastAPI, Pydantic and async SQLAlchemy
- PostgreSQL 17 for payment state, immutable accounting and transactional outbox records
- Redis Streams for asynchronous event delivery
- React 19, TypeScript, Vite, Recharts and responsive CSS
- Docker Compose and GitHub Codespaces
- pytest, Ruff, TypeScript build verification and GitHub Actions

## Local development

Requirements: Docker with Compose.

```bash
docker compose up --build --wait
```

Open `http://localhost:3000`. Stop services with:

```bash
docker compose down
```

Persistent Docker volumes intentionally retain demonstration data between restarts. To remove local data:

```bash
docker compose down --volumes
```

## Engineering boundaries

LedgerFlow demonstrates production-oriented patterns but is not certified or suitable for real financial processing. It does not collect card data, contact banks, provide PCI DSS compliance, or move funds. Simulated processor behavior exists specifically to exercise recovery logic safely.

## License

Released under the [MIT License](LICENSE).
