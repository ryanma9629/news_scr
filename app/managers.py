"""
Manager classes for centralized business logic.

This module provides manager classes for content loading, validation,
storage operations, and response creation.
"""

from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException

from .config import SUPPORTED_LLM_DEPLOYMENTS
from .logging_config import get_logger
from .models import CrawlerResultResponse, TaggingResultResponse
from .session import get_session_data

__all__ = [
    "ContentManager",
    "ValidationManager",
    "StorageManager",
    "ResponseManager",
    # Convenience functions (wrappers around manager methods)
    "validate_llm_deployment",
    "validate_llm_deployment_safe",
    "validate_session_and_urls",
    "get_contents_from_session_with_validation",
    "load_from_storage_with_fallback",
    "handle_storage_operation",
]

logger = get_logger(__name__)


# =============================================================================
# CONTENT MANAGER
# =============================================================================


class ContentManager:
    """Unified content loading and validation manager."""

    @staticmethod
    def get_from_session_with_validation(
        session_id: str, urls: List[str], operation_name: str
    ) -> Tuple[List[Dict[str, str]], List[str], Optional[str]]:
        """Get contents from session with comprehensive validation.

        Args:
            session_id: Session identifier
            urls: List of URLs to retrieve
            operation_name: Name of the operation for error messages

        Returns:
            Tuple of (contents, missing_urls, error_message).
            If successful, error_message is None.
        """
        session_data = get_session_data(session_id)
        session_contents = session_data.get("web_contents", {})
        contents = []
        missing_urls = []

        for url in urls:
            if url in session_contents:
                contents.append({"url": url, "text": session_contents[url]})
            else:
                missing_urls.append(url)

        if not contents:
            return (
                [],
                missing_urls,
                f"Content not found for {operation_name}. Please get content first.",
            )
        return contents, missing_urls, None

    @staticmethod
    def load_with_fallback(
        doc_store, urls: List[str], session_id: str, days: int = 0
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        """Load contents from storage with session fallback.

        Args:
            doc_store: Document storage instance
            urls: List of URLs to load
            session_id: Session identifier
            days: Number of days to look back for cached content

        Returns:
            Tuple of (contents, missing_urls)
        """
        from .doc_store import RedisStore

        session_data = get_session_data(session_id)
        session_contents = session_data.get("web_contents", {})
        contents = []
        missing_urls = []

        for url in urls:
            if url in session_contents:
                contents.append({"url": url, "text": session_contents[url]})
            else:
                missing_urls.append(url)

        if missing_urls:
            try:
                fallback_contents = doc_store.load_contents(missing_urls, days=days)
                contents.extend(fallback_contents)
                fallback_urls = {content["url"] for content in fallback_contents}
                missing_urls = [url for url in missing_urls if url not in fallback_urls]
            except Exception as e:
                storage_type = "Redis" if isinstance(doc_store, RedisStore) else "MongoDB"
                logger.error(f"Error loading from {storage_type}: {e}")

        return contents, missing_urls


# =============================================================================
# VALIDATION MANAGER
# =============================================================================


class ValidationManager:
    """Unified validation manager for common request validations."""

    @staticmethod
    def validate_session_and_urls(
        session_id: Optional[str], urls: List[str], operation_name: str
    ):
        """Centralized validation for session ID and URLs."""
        if not session_id:
            return (
                False,
                f"Session is required. Please search for news and get content first, then try {operation_name} again.",
            )
        if not urls:
            return False, f"No URLs provided for {operation_name}"
        return True, ""

    @staticmethod
    def validate_llm_deployment(llm_model: str) -> str:
        """Validate and return the correct deployment name for the given LLM model."""
        if llm_model not in SUPPORTED_LLM_DEPLOYMENTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported LLM model: {llm_model}. Supported models: {list(SUPPORTED_LLM_DEPLOYMENTS.keys())}",
            )
        return SUPPORTED_LLM_DEPLOYMENTS[llm_model]

    @staticmethod
    def validate_llm_deployment_safe(llm_model: str) -> Tuple[str, Optional[str]]:
        """Validate LLM deployment and return (deployment, error_message) tuple.

        This is a non-throwing version that returns error as string instead of
        raising HTTPException, for consistent error handling across endpoints.

        Args:
            llm_model: The LLM model name to validate

        Returns:
            Tuple of (deployment_name, error_message). If valid, error_message is None.
        """
        if llm_model not in SUPPORTED_LLM_DEPLOYMENTS:
            return "", f"Unsupported LLM model: {llm_model}. Supported models: {list(SUPPORTED_LLM_DEPLOYMENTS.keys())}"
        return SUPPORTED_LLM_DEPLOYMENTS[llm_model], None


