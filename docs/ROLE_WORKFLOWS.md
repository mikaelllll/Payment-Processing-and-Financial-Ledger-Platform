# Role workflows

Every role uses a distinct backend read model and frontend workspace. The demonstration role header removes login friction but does not bypass authorization: mutation endpoints independently verify required permissions.

## Merchant owner

- Inspect captured activity and ledger-derived available balance.
- Capture authorized payments; pending risk cases remain excluded.
- Request idempotent settlements without reserving the same balance twice.
- Inspect payout state and bank references.
- View disputes, deadlines and evidence history.
- Submit evidence without resolving the processor outcome.
- Create payments and refunds through the shared failure laboratory and API.

## Merchant developer

- Create scoped API credentials. The plaintext value is returned once; only its SHA-256 hash and last four characters remain stored.
- Revoke credentials immediately.
- Register HTTPS webhook endpoints and receive a one-time signing secret.
- Inspect response codes, retry counts and event types.
- Manually replay unsuccessful delivery attempts with a fresh simulated signature.
- Inspect recent execution traces and idempotency decisions.

## Operations administrator

- Inspect processor success rate, latency, fees, currencies and health.
- Move processors between healthy, degraded and offline routing states.
- Inspect ambiguous-payment recovery and transactional outbox queues.
- Complete, fail or safely retry merchant settlements.
- Compare internal and processor reconciliation values.
- Resolve reconciliation exceptions with an attributable note.

## Risk analyst

- Inspect risk score and every deterministic signal contributing to it.
- Approve or reject held authorizations without silently capturing funds.
- Review enabled fraud rules and their actions.
- Inspect merchant-submitted dispute evidence.
- Mark disputes won or lost, producing the appropriate balanced ledger consequence.

## Auditor

- Read the latest immutable journal entries grouped by transaction ID.
- Compare global debit and credit totals.
- Inspect resource, actor, action and timestamp for operational changes.
- Perform no mutations; the API rejects attempts outside the role’s permission set.

## Cross-role journey

A high-risk payment demonstrates separation of duties:

1. A merchant application creates the payment.
2. The risk engine holds the authorization and creates a review case.
3. A Risk analyst reviews signals and approves or rejects it.
4. Approval makes it available to the Merchant owner for capture.
5. Capture adds balanced accounting entries and a transactional outbox event.
6. The worker publishes the event and records delivery attempts for configured developer endpoints.
7. The Auditor can trace the payment, accounting transaction and actors without modifying them.
