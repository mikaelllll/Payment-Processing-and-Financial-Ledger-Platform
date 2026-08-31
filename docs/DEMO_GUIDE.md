# Roles and demonstration guide

The role selector intentionally changes permissions and perspective without requiring visitors to manage passwords. The `X-Demo-Role` header powers the same backend authorization checks used by the frontend.

| Role | Primary perspective |
|---|---|
| Merchant owner | Payments, manual capture, refunds, derived balances, settlements, payouts and dispute evidence |
| Merchant developer | API credentials, endpoints, signed deliveries, replay and execution diagnostics |
| Operations administrator | Processor routing health, recovery, settlement outcomes, reconciliation and outbox health |
| Risk analyst | Explainable review decisions, fraud rules, disputes and chargeback outcomes |
| Auditor | Global ledger proof, transaction evidence and actor-attributed audit history |

## Recommended walkthrough

1. Generate the medium dataset.
2. Run **Successful capture** and inspect its three balanced ledger entries.
3. Select **Replay same idempotency key** and confirm the trace bypasses processor and accounting work.
4. Run **Ambiguous timeout** and observe why the system queries the original processor instead of falling back.
5. Run **Definitive decline** and confirm no ledger movement exists.
6. Approve a high-risk payment as Risk analyst, switch to Merchant owner and capture it.
7. Create a settlement as Merchant owner, then complete or fail/retry it as Operations administrator.
8. Create a webhook and API key as Merchant developer; replay the seeded failed delivery.
9. Submit dispute evidence as Merchant owner and decide the case as Risk analyst.
10. Switch to Auditor and confirm every resulting debit and credit remains balanced.

Simulation latency is presented as recorded trace metadata; the interface animates the steps for comprehension rather than intentionally delaying backend requests.
