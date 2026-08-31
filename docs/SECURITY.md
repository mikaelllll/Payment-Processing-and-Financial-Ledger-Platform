# Security model

## Demonstration design

Role switching is intentionally frictionless so portfolio visitors can inspect every perspective. It is not presented as production authentication. No real credentials, cardholder data, bank accounts or payment-provider keys are used or stored.

## Implemented controls

- Strict Pydantic request validation and bounded integer amounts.
- Role and permission checks at API mutation boundaries.
- Per-merchant idempotency keys and request fingerprints.
- Database uniqueness constraints and transactional state changes.
- Immutable audit and ledger history.
- Minimal CORS methods and headers.
- Non-root API container.
- No secrets committed; local Compose credentials are explicitly local-only.

## Required before real-world use

A real payment platform would require audited identity, short-lived sessions, merchant API-key hashing and rotation, KMS-backed secret encryption, network isolation, PCI DSS scope analysis, processor contracts, stronger ledger database permissions, tamper-evident audit export, reconciliation controls, disaster recovery and independent security review.

The simulator must never be used with genuine payment data.

