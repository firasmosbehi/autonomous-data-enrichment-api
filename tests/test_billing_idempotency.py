"""Tests for billing idempotency logic."""

from unittest.mock import patch

from enrichment_api import billing


def test_checkout_idempotency_returns_cached_url():
    with patch.dict(
        billing.PLANS,
        {
            "free": {"price": 0, "requests_per_month": 50, "stripe_price_id": None},
            "basic": {"price": 999, "requests_per_month": 500, "stripe_price_id": "price_basic"},
            "pro": {"price": 2999, "requests_per_month": 2000, "stripe_price_id": "price_pro"},
            "ultra": {"price": 9999, "requests_per_month": 10000, "stripe_price_id": "price_ultra"},
        },
        clear=True,
    ):
        with patch("stripe.checkout.Session.create") as create_session:
            create_session.return_value = type("Session", (), {"url": "https://checkout.stripe.com/mock"})

            first = billing.create_checkout_session(
                email="idempotency@example.com",
                plan="basic",
                success_url="https://ok",
                cancel_url="https://cancel",
                idempotency_key="idem-checkout",
            )
            second = billing.create_checkout_session(
                email="idempotency@example.com",
                plan="basic",
                success_url="https://ok",
                cancel_url="https://cancel",
                idempotency_key="idem-checkout",
            )

    assert first == second
    assert create_session.call_count == 1


def test_webhook_duplicate_event_is_ignored():
    fake_event = {
        "id": "evt_duplicate_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer_email": "dup@example.com",
                "metadata": {"email": "dup@example.com", "plan": "basic"},
                "customer": "cus_dup",
                "subscription": "sub_dup",
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=fake_event):
        with patch("enrichment_api.billing._upgrade_or_create_key", return_value="enrich_key") as upgrade:
            first = billing.handle_webhook(b"{}", "sig")
            second = billing.handle_webhook(b"{}", "sig")

    assert first["status"] == "success"
    assert second["status"] == "ignored"
    assert second["reason"] == "duplicate_event"
    assert upgrade.call_count == 1
