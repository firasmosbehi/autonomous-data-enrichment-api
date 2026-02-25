"""Pydantic models for input and enriched output."""

from pydantic import BaseModel, Field, ConfigDict, field_validator


class EnrichmentRequest(BaseModel):
    """Input schema for enrichment requests."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    raw_data: str = Field(
        ...,
        description="Raw, unstructured data to enrich (company name, address, etc.)",
        min_length=1,
        max_length=2000,
    )
    data_type: str = Field(
        default="company",
        description="Type of data to enrich: 'company', 'address', or 'person'",
    )

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, v: str) -> str:
        allowed = {"company", "address", "person", "domain"}
        if v.lower() not in allowed:
            raise ValueError(f"data_type must be one of: {allowed}")
        return v.lower()


class BatchEnrichmentRequest(BaseModel):
    """Input schema for batch enrichment requests."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    items: list[EnrichmentRequest] = Field(
        ...,
        description="List of items to enrich (max 10)",
        min_length=1,
        max_length=10,
    )


class CompanyInfo(BaseModel):
    """Structured company information."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Official company name")
    domain: str | None = Field(None, description="Company website domain")
    industry: str | None = Field(None, description="Primary industry or sector")
    description: str | None = Field(None, description="Brief company description")
    headquarters: str | None = Field(None, description="Headquarters location")
    founded_year: int | None = Field(None, description="Year the company was founded")
    employee_count: str | None = Field(
        None, description="Approximate employee count range"
    )
    linkedin_url: str | None = Field(None, description="LinkedIn company page URL")


class AddressInfo(BaseModel):
    """Structured address information."""

    model_config = ConfigDict(extra="forbid")

    street: str | None = Field(None, description="Street address")
    city: str | None = Field(None, description="City name")
    state: str | None = Field(None, description="State or province")
    postal_code: str | None = Field(None, description="Postal or ZIP code")
    country: str = Field(..., description="Country name")
    formatted_address: str = Field(..., description="Full formatted address")


class PersonInfo(BaseModel):
    """Structured person information."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., description="Full name of the person")
    first_name: str | None = Field(None, description="First name")
    last_name: str | None = Field(None, description="Last name")
    title: str | None = Field(None, description="Professional title or role")
    company: str | None = Field(None, description="Current company")
    linkedin_url: str | None = Field(None, description="LinkedIn profile URL")


class DomainInfo(BaseModel):
    """Structured domain/website information."""

    model_config = ConfigDict(extra="forbid")

    domain: str = Field(..., description="The domain name")
    company_name: str | None = Field(None, description="Company that owns the domain")
    industry: str | None = Field(None, description="Primary industry or sector")
    description: str | None = Field(None, description="Brief description of the website/company")
    headquarters: str | None = Field(None, description="Headquarters location")
    founded_year: int | None = Field(None, description="Year founded")
    employee_count: str | None = Field(None, description="Approximate employee count")
    technologies: list[str] | None = Field(None, description="Technologies used by the website")
    social_profiles: dict[str, str] | None = Field(None, description="Social media URLs")


class EnrichmentResponse(BaseModel):
    """Output schema for enrichment responses."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="Whether enrichment was successful")
    data_type: str = Field(..., description="Type of data that was enriched")
    original_input: str = Field(..., description="The original raw input")
    company: CompanyInfo | None = Field(
        None, description="Enriched company data if data_type is 'company'"
    )
    address: AddressInfo | None = Field(
        None, description="Enriched address data if data_type is 'address'"
    )
    person: PersonInfo | None = Field(
        None, description="Enriched person data if data_type is 'person'"
    )
    domain_info: DomainInfo | None = Field(
        None, description="Enriched domain data if data_type is 'domain'"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score of the enrichment (0-1)"
    )
    sources: list[str] = Field(
        default_factory=list, description="Sources used for enrichment"
    )


class BatchEnrichmentResponse(BaseModel):
    """Output schema for batch enrichment responses."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="Whether batch processing was successful")
    total: int = Field(..., description="Total number of items processed")
    successful: int = Field(..., description="Number of successfully enriched items")
    failed: int = Field(..., description="Number of failed items")
    results: list[EnrichmentResponse] = Field(..., description="List of enrichment results")
