"""FastAPI app with POST endpoint for data enrichment."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

from .schemas import EnrichmentRequest, EnrichmentResponse
from .llm import enrich_data

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    yield


app = FastAPI(
    title="Autonomous Data Enrichment API",
    description="Accepts messy, unstructured data and returns perfectly structured JSON.",
    version="0.1.0",
    lifespan=lifespan,
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
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; background: #0d1117; color: #c9d1d9; }
            h1 { color: #58a6ff; }
            a { color: #58a6ff; }
            .endpoint { background: #161b22; padding: 15px; border-radius: 8px; margin: 15px 0; border: 1px solid #30363d; }
            code { background: #21262d; padding: 2px 6px; border-radius: 4px; }
            .method { color: #7ee787; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>Autonomous Data Enrichment API</h1>
        <p>Transform messy, unstructured data into perfectly structured JSON.</p>

        <h2>Quick Links</h2>
        <ul>
            <li><a href="/docs">Swagger UI Documentation</a></li>
            <li><a href="/redoc">ReDoc Documentation</a></li>
        </ul>

        <h2>Endpoints</h2>
        <div class="endpoint">
            <p><span class="method">POST</span> <code>/api/v1/enrich</code></p>
            <p>Enrich raw data (company names, addresses, persons) and return structured JSON.</p>
        </div>
        <div class="endpoint">
            <p><span class="method">GET</span> <code>/health</code></p>
            <p>Health check endpoint.</p>
        </div>

        <h2>Example</h2>
        <pre><code>curl -X POST http://localhost:8000/api/v1/enrich \\
  -H "Content-Type: application/json" \\
  -d '{"raw_data": "Apple Inc", "data_type": "company"}'</code></pre>
    </body>
    </html>
    """


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/api/v1/enrich", response_model=EnrichmentResponse)
async def enrich_endpoint(
    request: EnrichmentRequest,
    x_rapidapi_proxy_secret: str | None = Header(None),
):
    """
    Enrich raw, unstructured data and return structured JSON.

    Accepts messy data payloads (company names, addresses, etc.),
    researches missing information, and returns validated structured data.

    Args:
        request: The enrichment request with raw data.
        x_rapidapi_proxy_secret: RapidAPI proxy secret for authentication.

    Returns:
        EnrichmentResponse: Structured, validated enrichment data.

    Raises:
        HTTPException: 401 for invalid credentials, 400 for bad input.
    """
    if not verify_rapidapi_secret(x_rapidapi_proxy_secret):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing RapidAPI proxy secret",
        )

    try:
        result = await enrich_data(request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
