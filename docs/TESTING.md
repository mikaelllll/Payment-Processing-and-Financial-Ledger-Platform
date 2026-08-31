# Testing strategy

Tests prioritize financial invariants and failure paths:

- Successful capture creates exactly one balanced ledger transaction.
- Idempotent replay returns the original payment and creates no new entries.
- Reusing a key for different input is rejected.
- Ambiguous processor completion recovers without duplicate posting.
- Definitive declines produce no money movement.
- Partial and complete refunds preserve global balance.
- Over-refunds are rejected.
- Read-only roles cannot create payments.

Run backend verification:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
ruff check .
pytest -q
```

Run frontend verification:

```bash
cd frontend
npm install
npm run build
```

GitHub Actions runs backend lint/tests, strict TypeScript production build, Compose validation and image builds on pushes and pull requests. It can also be started manually.

