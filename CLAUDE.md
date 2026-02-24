# CLAUDE.md - Autonomous Data Enrichment API

## Project Overview

This is a headless, fully automated data enrichment API designed for marketplace deployment (e.g., RapidAPI). It accepts messy, unstructured data payloads (bare company names, poorly formatted addresses, etc.), uses an LLM with MCP servers to research missing data via the web, validates output through strict Pydantic schemas, and returns perfectly structured JSON. Zero human intervention once deployed.

## Tech Stack

- **Language:** Python 3.12+
- **Package Manager:** Poetry
- **API Framework:** FastAPI (served via Uvicorn)
- **LLM Orchestration & Validation:** `instructor` + Pydantic
- **Tooling Integration:** Official MCP Python SDK (`mcp.server.fastmcp`)
- **HTTP Client:** httpx
- **Config:** python-dotenv

## Project Structure

```
enrichment-api/
├── pyproject.toml          # Poetry config & dependencies
├── Dockerfile
├── .env                    # API keys (never commit)
├── enrichment_api/
│   ├── __init__.py
│   ├── main.py             # FastAPI app, POST endpoint (/api/v1/enrich)
│   ├── schemas.py          # Pydantic models for input & enriched output
│   ├── tools.py            # FastMCP server + @mcp.tool() search/scraping functions
│   └── llm.py              # Async LLM orchestration via Instructor
```

## Architecture & Roles

### Gateway Layer (main.py)
- FastAPI routing and async request handling
- RapidAPI header validation (`X-RapidAPI-Proxy-Secret`)
- Rate-limiting and proper HTTP status codes (400 for bad input, 500 for server errors — critical for marketplace billing)
- Exposes `POST /api/v1/enrich`

### MCP Tooling Layer (tools.py)
- Configures `FastMCP` class from the official Python SDK
- Defines discrete Python tool functions with accurate docstrings so the LLM knows when to trigger them
- Example: `@mcp.tool() def search_company_registry(query: str) -> str`
- Manages API keys for external search providers (Brave Search, SerpAPI, etc.)

### Data Structuring Layer (schemas.py + llm.py)
- Complex `pydantic.BaseModel` schemas for expected output
- Uses `instructor.from_provider()` to wrap the LLM client
- Automatic retry logic (`max_retries=3`) — if the LLM makes a formatting mistake, the system re-prompts before returning to the user

## Development Phases

1. **Scaffolding:** `poetry new enrichment-api && cd enrichment-api`
2. **Dependencies:** `poetry add fastapi uvicorn instructor pydantic mcp httpx python-dotenv`
3. **Schemas (schemas.py):** Define Pydantic models for incoming POST requests and enriched JSON output
4. **Tools (tools.py):** Initialize FastMCP, write search/scraping functions with `@mcp.tool()`
5. **Core Logic (llm.py):** Async function that receives raw input → passes to Instructor-patched LLM → uses MCP tools → returns validated Pydantic object
6. **Endpoint (main.py):** FastAPI app instance + POST endpoint triggering LLM logic
7. **Deploy:** Dockerfile → host (Railway/Render/AWS AppRunner) → RapidAPI listing

## Relevant Skills & References

Before starting any phase, read the corresponding skill files. These contain battle-tested patterns that prevent common pitfalls.

### MCP Builder Skill (Critical — read before Phase 2)
- **Location:** `/mnt/skills/examples/mcp-builder/SKILL.md`
- **What it covers:** End-to-end guide for building MCP servers — tool naming, annotations, Pydantic input models, error handling, transport selection, pagination, and testing.
- **Key sub-references to also read:**
  - `/mnt/skills/examples/mcp-builder/reference/python_mcp_server.md` — Python-specific FastMCP patterns: `@mcp.tool()` decorator usage, Pydantic v2 input validation, `ConfigDict`, `field_validator`, async context managers, lifespan management, structured output types, and a full quality checklist.
  - `/mnt/skills/examples/mcp-builder/reference/mcp_best_practices.md` — Server naming (`{service}_mcp`), tool naming (`{service}_{action}_{resource}`), response format guidelines (JSON + Markdown), pagination metadata (`has_more`, `next_offset`, `total_count`), transport selection (streamable HTTP vs stdio), security (OAuth, API key handling, input sanitization, DNS rebinding), and tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`).
  - `/mnt/skills/examples/mcp-builder/reference/evaluation.md` — How to write eval questions for verifying the MCP server works end-to-end.
- **When to use:** Defining tools in `tools.py`, structuring Pydantic models in `schemas.py`, wiring MCP into `llm.py`.

### Skill Creator (Optional — for iterating on skill quality)
- **Location:** `/mnt/skills/examples/skill-creator/SKILL.md`
- **What it covers:** Creating, modifying, and evaluating skills. Useful if you want to package this project's patterns as a reusable skill later.

### Key Patterns Extracted from Skills

**FastMCP Server Init:**
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("enrichment_mcp")
```

**Tool Registration (with full annotations):**
```python
@mcp.tool(
    name="enrichment_search_company",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def enrichment_search_company(params: CompanySearchInput) -> str:
    '''Search for company information by name or domain.'''
    ...
```

**Pydantic v2 Input Model (with ConfigDict):**
```python
from pydantic import BaseModel, Field, field_validator, ConfigDict

class CompanySearchInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra='forbid',
    )
    query: str = Field(..., description="Company name or domain to search", min_length=1, max_length=200)
```

**Error Handling (consistent across all tools):**
```python
def _handle_api_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 404:
            return "Error: Resource not found. Check the query."
        if e.response.status_code == 429:
            return "Error: Rate limit exceeded. Retry later."
        return f"Error: API returned status {e.response.status_code}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Retry."
    return f"Error: {type(e).__name__}"
```

**Instructor Retry Pattern:**
```python
import instructor
client = instructor.from_provider("anthropic/claude...", max_retries=3)
```

## Key Conventions

- All LLM calls must go through the `instructor`-patched client — never return raw LLM strings
- Every MCP tool must have a precise docstring describing when and why the LLM should invoke it
- Use async throughout (`async def` for endpoints and LLM calls)
- Validate all external API responses before passing to the LLM
- Keep schemas strict: use `pydantic.BaseModel` with explicit types, no `Any` or `dict`
- Environment variables for all secrets (API keys, proxy secrets) via `.env`
- HTTP errors: 400-level for client issues, 500-level for internal failures — never mix these