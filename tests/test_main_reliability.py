"""Tests for API-layer reliability behavior."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from enrichment_api.llm import EnrichmentTimeoutError, UpstreamServiceUnavailableError
from enrichment_api.main import app


def test_enrich_maps_upstream_unavailable_to_503():
    async def fake_enrich(_request):
        raise UpstreamServiceUnavailableError("Provider overloaded")

    client = TestClient(app)
    with patch("enrichment_api.main.enrich_data", new=fake_enrich):
        with patch.dict(os.environ, {"RAPIDAPI_PROXY_SECRET": "rapid-test"}, clear=False):
            response = client.post(
                "/api/v1/enrich",
                headers={"X-RapidAPI-Proxy-Secret": "rapid-test"},
                json={"raw_data": "OpenAI", "data_type": "company"},
            )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "15"
    detail = response.json()["detail"]
    assert detail["error"] == "upstream_unavailable"
    assert detail["retry_after_seconds"] == 15


def test_enrich_maps_timeout_to_503():
    async def fake_enrich(_request):
        raise EnrichmentTimeoutError("Timeout budget exceeded")

    client = TestClient(app)
    with patch("enrichment_api.main.enrich_data", new=fake_enrich):
        with patch.dict(os.environ, {"RAPIDAPI_PROXY_SECRET": "rapid-test"}, clear=False):
            response = client.post(
                "/api/v1/enrich",
                headers={"X-RapidAPI-Proxy-Secret": "rapid-test"},
                json={"raw_data": "OpenAI", "data_type": "company"},
            )

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "upstream_unavailable"


def test_checkout_forwards_idempotency_key():
    client = TestClient(app)
    with patch("enrichment_api.main.billing.create_checkout_session", return_value="https://checkout.stripe.com/mock") as create_checkout:
        response = client.post(
            "/api/v1/checkout",
            headers={"Idempotency-Key": "idem-123"},
            json={"email": "test@example.com", "plan": "basic"},
        )

    assert response.status_code == 200
    assert create_checkout.call_count == 1
    assert create_checkout.call_args.kwargs["idempotency_key"] == "idem-123"
