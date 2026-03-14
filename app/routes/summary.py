"""
Summary API endpoints.

This module provides the summarization endpoints (regular and streaming).
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.documents import Document

from ..decorators import handle_api_errors, require_session
from ..factories import init_llm_and_embeddings
from ..logging_config import get_logger
from ..managers import get_contents_from_session_with_validation, validate_llm_deployment_safe
from ..models import SummaryRequest, SummaryResponse
from ..summarization import SUMMARY_LEVELS, MapReduceSummarization, RefinementSummarization

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["summary"])


@router.post("/summary", response_model=SummaryResponse)
@require_session(strict=False)
@handle_api_errors(SummaryResponse)
async def summarize_news_content(request: SummaryRequest):
    """Perform summarization on news content from session."""
    try:
        session_id = request.session_id

        # Use safe validation for consistent error handling
        deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
        if validation_error:
            return SummaryResponse(success=False, message=validation_error, summary=None)

        valid_levels = list(SUMMARY_LEVELS.keys())
        if request.summary_level not in valid_levels:
            return SummaryResponse(
                success=False,
                message=f"Invalid summary level '{request.summary_level}'. Valid options: {', '.join(valid_levels)}",
                summary=None,
            )

        if not session_id:
            return SummaryResponse(
                success=False,
                message="Session is required. Please search for news and get content first, then try summarization again.",
                summary=None,
            )

        if not request.urls:
            return SummaryResponse(
                success=False,
                message="No URLs provided for summarization",
                summary=None,
            )

        contents, missing_urls, error_msg = get_contents_from_session_with_validation(
            session_id, request.urls, "summarization"
        )
        if error_msg:
            return SummaryResponse(success=False, message=error_msg, summary=None)

        try:
            llm, emb = init_llm_and_embeddings(deployment, request.llm_model)
            docs = [
                Document(page_content=content["text"], metadata={"url": content["url"]})
                for content in contents
                if content.get("text")
            ]
            num_clusters = request.num_clusters if request.cluster_docs else 0

            if request.summary_method == "map-reduce":
                summarizer = MapReduceSummarization(llm, emb)
            else:
                summarizer = RefinementSummarization(llm, emb)

            summary = await summarizer.summarize(
                docs=docs,
                lang=request.lang,
                summary_level=request.summary_level,
                num_cluster=num_clusters,
            )
            return SummaryResponse(
                success=True,
                message=f"Summary generated successfully, processed {len(contents)} articles",
                summary=summary,
            )

        except Exception as summarization_error:
            logger.error(f"Summarization execution failed: {summarization_error}")
            return SummaryResponse(
                success=False,
                message=f"Summary generation failed: {summarization_error}",
                summary=None,
            )

    except Exception as e:
        logger.error(f"Summary error: {e}")
        return SummaryResponse(
            success=False, message=f"System error: {e}", summary=None
        )


@router.post("/summary/stream")
@require_session(strict=False)
async def summarize_news_content_stream(request: SummaryRequest):
    """Perform summarization on news content with streaming progress updates."""

    def format_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\n" f"data: {json.dumps(data)}\n\n"

    async def generate_stream():
        try:
            session_id = request.session_id

            # Send initial status
            yield format_event("status", {"message": "Initializing summarization..."})

            deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
            if validation_error:
                yield format_event("error", {"message": validation_error})
                return

            valid_levels = list(SUMMARY_LEVELS.keys())
            if request.summary_level not in valid_levels:
                yield format_event("error", {
                    "message": f"Invalid summary level '{request.summary_level}'. Valid options: {', '.join(valid_levels)}"
                })
                return

            if not session_id:
                yield format_event("error", {
                    "message": "Session is required. Please search for news and get content first."
                })
                return

            if not request.urls:
                yield format_event("error", {"message": "No URLs provided for summarization"})
                return

            # Send progress update
            yield format_event("status", {"message": "Loading content from session..."})

            contents, missing_urls, error_msg = get_contents_from_session_with_validation(
                session_id, request.urls, "summarization"
            )
            if error_msg:
                yield format_event("error", {"message": error_msg})
                return

            # Send progress update
            yield format_event("status", {
                "message": f"Preparing {len(contents)} documents for summarization..."
            })

            llm, emb = init_llm_and_embeddings(deployment, request.llm_model)
            docs = [
                Document(page_content=content["text"], metadata={"url": content["url"]})
                for content in contents
                if content.get("text")
            ]
            num_clusters = request.num_clusters if request.cluster_docs else 0

            # Send progress update
            method_name = "Map-Reduce" if request.summary_method == "map-reduce" else "Refinement"
            yield format_event("status", {
                "message": f"Running {method_name} summarization on {len(docs)} documents..."
            })

            if request.summary_method == "map-reduce":
                summarizer = MapReduceSummarization(llm, emb)
            else:
                summarizer = RefinementSummarization(llm, emb)

            summary = await summarizer.summarize(
                docs=docs,
                lang=request.lang,
                summary_level=request.summary_level,
                num_cluster=num_clusters,
            )

            # Send final result
            yield format_event("complete", {
                "success": True,
                "message": f"Summary generated successfully, processed {len(contents)} articles",
                "summary": summary
            })

        except Exception as e:
            logger.error(f"Streaming summary error: {e}")
            yield format_event("error", {"message": f"System error: {str(e)}"})

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )