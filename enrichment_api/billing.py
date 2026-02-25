"""Stripe billing and API key management with Redis persistence."""

import os
import secrets
import json
from datetime import datetime, timedelta

import stripe
import redis

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Redis connection (falls back to in-memory dict if not configured)
REDIS_URL = os.getenv("REDIS_URL")
_redis_client = None
_memory_store = {}  # Fallback for local dev

def _get_redis():
    """Get Redis client, initialize if needed."""
    global _redis_client
    if REDIS_URL and _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _get_key_data(api_key: str) -> dict | None:
    """Get API key data from Redis or memory."""
    r = _get_redis()
    if r:
        data = r.get(f"apikey:{api_key}")
        return json.loads(data) if data else None
    return _memory_store.get(api_key)


def _set_key_data(api_key: str, data: dict) -> None:
    """Save API key data to Redis or memory."""
    r = _get_redis()
    if r:
        r.set(f"apikey:{api_key}", json.dumps(data, default=str))
        # Also index by email for lookups
        r.set(f"email:{data['email']}", api_key)
    else:
        _memory_store[api_key] = data


def _get_key_by_email(email: str) -> str | None:
    """Get API key by email."""
    r = _get_redis()
    if r:
        return r.get(f"email:{email}")
    for key, data in _memory_store.items():
        if data.get("email") == email:
            return key
    return None


def _get_key_by_subscription(subscription_id: str) -> str | None:
    """Get API key by Stripe subscription ID."""
    r = _get_redis()
    if r:
        return r.get(f"subscription:{subscription_id}")
    for key, data in _memory_store.items():
        if data.get("stripe_subscription_id") == subscription_id:
            return key
    return None


# Pricing plans
PLANS = {
    "free": {"price": 0, "requests_per_month": 50, "stripe_price_id": None},
    "basic": {"price": 999, "requests_per_month": 500, "stripe_price_id": os.getenv("STRIPE_PRICE_BASIC")},
    "pro": {"price": 2999, "requests_per_month": 2000, "stripe_price_id": os.getenv("STRIPE_PRICE_PRO")},
    "ultra": {"price": 9999, "requests_per_month": 10000, "stripe_price_id": os.getenv("STRIPE_PRICE_ULTRA")},
}


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"enrich_{secrets.token_urlsafe(32)}"


def create_free_api_key(email: str) -> dict:
    """Create a free tier API key."""
    # Check if email already has a key
    existing_key = _get_key_by_email(email)
    if existing_key:
        data = _get_key_data(existing_key)
        return {"api_key": existing_key, "plan": data["plan"], "already_exists": True}

    api_key = generate_api_key()
    key_data = {
        "email": email,
        "plan": "free",
        "requests_used": 0,
        "requests_limit": PLANS["free"]["requests_per_month"],
        "created_at": datetime.utcnow().isoformat(),
        "resets_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
    }
    _set_key_data(api_key, key_data)

    return {"api_key": api_key, "plan": "free", "already_exists": False}


def validate_api_key(api_key: str) -> dict | None:
    """Validate an API key and check rate limits."""
    key_data = _get_key_data(api_key)
    if not key_data:
        return None

    # Check if reset is needed
    resets_at = datetime.fromisoformat(key_data["resets_at"])
    if datetime.utcnow() > resets_at:
        key_data["requests_used"] = 0
        key_data["resets_at"] = (datetime.utcnow() + timedelta(days=30)).isoformat()
        _set_key_data(api_key, key_data)

    # Check rate limit
    if key_data["requests_used"] >= key_data["requests_limit"]:
        return {"valid": False, "error": "rate_limit_exceeded", "plan": key_data["plan"]}

    return {"valid": True, "plan": key_data["plan"], "requests_remaining": key_data["requests_limit"] - key_data["requests_used"]}


def increment_usage(api_key: str) -> None:
    """Increment usage counter for an API key."""
    key_data = _get_key_data(api_key)
    if key_data:
        key_data["requests_used"] += 1
        _set_key_data(api_key, key_data)


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
    r = _get_redis()

    # Find existing key by email
    existing_key = _get_key_by_email(email)
    if existing_key:
        key_data = _get_key_data(existing_key)
        old_subscription = key_data.get("stripe_subscription_id")

        key_data["plan"] = plan
        key_data["requests_limit"] = PLANS[plan]["requests_per_month"]
        key_data["stripe_customer_id"] = customer_id
        key_data["stripe_subscription_id"] = subscription_id
        _set_key_data(existing_key, key_data)

        # Update subscription index
        if r:
            if old_subscription:
                r.delete(f"subscription:{old_subscription}")
            r.set(f"subscription:{subscription_id}", existing_key)

        return existing_key

    # Create new key
    api_key = generate_api_key()
    key_data = {
        "email": email,
        "plan": plan,
        "requests_used": 0,
        "requests_limit": PLANS[plan]["requests_per_month"],
        "created_at": datetime.utcnow().isoformat(),
        "resets_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
    }
    _set_key_data(api_key, key_data)

    # Index by subscription
    if r:
        r.set(f"subscription:{subscription_id}", api_key)

    return api_key


def _downgrade_to_free(subscription_id: str) -> None:
    """Downgrade a subscription to free tier."""
    api_key = _get_key_by_subscription(subscription_id)
    if not api_key:
        return

    key_data = _get_key_data(api_key)
    if key_data:
        key_data["plan"] = "free"
        key_data["requests_limit"] = PLANS["free"]["requests_per_month"]
        key_data["stripe_subscription_id"] = None
        _set_key_data(api_key, key_data)

        # Remove subscription index
        r = _get_redis()
        if r:
            r.delete(f"subscription:{subscription_id}")
