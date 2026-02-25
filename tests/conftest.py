"""Shared test fixtures."""

import pytest

from enrichment_api import billing


@pytest.fixture(autouse=True)
def reset_billing_state():
    """Force in-memory mode and clear state between tests."""
    billing.REDIS_URL = None
    billing._redis_client = None
    billing._memory_store.clear()
    yield
    billing._memory_store.clear()
