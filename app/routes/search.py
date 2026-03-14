"""
Search API endpoints.

This module provides the news search endpoint.
"""

from fastapi import APIRouter, HTTPException, Request

from ..decorators import handle_api_errors, require_session
from ..factories import get_search_engine, get_search_keywords
from ..logging_config import get_logger
from ..managers import validate_llm_deployment_safe
from ..models import SearchRequest, SearchResponse, SearchResultResponse
from ..session import (
    create_json_response_with_cookies,
    generate_session_id,
    update_session_data,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
@require_session(strict=False)
@handle_api_errors(SearchResponse)
async def search_news(http_request: Request, request: SearchRequest):
    """Search for news articles based on company name and parameters."""
    try:
        client_ip = http_request.client.host if http_request.client else "unknown"
        user_agent = http_request.headers.get("user-agent", "")
        session_id = request.session_id or generate_session_id(client_ip, user_agent)

        # Use safe validation for consistent error handling
        deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
        if validation_error:
            return SearchResponse(
                success=False,
                results=[],
                total_results=0,
                message=validation_error,
                session_id=session_id,
            )

        keywords = get_search_keywords(
            request.company_name, request.search_suffix, request.lang
        )
        search_engine = get_search_engine(request.search_engine, request.lang)

        if not search_engine:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported search engine: {request.search_engine}",
            )

        # Perform search with better error handling
        try:
            results = await search_engine.asearch(keywords, request.num_results)
        except Exception as search_error:
            # This is definitely an API/network error
            logger.error(f"Search engine error: {search_error}")
            return SearchResponse(
                success=False,
                results=[],
                total_results=0,
                message="Search failed due to network connection or API configuration issues. Please try again later or contact support.",
                session_id=session_id,
            )

        # Handle different result scenarios
        if results is None or len(results) == 0:
            # Either no results found or API returned None/empty list
            # Since we can't distinguish, assume it's "no results found" for better UX
            search_topic_map = {
                "negative": "negative news",
                "crime": "criminal suspect news",
                "everything": "news articles",
            }
            search_topic = search_topic_map.get(request.search_suffix, "news articles")

            return SearchResponse(
                success=True,
                results=[],
                total_results=0,
                message=f"No {search_topic} found for '{request.company_name}'. Try using different search terms, changing the search topic, or checking the spelling.",
                session_id=session_id,
            )

        search_results = [
            SearchResultResponse(url=result["url"], title=result["title"])
            for result in results
        ]

        # Store search results and user context in session
        update_session_data(
            session_id,
            "search_results",
            [{"url": result["url"], "title": result["title"]} for result in results],
        )
        update_session_data(
            session_id,
            "user_context",
            {
                "company_name": request.company_name,
                "lang": request.lang,
                "search_params": {
                    "search_suffix": request.search_suffix,
                    "search_engine": request.search_engine,
                    "num_results": request.num_results,
                    "llm_model": request.llm_model,
                },
            },
        )

        response_data = {
            "success": True,
            "results": [
                {"url": result.url, "title": result.title} for result in search_results
            ],
            "total_results": len(search_results),
            "message": f"Successfully found {len(search_results)} news articles",
            "session_id": session_id,
        }
        return create_json_response_with_cookies(response_data, session_id)

    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return SearchResponse(
            success=False,
            results=[],
            total_results=0,
            message=f"Search error: {str(e)}",
            session_id=request.session_id,
        )