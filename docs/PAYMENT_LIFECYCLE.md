# Payment lifecycle and invariants

## State model

Payments begin in `created`, pass through `processing`, and reach a definitive or recoverable state. Capture is separate from authorization because reserved funds are not yet merchant revenue.

Valid demonstrated states include `authorized`, `captured`, `partially_refunded`, `refunded`, `failed`, `cancelled`, `confirmation_required`, and `disputed`.

## Idempotency

The API fingerprints the semantic request and reserves the merchant/key pair before processor work. Reusing the key with the same request returns the original payment. Reusing it with different content returns `409 Conflict`. The database uniqueness constraint protects against concurrent duplicate insertion.

## Ambiguous processor outcomes

A timeout before submission is safe to retry. A timeout after submission is ambiguous: the processor may have completed the charge. LedgerFlow forbids blind fallback, stores `confirmation_required`, and queries the original processor using the stable reference. Accounting occurs only after a definitive result.

## Double-entry ledger

All amounts are integer minor units. A capture of 10,000 with a 300 platform fee posts:

| Account | Debit | Credit |
|---|---:|---:|
| Processor receivable | 10,000 | 0 |
| Merchant payable | 0 | 9,700 |
| Platform fee revenue | 0 | 300 |

The posting is rejected unless debits equal credits. Entries are not edited; refunds create new reversing entries.

## Refund concurrency

Refund creation locks the payment row, calculates the remaining refundable amount, and rejects over-refunds. Two concurrent refunds cannot both consume the same remaining balance.

## Transactional outbox

Payment mutations write an outbox event in the same database transaction. The worker later publishes committed events to Redis and marks the outbox row delivered. A messaging outage therefore cannot erase the financial result or cause the API transaction to depend on Redis availability.

