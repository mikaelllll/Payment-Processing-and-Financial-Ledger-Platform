import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-ledgerflow.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_data(client: TestClient):
    response = client.post(
        "/api/demo/seed",
        headers={"X-Demo-Role": "operations_admin"},
        json={"size": "small", "reset": True},
    )
    assert response.status_code == 200
