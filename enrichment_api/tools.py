"""FastMCP server with search and scraping tools for the LLM."""

import asyncio
import os
import random

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

mcp = FastMCP("enrichment_mcp")

SERPER_TIMEOUT_SECONDS = float(os.getenv("SERPER_TIMEOUT_SECONDS", "20"))
SERPER_RETRY_ATTEMPTS = int(os.getenv("SERPER_RETRY_ATTEMPTS", "3"))
SERPER_BACKOFF_BASE_SECONDS = float(os.getenv("SERPER_BACKOFF_BASE_SECONDS", "0.75"))
SERPER_BACKOFF_JITTER_SECONDS = float(os.getenv("SERPER_BACKOFF_JITTER_SECONDS", "0.5"))
SERPER_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class CompanySearchInput(BaseModel):
    """Input schema for company search."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    query: str = Field(
        ...,
        description="Company name or domain to search",
        min_length=1,
        max_length=200,
    )


class WebSearchInput(BaseModel):
    """Input schema for general web search."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    query: str = Field(
        ...,
        description="Search query string",
        min_length=1,
        max_length=500,
    )
    num_results: int = Field(
        default=5,
        description="Number of results to return",
        ge=1,
        le=10,
    )


def _handle_api_error(e: Exception) -> str:
    """Handle API errors consistently across all tools."""
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 404:
            return "Error: Resource not found. Check the query."
        if e.response.status_code == 429:
            return "Error: Rate limit exceeded. Retry later."
        return f"Error: API returned status {e.response.status_code}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Retry."
    return f"Error: {type(e).__name__}"


def _retry_delay_seconds(attempt_number: int) -> float:
    """Return exponential backoff delay with jitter for retry loops."""
    return (SERPER_BACKOFF_BASE_SECONDS * (2 ** (attempt_number - 1))) + random.uniform(
        0,
        SERPER_BACKOFF_JITTER_SECONDS,
    )


async def _serper_search(api_key: str, query: str, num_results: int) -> dict:
    """Call Serper search API with retry/backoff on transient failures."""
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results}
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=SERPER_TIMEOUT_SECONDS) as client:
        for attempt in range(1, SERPER_RETRY_ATTEMPTS + 1):
            try:
                response = await client.post(
                    "https://google.serper.dev/search",
                    json=payload,
                    headers=headers,
                )
                if (
                    response.status_code in SERPER_RETRYABLE_STATUS_CODES
                    and attempt < SERPER_RETRY_ATTEMPTS
                ):
                    await asyncio.sleep(_retry_delay_seconds(attempt))
                    continue

                response.raise_for_status()
                return response.json()
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < SERPER_RETRY_ATTEMPTS:
                    await asyncio.sleep(_retry_delay_seconds(attempt))
                    continue
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if (
                    exc.response.status_code in SERPER_RETRYABLE_STATUS_CODES
                    and attempt < SERPER_RETRY_ATTEMPTS
                ):
                    await asyncio.sleep(_retry_delay_seconds(attempt))
                    continue
                raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("Serper search failed without specific exception")


@mcp.tool(
    name="enrichment_search_company",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def enrichment_search_company(params: CompanySearchInput) -> str:
    """Search for company information by name or domain.

    Use this tool when you need to find details about a company including
    their website, industry, headquarters, employee count, or other
    business information. Provide the company name or domain as the query.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return "Error: SERPER_API_KEY not configured"

    try:
        data = await _serper_search(api_key, f"{params.query} company info", 5)

        results = []
        for result in data.get("organic", [])[:5]:
            results.append(
                f"Title: {result.get('title', 'N/A')}\n"
                f"URL: {result.get('link', 'N/A')}\n"
                f"Description: {result.get('snippet', 'N/A')}\n"
            )

        if not results:
            return f"No results found for company: {params.query}"

        return "\n---\n".join(results)

    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="enrichment_web_search",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def enrichment_web_search(params: WebSearchInput) -> str:
    """Perform a general web search to gather information.

    Use this tool when you need to find general information about any topic,
    verify data, or search for specific details. Provide a clear search query.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return "Error: SERPER_API_KEY not configured"

    try:
        data = await _serper_search(api_key, params.query, params.num_results)

        results = []
        for result in data.get("organic", []):
            results.append(
                f"Title: {result.get('title', 'N/A')}\n"
                f"URL: {result.get('link', 'N/A')}\n"
                f"Description: {result.get('snippet', 'N/A')}\n"
            )

        if not results:
            return f"No results found for: {params.query}"

        return "\n---\n".join(results)

    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="enrichment_fetch_page",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def enrichment_fetch_page(url: str) -> str:
    """Fetch and extract text content from a webpage.

    Use this tool when you need to get detailed information from a specific
    webpage URL. Returns the page title and text content.
    """
    try:
        async with httpx.AsyncClient(timeout=SERPER_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; EnrichmentBot/1.0)"
                },
            )
            response.raise_for_status()

            content = response.text
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"

            return f"Content from {url}:\n\n{content}"

    except Exception as e:
        return _handle_api_error(e)
