"""
Pydantic models for request and response validation.

This module contains all Pydantic models used for API request validation
and response serialization.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .config import CrawlerType

__all__ = [
    # Request models
    "SearchRequest",
    "CrawlerRequest",
    "TaggingRequest",
    "SummaryRequest",
    "QARequest",
    # Response models
    "SearchResultResponse",
    "SearchResponse",
    "CrawlerResultResponse",
    "CrawlerResponse",
    "TaggingResultResponse",
    "TaggingResponse",
    "SummaryResponse",
    "QAResponse",
]


# =============================================================================
# REQUEST MODELS
# =============================================================================


class SearchRequest(BaseModel):
    """Request model for news search endpoint."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_default=True,
    )

    company_name: str = Field(..., description="Company name to search for")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code (e.g., 'zh-CN', 'en-US')")
    search_suffix: str = Field(..., description="Search topic suffix")
    search_engine: str = Field(..., description="Search engine ('Google' or 'Tavily')")
    num_results: int = Field(
        ..., ge=1, le=100, description="Number of results to return"
    )
    llm_model: str = Field(..., description="LLM model to use")
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class CrawlerRequest(BaseModel):
    """Request model for content crawling endpoint."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_default=True,
    )

    urls: List[str] = Field(..., description="List of URLs to crawl")
    crawler_type: CrawlerType = Field(
        default="tavily", description="Crawler type"
    )
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code for storage")
    storage_type: str = Field(
        default="mongo", description="Persistent storage type ('redis' or 'mongo')"
    )
    contents_save: bool = Field(default=True, description="Save contents to storage")
    contents_load: bool = Field(
        default=True, description="Load contents from storage if possible"
    )
    contents_save_days: int = Field(
        default=90, description="Only update contents older than this many days"
    )
    contents_load_days: int = Field(
        default=90, description="Only load contents no older than this many days"
    )
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class TaggingRequest(BaseModel):
    """Request model for financial crime tagging endpoint."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_default=True,
    )
    urls: List[str] = Field(..., description="List of URLs to tag")
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code for storage")
    storage_type: str = Field(
        default="mongo", description="Persistent storage type ('redis' or 'mongo')"
    )
    tagging_method: str = Field(
        default="rag", description="Tagging method ('rag' or 'all')"
    )
    llm_model: str = Field(default="gpt-4o", description="LLM model to use")
    tags_save: bool = Field(default=True, description="Save tags to storage")
    tags_load: bool = Field(
        default=True, description="Load tags from storage if possible"
    )
    tags_save_days: int = Field(
        default=90, description="Only update tags older than this many days"
    )
    tags_load_days: int = Field(
        default=90, description="Only load tags no older than this many days"
    )
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class SummaryRequest(BaseModel):
    """Request model for summarization endpoint."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_default=True,
    )
    urls: List[str] = Field(..., description="List of URLs to summarize")
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code for storage")
    summary_method: str = Field(default="map-reduce", description="Summary method")
    llm_model: str = Field(default="gpt-4o", description="LLM model to use")
    summary_level: str = Field(default="moderate", description="Summary detail level")
    cluster_docs: bool = Field(
        default=True, description="Whether to cluster documents before summarization"
    )
    num_clusters: int = Field(
        default=2, description="Number of clusters for document clustering"
    )
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class QARequest(BaseModel):
    """Request model for Q&A endpoint."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_default=True,
    )
    question: str = Field(..., description="Question to ask")
    company_name: str = Field(..., description="Company name for context")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code")
    urls: List[str] = Field(..., description="URLs to use as context")
    llm_model: str = Field(default="gpt-4o-mini", description="LLM model to use")
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )
    thread_id: Optional[str] = Field(
        None, description="Thread ID for conversation continuity"
    )


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class SearchResultResponse(BaseModel):
    """Response model for individual search result."""

    url: str
    title: str


class CrawlerResultResponse(BaseModel):
    """Response model for individual crawler result."""

    url: str
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None


class SearchResponse(BaseModel):
    """Response model for search endpoint."""

    success: bool
    results: List[SearchResultResponse]
    total_results: int
    message: str
    session_id: Optional[str] = None


class CrawlerResponse(BaseModel):
    """Response model for crawler endpoint."""

    success: bool
    results: List[CrawlerResultResponse]
    total_results: int
    message: str


class TaggingResultResponse(BaseModel):
    """Response model for individual tagging result."""

    url: str
    success: bool
    crime_type: Optional[str] = None
    probability: Optional[str] = None
    description: Optional[str] = None
    error: Optional[str] = None


class TaggingResponse(BaseModel):
    """Response model for tagging endpoint."""

    success: bool
    results: List[TaggingResultResponse]
    total_results: int
    message: str


class SummaryResponse(BaseModel):
    """Response model for summary endpoint."""

    success: bool
    summary: Optional[str] = None
    message: str


class QAResponse(BaseModel):
    """Response model for Q&A endpoint."""

    success: bool
    question: Optional[str] = None
    answer: Optional[str] = None
    urls: Optional[List[str]] = None
    message: str