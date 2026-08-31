# Roles and demonstration guide

The role selector intentionally changes permissions and perspective without requiring visitors to manage passwords. The `X-Demo-Role` header powers the same backend authorization checks used by the frontend.

| Role | Primary perspective |
|---|---|
| Merchant owner | Create payments, issue refunds and inspect business balances |
| Merchant developer | Diagnose idempotency, processor decisions and integration delivery |
| Operations administrator | View all infrastructure behavior, recovery and seed controls |
| Risk analyst | Observe high-risk decisions without permission to create charges |
| Auditor | Read ledger and audit evidence without mutating financial state |

## Recommended walkthrough

1. Generate the medium dataset.
2. Run **Successful capture** and inspect its three balanced ledger entries.
3. Select **Replay same idempotency key** and confirm the trace bypasses processor and accounting work.
4. Run **Ambiguous timeout** and observe why the system queries the original processor instead of falling back.
5. Run **Definitive decline** and confirm no ledger movement exists.
6. Switch to Auditor and confirm payment creation is disabled while journal inspection remains available.

Simulation latency is presented as recorded trace metadata; the interface animates the steps for comprehension rather than intentionally delaying backend requests.

