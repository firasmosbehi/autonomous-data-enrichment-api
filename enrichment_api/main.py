"""FastAPI app with POST endpoint for data enrichment."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, EmailStr

from .schemas import EnrichmentRequest, EnrichmentResponse, BatchEnrichmentRequest, BatchEnrichmentResponse
from .llm import enrich_data
from . import billing
import asyncio

load_dotenv()


class RegisterRequest(BaseModel):
    """Request to register for a free API key."""
    email: EmailStr


class CheckoutRequest(BaseModel):
    """Request to create a checkout session."""
    email: EmailStr
    plan: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    yield


app = FastAPI(
    title="Data Enrichment API",
    description="""
Transform messy, unstructured data into perfectly structured JSON using AI + live web search.

## Features
- **Company Enrichment** - Get domain, industry, HQ, employee count, LinkedIn from just a company name
- **Domain Enrichment** - Get company info from a website domain
- **Address Parsing** - Parse and validate addresses into structured components
- **Person Lookup** - Find professional info, title, company from a name
- **Batch Processing** - Enrich up to 10 items in a single request

## How It Works
1. Register for a free API key at `/api/v1/register`
2. Send requests with `X-API-Key` header
3. AI searches the web and returns validated JSON

## Pricing
| Plan | Requests/Month | Price |
|------|---------------|-------|
| Free | 50 | $0 |
| Basic | 500 | $9.99/mo |
| Pro | 2,000 | $29.99/mo |
| Ultra | 10,000 | $99.99/mo |
""",
    version="1.0.0",
    lifespan=lifespan,
    contact={"name": "API Support", "url": "https://github.com/firasmosbehi/autonomous-data-enrichment-api"},
    license_info={"name": "MIT"},
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors with 500 status."""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "success": False},
    )


def verify_rapidapi_secret(
    x_rapidapi_proxy_secret: str | None = Header(None),
) -> bool:
    """Verify RapidAPI proxy secret if configured."""
    expected_secret = os.getenv("RAPIDAPI_PROXY_SECRET")
    if expected_secret and x_rapidapi_proxy_secret != expected_secret:
        return False
    return True


