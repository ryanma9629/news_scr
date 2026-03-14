"""
Factory functions for creating service instances.

This module provides factory functions for LLM, embeddings, search engines,
and document storage instances.
"""

import os
import socket
from typing import Tuple, Union

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_deepseek import ChatDeepSeek
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from pydantic import SecretStr

from .config import (
    LANGUAGE_DISPLAY_MAP,
    SEARCH_SUFFIX_MAP,
    SUPPORTED_LLM_DEPLOYMENTS,
    SUPPORTED_MODELS,
)
from .doc_store import MongoStore, RedisStore
from .logging_config import get_logger
from .websearch import GoogleSerperNews, TavilySearch

__all__ = [
    "init_llm_and_embeddings",
    "get_search_keywords",
    "get_search_engine",
    "get_doc_store",
    "StorageFactory",
    "create_doc_store_dependency",
    "check_port_availability",
    "get_fallback_port",
]

logger = get_logger(__name__)


# =============================================================================
# LLM AND EMBEDDINGS FACTORY
# =============================================================================


def init_llm_and_embeddings(deployment: str = "gpt-4o", model: str = "gpt-4o"):
    """Initialize LLM and embeddings with common configuration.

    Args:
        deployment: The deployment name for the LLM
        model: The model name to use

    Returns:
        Tuple of (LLM instance, embeddings instance)

    Raises:
        ValueError: If deployment or model is not supported
    """
    if deployment not in SUPPORTED_LLM_DEPLOYMENTS:
        raise ValueError(f"Unsupported LLM deployment: {deployment}")

    # Validate model for the given deployment
    valid_models = SUPPORTED_MODELS.get(deployment, [])
    if model not in valid_models:
        raise ValueError(
            f"Unsupported model '{model}' for deployment '{deployment}'. "
            f"Valid models: {valid_models}"
        )

    if deployment.startswith("deepseek"):
        llm = ChatDeepSeek(model=deployment, temperature=0)
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    elif deployment.startswith("qwen"):
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY environment variable is required for Qwen models"
            )
        llm = ChatTongyi(model=deployment, api_key=SecretStr(api_key))
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    else:
        azure_deployment = SUPPORTED_LLM_DEPLOYMENTS[deployment]
        llm = AzureChatOpenAI(
            azure_deployment=azure_deployment, model=model, temperature=0
        )
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")

    return llm, emb


# =============================================================================
# SEARCH ENGINE FACTORY
# =============================================================================


def get_search_keywords(company_name: str, search_suffix: str, lang: str) -> str:
    """Generate search keywords based on company name, suffix, and language."""
    base_keywords = company_name
    if search_suffix != "everything":
        suffix_mapping = SEARCH_SUFFIX_MAP.get(search_suffix, {})
        suffix_text = suffix_mapping.get(lang, suffix_mapping.get("en-US", ""))
        if suffix_text:
            base_keywords += f" {suffix_text}"
    return base_keywords


def get_search_engine(engine_name: str, lang: str):
    """Get search engine instance based on engine name and language.

    Args:
        engine_name: Name of the search engine ('Google' or 'Tavily')
        lang: Language code for search results

    Returns:
        Search engine instance, or None if engine not supported
    """
    display_lang = LANGUAGE_DISPLAY_MAP.get(lang, "English")
    engine_name_lower = engine_name.lower()
    if engine_name_lower == "google":
        return GoogleSerperNews(lang=display_lang)
    elif engine_name_lower == "tavily":
        return TavilySearch(lang=display_lang)
    return None


# =============================================================================
# DOCUMENT STORAGE FACTORY
# =============================================================================


def get_doc_store(storage_type: str, company_name: str, lang: str) -> Union[MongoStore, RedisStore]:
    """Get appropriate document store based on storage type.

    Args:
        storage_type: Storage type ('redis' or 'mongo')
        company_name: Company name for storage namespace
        lang: Language code for storage namespace

    Returns:
        Document store instance (MongoStore or RedisStore)

    Raises:
        ValueError: If storage_type is not supported
    """
    storage_type = storage_type.lower()
    if storage_type == "redis":
        return RedisStore(company_name=company_name, lang=lang)
    elif storage_type == "mongo":
        return MongoStore(company_name=company_name, lang=lang)
    else:
        raise ValueError(f"Unsupported storage type: {storage_type}. Supported types: 'redis', 'mongo'")


class StorageFactory:
    """Factory class for creating document storage instances with caching."""

    _instances = {}

    @classmethod
    def get_doc_store(
        cls, storage_type: str, company_name: str, lang: str
    ) -> Union[MongoStore, RedisStore]:
        """Get or create a document store instance.

        Uses caching to avoid creating multiple instances for the same parameters.

        Args:
            storage_type: Storage type ('redis' or 'mongo')
            company_name: Company name for storage namespace
            lang: Language code for storage namespace

        Returns:
            Document store instance (MongoStore or RedisStore)
        """
        cache_key = (storage_type.lower(), company_name, lang)
        if cache_key not in cls._instances:
            cls._instances[cache_key] = get_doc_store(
                storage_type, company_name, lang
            )
        return cls._instances[cache_key]

    @classmethod
    def clear_cache(cls):
        """Clear the instance cache."""
        cls._instances.clear()


def create_doc_store_dependency(
    storage_type: str, company_name: str, lang: str
) -> Union[MongoStore, RedisStore]:
    """Dependency function for document store injection.

    This function is designed to be used with FastAPI's dependency injection
    system. It wraps the StorageFactory for easy testing and configuration.

    Args:
        storage_type: Storage type ('redis' or 'mongo')
        company_name: Company name for storage namespace
        lang: Language code for storage namespace

    Returns:
        Document store instance (MongoStore or RedisStore)
    """
    return StorageFactory.get_doc_store(storage_type, company_name, lang)


# =============================================================================
# PORT UTILITIES
# =============================================================================


def check_port_availability(port: int) -> bool:
    """Check if a port is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def get_fallback_port(preferred_port: int) -> int:
    """Get a fallback port if the preferred one is not available."""
    for port in range(preferred_port, preferred_port + 100):
        if check_port_availability(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]