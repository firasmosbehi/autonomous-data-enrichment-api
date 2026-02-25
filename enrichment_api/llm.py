"""Async LLM orchestration via Instructor with live web search."""

import asyncio
import os
import random

import instructor
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    InternalServerError,
    RateLimitError,
)
from instructor.core.exceptions import InstructorRetryException

from .schemas import EnrichmentRequest, EnrichmentResponse
from .tools import CompanySearchInput, WebSearchInput, enrichment_search_company, enrichment_web_search

SEARCH_CONTEXT_TIMEOUT_SECONDS = float(os.getenv("SEARCH_CONTEXT_TIMEOUT_SECONDS", "30"))
LLM_CALL_TIMEOUT_SECONDS = float(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "45"))
ENRICH_TOTAL_TIMEOUT_SECONDS = float(os.getenv("ENRICH_TOTAL_TIMEOUT_SECONDS", "75"))
LLM_RETRY_ATTEMPTS = int(os.getenv("LLM_RETRY_ATTEMPTS", "3"))
LLM_BACKOFF_BASE_SECONDS = float(os.getenv("LLM_BACKOFF_BASE_SECONDS", "1.0"))
LLM_BACKOFF_JITTER_SECONDS = float(os.getenv("LLM_BACKOFF_JITTER_SECONDS", "0.6"))
INSTRUCTOR_VALIDATION_RETRIES = int(os.getenv("INSTRUCTOR_VALIDATION_RETRIES", "2"))
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class UpstreamServiceUnavailableError(RuntimeError):
    """Raised when upstream providers are temporarily unavailable."""


class EnrichmentTimeoutError(RuntimeError):
    """Raised when enrichment exceeds timeout budget."""


def _retry_delay_seconds(attempt_number: int) -> float:
    """Return exponential backoff delay with jitter."""
    return (LLM_BACKOFF_BASE_SECONDS * (2 ** (attempt_number - 1))) + random.uniform(
        0,
        LLM_BACKOFF_JITTER_SECONDS,
    )


def _model_chain() -> list[str]:
    """Build primary + fallback model chain from env vars."""
    primary = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip()
    fallback_env = os.getenv("ANTHROPIC_FALLBACK_MODELS", "claude-opus-4-6")
    fallbacks = [m.strip() for m in fallback_env.split(",") if m.strip()]
    chain: list[str] = []
    for model in [primary, *fallbacks]:
        if model and model not in chain:
            chain.append(model)
    return chain


def _is_retryable_llm_error(exc: Exception) -> bool:
    """Classify whether an LLM exception should be retried/failovered."""
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    if isinstance(exc, InstructorRetryException):
        message = str(exc).lower()
        return "overloaded" in message or "rate limit" in message or "error code: 529" in message
    return False


def _is_upstream_search_error(result: str) -> bool:
    """Detect retryable upstream search failures from tool output text."""
    lowered = result.lower()
    return (
        lowered.startswith("error:")
        and (
            "rate limit" in lowered
            or "timed out" in lowered
            or "api returned status 5" in lowered
            or "api returned status 429" in lowered
            or "connecterror" in lowered
        )
    )


async def _call_search_or_raise(search_coro, provider_name: str) -> str:
    """Execute search call and raise service-unavailable on transient provider failures."""
    result = await search_coro
    if _is_upstream_search_error(result):
        raise UpstreamServiceUnavailableError(
            f"{provider_name} is temporarily unavailable. Please retry shortly."
        )
    return result


async def _call_llm_with_fallback(
    client,
    user_message: str,
    system_prompt: str,
) -> EnrichmentResponse:
    """Call Anthropic with retries and model failover chain."""
    last_error: Exception | None = None
    for model in _model_chain():
        for attempt in range(1, LLM_RETRY_ATTEMPTS + 1):
            try:
                async with asyncio.timeout(LLM_CALL_TIMEOUT_SECONDS):
                    return await client.chat.completions.create(
                        model=model,
                        max_tokens=2000,
                        max_retries=INSTRUCTOR_VALIDATION_RETRIES,
                        messages=[{"role": "user", "content": user_message}],
                        system=system_prompt,
                        response_model=EnrichmentResponse,
                    )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                last_error = exc
                if attempt < LLM_RETRY_ATTEMPTS:
                    await asyncio.sleep(_retry_delay_seconds(attempt))
                    continue
            except Exception as exc:
                last_error = exc
                if _is_retryable_llm_error(exc) and attempt < LLM_RETRY_ATTEMPTS:
                    await asyncio.sleep(_retry_delay_seconds(attempt))
                    continue
                if not _is_retryable_llm_error(exc):
                    raise
        # Try next model in chain if retries were exhausted
        continue

    if last_error is not None:
        raise UpstreamServiceUnavailableError(
            "LLM provider is temporarily unavailable. Please retry in a few seconds."
        ) from last_error
    raise UpstreamServiceUnavailableError("LLM provider is temporarily unavailable.")


