"""
Crawler API endpoints.

This module provides the content crawling endpoint.
"""

from fastapi import APIRouter

from ..crawler import ApifyCrawler, TavilyCrawler
from ..decorators import handle_api_errors, require_session
from ..factories import get_doc_store
from ..logging_config import get_logger
from ..managers import handle_storage_operation, validate_session_and_urls
from ..models import CrawlerRequest, CrawlerResponse, CrawlerResultResponse
from ..session import update_session_data

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["crawler"])


@router.post("/crawler", response_model=CrawlerResponse)
@require_session(strict=False)
@handle_api_errors(CrawlerResponse)
async def crawl_news_content(request: CrawlerRequest):
    """Crawl content from news URLs using ApifyCrawler with storage and session support."""
    try:
        session_id = request.session_id
        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "crawling"
        )
        if not is_valid:
            return CrawlerResponse(
                success=False,
                results=[],
                total_results=0,
                message=validation_error or "Validation failed",
            )

        try:
            doc_store = get_doc_store(request.storage_type, request.company_name, request.lang)
        except ValueError as e:
            return CrawlerResponse(
                success=False,
                results=[],
                total_results=0,
                message=str(e),
            )

        results = []
        contents_from_db = []

        # Load from storage if enabled
        if request.contents_load:
            storage_name = "Redis" if request.storage_type.lower() == "redis" else "MongoDB"
            contents_from_db = (
                handle_storage_operation(
                    doc_store.load_contents,
                    f"loaded contents from {storage_name}",
                    request.urls,
                    days=request.contents_load_days,
                )
                or []
            )

            stored_urls = {content["url"] for content in contents_from_db}
            for content in contents_from_db:
                results.append(
                    CrawlerResultResponse(
                        url=content["url"],
                        success=True,
                        content=content["text"],
                        error=None,
                    )
                )
            urls_to_crawl = [url for url in request.urls if url not in stored_urls]
        else:
            urls_to_crawl = request.urls

        # Crawl remaining URLs
        crawled_contents = []
        if urls_to_crawl:
            try:
                # Select crawler based on type
                if request.crawler_type == "tavily":
                    crawler = TavilyCrawler()
                    documents = await crawler.get(urls_to_crawl)
                else:
                    crawler = ApifyCrawler()
                    documents = await crawler.get(
                        urls_to_crawl, crawler_type=request.crawler_type
                    )

                url_to_doc = {
                    doc.metadata.get("source", ""): doc
                    for doc in documents
                    if doc.metadata.get("source")
                }

                for url in urls_to_crawl:
                    if url in url_to_doc and url_to_doc[url].page_content.strip():
                        content = url_to_doc[url].page_content
                        results.append(
                            CrawlerResultResponse(
                                url=url, success=True, content=content, error=None
                            )
                        )
                        crawled_contents.append({"url": url, "text": content})
                    else:
                        error_msg = (
                            "Content is empty"
                            if url in url_to_doc
                            else "Content not found for this URL"
                        )
                        results.append(
                            CrawlerResultResponse(
                                url=url, success=False, content=None, error=error_msg
                            )
                        )
            except Exception as crawler_error:
                logger.error(f"Crawler execution failed: {crawler_error}")
                for url in urls_to_crawl:
                    results.append(
                        CrawlerResultResponse(
                            url=url,
                            success=False,
                            content=None,
                            error=f"Crawling failed: {crawler_error}",
                        )
                    )

        # Save to storage and session
        if request.contents_save and crawled_contents:
            storage_name = "Redis" if request.storage_type.lower() == "redis" else "MongoDB"
            handle_storage_operation(
                doc_store.save_contents,
                f"saved contents to {storage_name}",
                crawled_contents,
                days=request.contents_save_days,
            )

        all_contents = {content["url"]: content["text"] for content in contents_from_db}
        all_contents.update(
            {r.url: r.content for r in results if r.success and r.content}
        )

        if session_id:
            update_session_data(session_id, "web_contents", all_contents)

        success_count = sum(1 for r in results if r.success)
        return CrawlerResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"Crawling completed: {success_count} successful, {len(results) - success_count} failed",
        )

    except Exception as e:
        logger.error(f"Crawler error: {e}")
        failed_results = [
            CrawlerResultResponse(
                url=url, success=False, error=f"System error: {e}", content=None
            )
            for url in request.urls
        ]
        return CrawlerResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"System error: {e}",
        )