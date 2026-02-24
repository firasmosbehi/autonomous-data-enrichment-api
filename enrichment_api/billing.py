"""Stripe billing and API key management."""

import os
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path

import stripe

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Simple file-based storage for API keys (use Redis/DB in production)
KEYS_FILE = Path("/tmp/api_keys.json")

# Pricing plans
PLANS = {
    "free": {"price": 0, "requests_per_month": 50, "stripe_price_id": None},
    "basic": {"price": 999, "requests_per_month": 500, "stripe_price_id": os.getenv("STRIPE_PRICE_BASIC")},
    "pro": {"price": 2999, "requests_per_month": 2000, "stripe_price_id": os.getenv("STRIPE_PRICE_PRO")},
    "ultra": {"price": 9999, "requests_per_month": 10000, "stripe_price_id": os.getenv("STRIPE_PRICE_ULTRA")},
}


def _load_keys() -> dict:
    """Load API keys from file."""
    if KEYS_FILE.exists():
        return json.loads(KEYS_FILE.read_text())
    return {}


def _save_keys(keys: dict) -> None:
    """Save API keys to file."""
    KEYS_FILE.write_text(json.dumps(keys, indent=2, default=str))


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"enrich_{secrets.token_urlsafe(32)}"


def create_free_api_key(email: str) -> dict:
    """Create a free tier API key."""
    keys = _load_keys()

    # Check if email already has a key
    for key_id, data in keys.items():
        if data.get("email") == email:
            return {"api_key": key_id, "plan": data["plan"], "already_exists": True}

    api_key = generate_api_key()
    keys[api_key] = {
        "email": email,
        "plan": "free",
        "requests_used": 0,
        "requests_limit": PLANS["free"]["requests_per_month"],
        "created_at": datetime.utcnow().isoformat(),
        "resets_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
    }
    _save_keys(keys)

    return {"api_key": api_key, "plan": "free", "already_exists": False}


def validate_api_key(api_key: str) -> dict | None:
    """Validate an API key and check rate limits."""
    keys = _load_keys()

    if api_key not in keys:
        return None

    key_data = keys[api_key]

    # Check if reset is needed
    resets_at = datetime.fromisoformat(key_data["resets_at"])
    if datetime.utcnow() > resets_at:
        key_data["requests_used"] = 0
        key_data["resets_at"] = (datetime.utcnow() + timedelta(days=30)).isoformat()
        _save_keys(keys)

    # Check rate limit
    if key_data["requests_used"] >= key_data["requests_limit"]:
        return {"valid": False, "error": "rate_limit_exceeded", "plan": key_data["plan"]}

    return {"valid": True, "plan": key_data["plan"], "requests_remaining": key_data["requests_limit"] - key_data["requests_used"]}


def increment_usage(api_key: str) -> None:
    """Increment usage counter for an API key."""
    keys = _load_keys()
    if api_key in keys:
        keys[api_key]["requests_used"] += 1
        _save_keys(keys)


def create_checkout_session(email: str, plan: str, success_url: str, cancel_url: str) -> str:
    """Create a Stripe checkout session for a plan upgrade."""
    if plan not in PLANS or plan == "free":
        raise ValueError(f"Invalid plan: {plan}")

    price_id = PLANS[plan]["stripe_price_id"]
    if not price_id:
        raise ValueError(f"Stripe price not configured for plan: {plan}")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=email,
        metadata={"plan": plan, "email": email},
    )

    return session.url


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Handle Stripe webhook events."""
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return {"error": "Invalid payload"}
    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email") or session["metadata"].get("email")
        plan = session["metadata"].get("plan")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        if email and plan:
            _upgrade_or_create_key(email, plan, customer_id, subscription_id)

        return {"status": "success", "event": "checkout.session.completed"}

    if event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        _downgrade_to_free(subscription["id"])
        return {"status": "success", "event": "customer.subscription.deleted"}

    return {"status": "ignored", "event": event["type"]}


def _upgrade_or_create_key(email: str, plan: str, customer_id: str, subscription_id: str) -> str:
    """Upgrade existing key or create new one for paid plan."""
    keys = _load_keys()

    # Find existing key by email
    for key_id, data in keys.items():
        if data.get("email") == email:
            data["plan"] = plan
            data["requests_limit"] = PLANS[plan]["requests_per_month"]
            data["stripe_customer_id"] = customer_id
            data["stripe_subscription_id"] = subscription_id
            _save_keys(keys)
            return key_id

    # Create new key
    api_key = generate_api_key()
    keys[api_key] = {
        "email": email,
        "plan": plan,
        "requests_used": 0,
        "requests_limit": PLANS[plan]["requests_per_month"],
        "created_at": datetime.utcnow().isoformat(),
        "resets_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
    }
    _save_keys(keys)
    return api_key


def _downgrade_to_free(subscription_id: str) -> None:
    """Downgrade a subscription to free tier."""
    keys = _load_keys()

    for key_id, data in keys.items():
        if data.get("stripe_subscription_id") == subscription_id:
            data["plan"] = "free"
            data["requests_limit"] = PLANS["free"]["requests_per_month"]
            data["stripe_subscription_id"] = None
            _save_keys(keys)
            return