# =============================================================================
# STORAGE MANAGER
# =============================================================================


class StorageManager:
    """Unified storage operations manager."""

    @staticmethod
    def handle_operation(operation_func, operation_name: str, *args, **kwargs):
        """Generic handler for storage operations with error handling."""
        try:
            return operation_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error {operation_name}: {e}")
            return None


# =============================================================================
# RESPONSE MANAGER
# =============================================================================


class ResponseManager:
    """Unified response creation manager."""

    @staticmethod
    def create_error_response(
        response_class, urls: List[str], error_message: str, **kwargs
    ):
        """Create standardized error responses."""
        if (
            hasattr(response_class, "model_fields")
            and "results" in response_class.model_fields
        ):
            # For responses with results (like TaggingResponse, CrawlerResponse)
            failed_results = []
            for url in urls:
                if response_class.__name__ == "TaggingResponse":
                    failed_results.append(
                        TaggingResultResponse(
                            url=url,
                            success=False,
                            error=error_message,
                            crime_type=None,
                            probability=None,
                            description=None,
                        )
                    )
                elif response_class.__name__ == "CrawlerResponse":
                    failed_results.append(
                        CrawlerResultResponse(
                            url=url, success=False, error=error_message, content=None
                        )
                    )
            return response_class(
                success=False,
                results=failed_results,
                total_results=len(failed_results),
                message=error_message,
                **kwargs,
            )
        else:
            # For simple responses (like SummaryResponse, QAResponse)
            return response_class(success=False, message=error_message, **kwargs)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def validate_llm_deployment(llm_model: str) -> str:
    """Validate and return the correct deployment name for the given LLM model."""
    return ValidationManager.validate_llm_deployment(llm_model)


def validate_llm_deployment_safe(llm_model: str) -> Tuple[str, Optional[str]]:
    """Validate LLM deployment and return (deployment, error_message) tuple.

    This is a non-throwing version for consistent error handling across endpoints.

    Args:
        llm_model: The LLM model name to validate

    Returns:
        Tuple of (deployment_name, error_message). If valid, error_message is None.
    """
    return ValidationManager.validate_llm_deployment_safe(llm_model)


def validate_session_and_urls(
    session_id: Optional[str], urls: List[str], operation_name: str
) -> Tuple[bool, str]:
    """Centralized validation for session ID and URLs.

    Args:
        session_id: Session identifier
        urls: List of URLs to validate
        operation_name: Name of the operation for error messages

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty string.
    """
    return ValidationManager.validate_session_and_urls(session_id, urls, operation_name)


def get_contents_from_session_with_validation(
    session_id: str, urls: List[str], operation_name: str
) -> Tuple[List[Dict[str, str]], List[str], Optional[str]]:
    """Get contents from session with comprehensive validation.

    Args:
        session_id: Session identifier
        urls: List of URLs to retrieve
        operation_name: Name of the operation for error messages

    Returns:
        Tuple of (contents, missing_urls, error_message).
    """
    return ContentManager.get_from_session_with_validation(
        session_id, urls, operation_name
    )


def load_from_storage_with_fallback(
    doc_store, urls: List[str], session_id: str, days: int = 0
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Load contents from storage with session fallback.

    Args:
        doc_store: Document storage instance
        urls: List of URLs to load
        session_id: Session identifier
        days: Number of days to look back for cached content

    Returns:
        Tuple of (contents, missing_urls)
    """
    return ContentManager.load_with_fallback(doc_store, urls, session_id, days)


def handle_storage_operation(operation_func, operation_name: str, *args, **kwargs):
    """Generic handler for storage operations with error handling.

    Args:
        operation_func: The storage operation function to call
        operation_name: Description of the operation for logging
        *args: Positional arguments to pass to the operation
        **kwargs: Keyword arguments to pass to the operation

    Returns:
        Result of the operation, or None if an error occurred
    """
    return StorageManager.handle_operation(
        operation_func, operation_name, *args, **kwargs
    )