async def _gather_search_context(request: EnrichmentRequest) -> str:
    """Fetch live data from web search based on data type."""
    search_results = []

    if request.data_type == "company":
        result = await _call_search_or_raise(
            enrichment_search_company(CompanySearchInput(query=request.raw_data)),
            provider_name="Search provider",
        )
        search_results.append(f"Company search results:\n{result}")

        linkedin_result = await _call_search_or_raise(
            enrichment_web_search(
                WebSearchInput(query=f"{request.raw_data} linkedin company", num_results=3)
            ),
            provider_name="Search provider",
        )
        search_results.append(f"LinkedIn search:\n{linkedin_result}")

    elif request.data_type == "person":
        result = await _call_search_or_raise(
            enrichment_web_search(
                WebSearchInput(query=f"{request.raw_data} professional profile", num_results=5)
            ),
            provider_name="Search provider",
        )
        search_results.append(f"Person search results:\n{result}")

        linkedin_result = await _call_search_or_raise(
            enrichment_web_search(
                WebSearchInput(query=f"{request.raw_data} linkedin", num_results=3)
            ),
            provider_name="Search provider",
        )
        search_results.append(f"LinkedIn search:\n{linkedin_result}")

    elif request.data_type == "address":
        result = await _call_search_or_raise(
            enrichment_web_search(
                WebSearchInput(query=f"{request.raw_data} address location", num_results=5)
            ),
            provider_name="Search provider",
        )
        search_results.append(f"Address search results:\n{result}")

    elif request.data_type == "domain":
        # Search for domain/website information
        domain = request.raw_data.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]

        result = await _call_search_or_raise(
            enrichment_web_search(
                WebSearchInput(query=f"site:{domain} OR {domain} company about", num_results=5)
            ),
            provider_name="Search provider",
        )
        search_results.append(f"Domain search results:\n{result}")

        company_result = await _call_search_or_raise(
            enrichment_search_company(CompanySearchInput(query=domain)),
            provider_name="Search provider",
        )
        search_results.append(f"Company info:\n{company_result}")

    return "\n\n".join(search_results)


async def enrich_data(request: EnrichmentRequest) -> EnrichmentResponse:
    """
    Process raw input through the LLM with live web search and return validated output.

    Args:
        request: The enrichment request containing raw data to process.

    Returns:
        EnrichmentResponse: Validated, structured enrichment data.
    """
    try:
        async with asyncio.timeout(ENRICH_TOTAL_TIMEOUT_SECONDS):
            async with asyncio.timeout(SEARCH_CONTEXT_TIMEOUT_SECONDS):
                search_context = await _gather_search_context(request)

            client = instructor.from_anthropic(
                AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            )

            system_prompt = """You are a data enrichment specialist. Your task is to analyze
web search results and extract accurate, structured information.

IMPORTANT:
1. Only use information found in the provided search results
2. Set confidence_score based on how much data you found (0.9+ if comprehensive, 0.5-0.7 if partial)
3. List the actual URLs from search results in the sources field
4. Leave fields as null if the information is not found in the search results
5. Do not hallucinate or make up information not present in the search data
"""

            data_type_instructions = {
                "company": """Extract from the search results:
- Official company name (exact spelling from sources)
- Website domain
- Industry/sector
- Brief description
- Headquarters location
- Founded year
- Employee count range
- LinkedIn URL if found""",
                "address": """Parse and validate from search results:
- Street address
- City
- State/province
- Postal/ZIP code
- Country
- Full formatted address""",
                "person": """Extract from search results:
- Full name
- First and last name
- Professional title
- Current company
- LinkedIn URL if found""",
                "domain": """Extract from search results for the domain_info field:
- The domain name
- Company name that owns this domain
- Industry/sector
- Brief description of the website/company
- Headquarters location
- Founded year
- Employee count range
- Technologies used (if mentioned)
- Social media profiles (LinkedIn, Twitter, etc.)""",
            }

            user_message = f"""Please enrich the following {request.data_type} data using ONLY the search results provided.

Raw input: {request.raw_data}

=== LIVE SEARCH RESULTS ===
{search_context}
=== END SEARCH RESULTS ===

{data_type_instructions.get(request.data_type, "")}

Extract and structure the data from the search results above."""

            return await _call_llm_with_fallback(client, user_message, system_prompt)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError as exc:
        raise EnrichmentTimeoutError(
            "Enrichment timed out while calling upstream providers. Please retry."
        ) from exc
