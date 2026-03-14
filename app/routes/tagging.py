"""
Tagging API endpoints.

This module provides the financial crime tagging endpoint.
"""

from fastapi import APIRouter
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from ..decorators import handle_api_errors, require_session
from ..factories import get_doc_store, init_llm_and_embeddings
from ..logging_config import get_logger
from ..managers import handle_storage_operation, load_from_storage_with_fallback, validate_llm_deployment_safe, validate_session_and_urls
from ..models import TaggingRequest, TaggingResponse, TaggingResultResponse
from ..tagging import FCTagging

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["tagging"])


@router.post("/tagging", response_model=TaggingResponse)
@require_session(strict=False)
@handle_api_errors(TaggingResponse)
async def tag_news_content(request: TaggingRequest):
    """Perform FC Tagging on news content with storage and session support."""
    try:
        session_id = request.session_id

        # Use safe validation for consistent error handling
        deployment, validation_error = validate_llm_deployment_safe(request.llm_model)
        if validation_error:
            return TaggingResponse(
                success=False, results=[], total_results=0, message=validation_error
            )

        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "tagging"
        )
        if not is_valid:
            return TaggingResponse(
                success=False,
                results=[],
                total_results=0,
                message=validation_error or "Validation failed",
            )

        try:
            doc_store = get_doc_store(request.storage_type, request.company_name, request.lang)
        except ValueError as e:
            return TaggingResponse(
                success=False,
                results=[],
                total_results=0,
                message=str(e),
            )

        results = []

        # Load existing tags from storage
        tags_from_db = []
        if request.tags_load:
            storage_name = "Redis" if request.storage_type.lower() == "redis" else "MongoDB"
            tags_from_db = (
                handle_storage_operation(
                    doc_store.load_tags,
                    f"loaded tags from {storage_name}",
                    request.urls,
                    method=request.tagging_method,
                    llm_name=request.llm_model,
                    days=request.tags_load_days,
                )
                or []
            )

            stored_urls = {tag["url"] for tag in tags_from_db}
            for tag in tags_from_db:
                results.append(
                    TaggingResultResponse(
                        url=tag["url"],
                        success=True,
                        crime_type=tag.get("crime_type"),
                        probability=tag.get("probability"),
                        description=tag.get("description"),
                        error=None,
                    )
                )
            urls_to_tag = [url for url in request.urls if url not in stored_urls]
        else:
            urls_to_tag = request.urls

        # Tag remaining URLs
        if urls_to_tag:
            contents_to_tag, urls_without_content = load_from_storage_with_fallback(
                doc_store, urls_to_tag, session_id or ""
            )

            for url in urls_without_content:
                results.append(
                    TaggingResultResponse(
                        url=url,
                        success=False,
                        crime_type=None,
                        probability=None,
                        description=None,
                        error="Content not found for this URL, please get content first",
                    )
                )

            if contents_to_tag:
                llm, emb = init_llm_and_embeddings(deployment, request.llm_model)
                fc_tagging = FCTagging(llm, emb)
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
                )

                tagged_results = []
                for content in contents_to_tag:
                    url, text = content["url"], content["text"]
                    try:
                        docs = text_splitter.split_documents(
                            [Document(page_content=text)]
                        )
                        tag_result = (
                            await fc_tagging.tagging_rag(docs)
                            if request.tagging_method == "rag"
                            else await fc_tagging.tagging_combine(docs)
                        )

                        results.append(
                            TaggingResultResponse(
                                url=url,
                                success=True,
                                crime_type=tag_result.get("crime_type"),
                                probability=tag_result.get("probability"),
                                description=tag_result.get("description"),
                                error=None,
                            )
                        )
                        tagged_results.append(
                            {
                                "url": url,
                                "crime_type": tag_result.get("crime_type"),
                                "probability": tag_result.get("probability"),
                                "description": tag_result.get("description"),
                                "method": request.tagging_method,
                            }
                        )
                    except Exception as tag_error:
                        results.append(
                            TaggingResultResponse(
                                url=url,
                                success=False,
                                crime_type=None,
                                probability=None,
                                description=None,
                                error=f"Tagging failed: {tag_error}",
                            )
                        )

                if tagged_results and request.tags_save:
                    storage_name = "Redis" if request.storage_type.lower() == "redis" else "MongoDB"
                    handle_storage_operation(
                        doc_store.save_tags,
                        f"saved tags to {storage_name}",
                        tagged_results,
                        method=request.tagging_method,
                        llm_name=request.llm_model,
                        days=request.tags_save_days,
                    )

        success_count = sum(1 for r in results if r.success)
        return TaggingResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"Tagging completed: {success_count} successful, {len(results) - success_count} failed",
        )

    except Exception as e:
        logger.error(f"Tagging error: {e}")
        failed_results = [
            TaggingResultResponse(
                url=url,
                success=False,
                error=f"System error: {e}",
                crime_type=None,
                probability=None,
                description=None,
            )
            for url in request.urls
        ]
        return TaggingResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"System error: {e}",
        )