@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page with API overview."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Data Enrichment API</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 50px auto; padding: 20px; background: #0d1117; color: #c9d1d9; }
            h1 { color: #58a6ff; }
            h2 { color: #8b949e; border-bottom: 1px solid #30363d; padding-bottom: 8px; }
            a { color: #58a6ff; }
            .card { background: #161b22; padding: 20px; border-radius: 8px; margin: 15px 0; border: 1px solid #30363d; }
            code { background: #21262d; padding: 2px 6px; border-radius: 4px; font-size: 14px; }
            pre { background: #21262d; padding: 15px; border-radius: 8px; overflow-x: auto; }
            .method { color: #7ee787; font-weight: bold; }
            .price { font-size: 24px; color: #58a6ff; }
            .pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
            .plan { text-align: center; }
            .plan h3 { margin: 0; color: #f0f6fc; }
            .plan .requests { color: #8b949e; font-size: 14px; }
            .btn { display: inline-block; background: #238636; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; margin-top: 10px; }
            .btn:hover { background: #2ea043; }
        </style>
    </head>
    <body>
        <h1>Data Enrichment API</h1>
        <p>Transform messy, unstructured data into perfectly structured JSON using AI + live web search.</p>

        <h2>Pricing</h2>
        <div class="pricing-grid">
            <div class="card plan">
                <h3>Free</h3>
                <p class="price">$0</p>
                <p class="requests">50 requests/month</p>
                <a href="/docs#/default/register_endpoint_api_v1_register_post" class="btn">Get Free Key</a>
            </div>
            <div class="card plan">
                <h3>Basic</h3>
                <p class="price">$9.99/mo</p>
                <p class="requests">500 requests/month</p>
            </div>
            <div class="card plan">
                <h3>Pro</h3>
                <p class="price">$29.99/mo</p>
                <p class="requests">2,000 requests/month</p>
            </div>
            <div class="card plan">
                <h3>Ultra</h3>
                <p class="price">$99.99/mo</p>
                <p class="requests">10,000 requests/month</p>
            </div>
        </div>

        <h2>Quick Start</h2>
        <div class="card">
            <p><strong>1. Get your free API key:</strong></p>
            <pre><code>curl -X POST https://enrichment-api-ttpv.onrender.com/api/v1/register \\
  -H "Content-Type: application/json" \\
  -d '{"email": "you@example.com"}'</code></pre>

            <p><strong>2. Make enrichment requests:</strong></p>
            <pre><code>curl -X POST https://enrichment-api-ttpv.onrender.com/api/v1/enrich \\
  -H "X-API-Key: your_api_key" \\
  -H "Content-Type: application/json" \\
  -d '{"raw_data": "Stripe payments", "data_type": "company"}'</code></pre>
        </div>

        <h2>Documentation</h2>
        <ul>
            <li><a href="/docs">Swagger UI (Interactive)</a></li>
            <li><a href="/redoc">ReDoc (Reference)</a></li>
        </ul>
    </body>
    </html>
    """


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/api/v1/register")
async def register_endpoint(request: RegisterRequest):
    """
    Register for a free API key.

    Provide your email to get an API key with 50 free requests/month.
    """
    result = billing.create_free_api_key(request.email)
    return {
        "api_key": result["api_key"],
        "plan": result["plan"],
        "requests_per_month": billing.PLANS[result["plan"]]["requests_per_month"],
        "message": "Key already exists for this email" if result.get("already_exists") else "API key created successfully",
    }


@app.post("/api/v1/checkout")
async def checkout_endpoint(request: CheckoutRequest):
    """
    Create a Stripe checkout session to upgrade your plan.

    Available plans: basic ($9.99), pro ($29.99), ultra ($99.99)
    """
    if request.plan not in ["basic", "pro", "ultra"]:
        raise HTTPException(status_code=400, detail="Invalid plan. Choose: basic, pro, or ultra")

    try:
        base_url = os.getenv("BASE_URL", "https://enrichment-api-ttpv.onrender.com")
        checkout_url = billing.create_checkout_session(
            email=request.email,
            plan=request.plan,
            success_url=f"{base_url}/checkout/success",
            cancel_url=f"{base_url}/checkout/cancel",
        )
        return {"checkout_url": checkout_url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@app.get("/checkout/success", response_class=HTMLResponse)
async def checkout_success():
    """Success page after checkout."""
    return """
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h1>Payment Successful!</h1>
    <p>Your API key has been upgraded. Check your email for details.</p>
    <p><a href="/docs">Go to API Documentation</a></p>
    </body></html>
    """


@app.get("/checkout/cancel", response_class=HTMLResponse)
async def checkout_cancel():
    """Cancel page for checkout."""
    return """
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h1>Checkout Cancelled</h1>
    <p>Your payment was not processed.</p>
    <p><a href="/">Go back home</a></p>
    </body></html>
    """


@app.post("/api/v1/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint for payment events.

    Configure this URL in your Stripe dashboard.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    result = billing.handle_webhook(payload, sig_header)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/v1/enrich", response_model=EnrichmentResponse)
async def enrich_endpoint(
    request: EnrichmentRequest,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_rapidapi_proxy_secret: str | None = Header(None, alias="X-RapidAPI-Proxy-Secret"),
):
    """
    Enrich raw, unstructured data and return structured JSON.

    **Authentication:** Include your API key in the `X-API-Key` header.
    Get a free key at `/api/v1/register`.

    **Supported data types:**
    - `company` - Enrich company names to get domain, industry, HQ, etc.
    - `domain` - Get company info from a website domain
    - `address` - Parse and validate addresses
    - `person` - Find professional info for individuals

    **Example:**
    ```bash
    curl -X POST /api/v1/enrich \\
      -H "X-API-Key: your_api_key" \\
      -H "Content-Type: application/json" \\
      -d '{"raw_data": "Stripe", "data_type": "company"}'
    ```
    """
    # Check RapidAPI auth first (if configured)
    if verify_rapidapi_secret(x_rapidapi_proxy_secret):
        pass  # RapidAPI auth passed
    elif x_api_key:
        # Validate API key
        validation = billing.validate_api_key(x_api_key)
        if not validation:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if not validation.get("valid"):
            if validation.get("error") == "rate_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Upgrade your plan at /api/v1/checkout. Current plan: {validation.get('plan')}",
                )
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Increment usage
        billing.increment_usage(x_api_key)
    else:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication. Provide X-API-Key header. Get a free key at /api/v1/register",
        )

    try:
        result = await enrich_data(request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/enrich/batch", response_model=BatchEnrichmentResponse)
async def batch_enrich_endpoint(
    request: BatchEnrichmentRequest,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_rapidapi_proxy_secret: str | None = Header(None, alias="X-RapidAPI-Proxy-Secret"),
):
    """
    Enrich multiple items in a single request (max 10).

    **Authentication:** Include your API key in the `X-API-Key` header.

    **Note:** Each item counts as one request against your rate limit.

    **Example:**
    ```json
    {
        "items": [
            {"raw_data": "Stripe", "data_type": "company"},
            {"raw_data": "stripe.com", "data_type": "domain"},
            {"raw_data": "Patrick Collison", "data_type": "person"}
        ]
    }
    ```
    """
    # Check RapidAPI auth first (if configured)
    if verify_rapidapi_secret(x_rapidapi_proxy_secret):
        pass
    elif x_api_key:
        validation = billing.validate_api_key(x_api_key)
        if not validation:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if not validation.get("valid"):
            if validation.get("error") == "rate_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Upgrade your plan at /api/v1/checkout. Current plan: {validation.get('plan')}",
                )
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Check if user has enough requests remaining
        remaining = validation.get("requests_remaining", 0)
        if remaining < len(request.items):
            raise HTTPException(
                status_code=429,
                detail=f"Not enough requests remaining. Need {len(request.items)}, have {remaining}. Upgrade at /api/v1/checkout",
            )
    else:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication. Provide X-API-Key header. Get a free key at /api/v1/register",
        )

    # Process all items concurrently
    async def process_item(item: EnrichmentRequest) -> EnrichmentResponse:
        try:
            return await enrich_data(item)
        except Exception:
            return EnrichmentResponse(
                success=False,
                data_type=item.data_type,
                original_input=item.raw_data,
                company=None,
                address=None,
                person=None,
                domain_info=None,
                confidence_score=0.0,
                sources=[],
            )

    results = await asyncio.gather(*[process_item(item) for item in request.items])

    # Increment usage for each item processed
    if x_api_key:
        for _ in request.items:
            billing.increment_usage(x_api_key)

    successful = sum(1 for r in results if r.success)

    return BatchEnrichmentResponse(
        success=True,
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )
