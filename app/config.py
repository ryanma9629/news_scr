"""
Centralized configuration constants for the application.

This module provides all configuration constants used across the application,
ensuring DRY (Don't Repeat Yourself) principles and easy configuration management.
"""

from typing import Literal

__all__ = [
    # Chunking configuration
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    # Session configuration
    "DEFAULT_SESSION_TIMEOUT_HOURS",
    "DEFAULT_STORAGE_DAYS",
    # LLM configuration
    "SUPPORTED_LLM_DEPLOYMENTS",
    "SUPPORTED_MODELS",
    "DEFAULT_LLM_DEPLOYMENT",
    # Language and search configuration
    "LANGUAGE_DISPLAY_MAP",
    "SEARCH_SUFFIX_MAP",
    # QA configuration
    "DEFAULT_RETRIEVAL_COUNT",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_DOC_SEPARATOR",
    "NO_CONTEXT_MESSAGE",
    "GENERATION_ERROR_MESSAGE",
    "TECHNICAL_ERROR_MESSAGE",
    # Tagging configuration
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_K",
    "MIN_CONTENT_LENGTH",
    "DEFAULT_CRIME_TYPE",
    "DEFAULT_PROBABILITY",
    "DEFAULT_DESCRIPTION",
    # Graph RAG configuration
    "MIN_WORD_LENGTH_FOR_SEARCH",
    "MAX_ENTITIES_IN_CONTEXT",
    "MAX_ENTITIES_FOR_ANSWER",
    "MAX_RELATIONSHIPS_DISPLAY",
    "MAX_DOC_CONTEXT_LENGTH",
    "MAX_DOCS_FOR_CONTEXT",
    "MAX_DESCRIPTION_LENGTH",
    # Vector store configuration
    "DEFAULT_CHROMA_PERSIST_DIR",
    # Crawler configuration
    "TAVILY_BATCH_SIZE",
    # Type aliases
    "CrawlerType",
]

# =============================================================================
# CHUNKING CONFIGURATION
# =============================================================================

DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 100

# =============================================================================
# SESSION CONFIGURATION
# =============================================================================

DEFAULT_SESSION_TIMEOUT_HOURS = 2
DEFAULT_STORAGE_DAYS = 90

# =============================================================================
# LLM CONFIGURATION
# =============================================================================

SUPPORTED_LLM_DEPLOYMENTS = {
    "gpt-4.1": "gpt-4.1",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "deepseek-chat": "deepseek-chat",
    "qwen-max": "qwen-max",
    "qwen-plus": "qwen-plus",
    "qwen-turbo": "qwen-turbo",
}

SUPPORTED_MODELS = {
    "gpt-4.1": ["gpt-4.1"],
    "gpt-4o": ["gpt-4o"],
    "gpt-4o-mini": ["gpt-4o-mini"],
    "deepseek-chat": ["deepseek-chat"],
    "qwen-max": ["qwen-max"],
    "qwen-plus": ["qwen-plus"],
    "qwen-turbo": ["qwen-turbo"],
}

DEFAULT_LLM_DEPLOYMENT = "gpt-4o"

# =============================================================================
# LANGUAGE AND SEARCH CONFIGURATION
# =============================================================================

LANGUAGE_DISPLAY_MAP = {
    "zh-CN": "Simplified Chinese",
    "zh-HK": "Traditional Chinese(HK)",
    "zh-TW": "Traditional Chinese(TW)",
    "en-US": "English",
    "ja-JP": "Japanese",
}

SEARCH_SUFFIX_MAP = {
    "negative": {
        "zh-CN": "负面新闻",
        "zh-HK": "負面新聞",
        "zh-TW": "負面新聞",
        "en-US": "negative news",
        "ja-JP": "ネガティブニュース",
    },
    "crime": {
        "zh-CN": "犯罪嫌疑",
        "zh-HK": "犯罪嫌疑",
        "zh-TW": "犯罪嫌疑",
        "en-US": "criminal suspect",
        "ja-JP": "犯罪容疑",
    },
    "everything": {"zh-CN": "", "zh-HK": "", "zh-TW": "", "en-US": "", "ja-JP": ""},
}

# =============================================================================
# QA CONFIGURATION
# =============================================================================

DEFAULT_RETRIEVAL_COUNT = 3
DEFAULT_TEMPERATURE = 0.0
DEFAULT_DOC_SEPARATOR = "\n\n"

# Error messages
NO_CONTEXT_MESSAGE = "I don't have enough information to answer this question."
GENERATION_ERROR_MESSAGE = "I'm unable to generate an answer at this time."
TECHNICAL_ERROR_MESSAGE = (
    "I'm unable to process your question due to a technical issue. Please try again."
)

# =============================================================================
# TAGGING CONFIGURATION
# =============================================================================

DEFAULT_MAX_CONCURRENCY = 3
DEFAULT_K = 3
MIN_CONTENT_LENGTH = 10
DEFAULT_CRIME_TYPE = "Not suspected"
DEFAULT_PROBABILITY = "low"
DEFAULT_DESCRIPTION = None

# =============================================================================
# GRAPH RAG CONFIGURATION
# =============================================================================

# Entity extraction thresholds
MIN_WORD_LENGTH_FOR_SEARCH = 3
MAX_ENTITIES_IN_CONTEXT = 10
MAX_ENTITIES_FOR_ANSWER = 5  # Limit entities used for answer generation
MAX_RELATIONSHIPS_DISPLAY = 10
MAX_DOC_CONTEXT_LENGTH = 500
MAX_DOCS_FOR_CONTEXT = 3

# Description generation
MAX_DESCRIPTION_LENGTH = 200

# =============================================================================
# VECTOR STORE CONFIGURATION
# =============================================================================

DEFAULT_CHROMA_PERSIST_DIR = "./chroma_db"

# =============================================================================
# CRAWLER CONFIGURATION
# =============================================================================

# Tavily batch size
TAVILY_BATCH_SIZE = 20

# =============================================================================
# TYPE ALIASES
# =============================================================================

CrawlerType = Literal["cheerio", "playwright:chrome", "playwright:firefox", "playwright:adaptive", "tavily"]