"""Async LLM orchestration via Instructor with live web search."""

import os

import instructor
from anthropic import AsyncAnthropic

from .schemas import EnrichmentRequest, EnrichmentResponse
from .tools import CompanySearchInput, WebSearchInput, enrichment_search_company, enrichment_web_search


async def _gather_search_context(request: EnrichmentRequest) -> str:
    """Fetch live data from web search based on data type."""
    search_results = []

    if request.data_type == "company":
        result = await enrichment_search_company(CompanySearchInput(query=request.raw_data))
        search_results.append(f"Company search results:\n{result}")

        linkedin_result = await enrichment_web_search(
            WebSearchInput(query=f"{request.raw_data} linkedin company", num_results=3)
        )
        search_results.append(f"LinkedIn search:\n{linkedin_result}")

    elif request.data_type == "person":
        result = await enrichment_web_search(
            WebSearchInput(query=f"{request.raw_data} professional profile", num_results=5)
        )
        search_results.append(f"Person search results:\n{result}")

        linkedin_result = await enrichment_web_search(
            WebSearchInput(query=f"{request.raw_data} linkedin", num_results=3)
        )
        search_results.append(f"LinkedIn search:\n{linkedin_result}")

    elif request.data_type == "address":
        result = await enrichment_web_search(
            WebSearchInput(query=f"{request.raw_data} address location", num_results=5)
        )
        search_results.append(f"Address search results:\n{result}")

    elif request.data_type == "domain":
        # Search for domain/website information
        domain = request.raw_data.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]

        result = await enrichment_web_search(
            WebSearchInput(query=f"site:{domain} OR {domain} company about", num_results=5)
        )
        search_results.append(f"Domain search results:\n{result}")

        company_result = await enrichment_search_company(CompanySearchInput(query=domain))
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

    response = await client.chat.completions.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=2000,
        max_retries=3,
        messages=[
            {"role": "user", "content": user_message},
        ],
        system=system_prompt,
        response_model=EnrichmentResponse,
    )

    return response
