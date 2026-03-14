"""
Document storage implementations using MongoDB.

This module (doc_store.py) provides abstract and concrete implementations for
document storage functionality, including content and tag management with MongoDB backend.
"""

__all__ = [
    "DocStore",
    "MongoStore",
    "RedisStore",
    "MongoConnectionManager",
    "_mongo_manager",
    # Date utilities
    "get_date_threshold",
    "is_date_within_threshold",
    "is_date_older_than_threshold",
    # Validation utilities
    "validate_content_fields",
    "validate_tag_fields",
    "normalize_fields",
    "normalize_url",
]

import json
import logging
import os
import re
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import redis
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .logging_config import get_logger

# Initialize logger using shared configuration
logger = get_logger(__name__)


# =============================================================================
# DATE UTILITY FUNCTIONS
# =============================================================================


def get_date_threshold(days: int) -> Optional[datetime]:
    """
    Calculate the date threshold for filtering data.

    Args:
        days: Number of days to look back. If 0 or negative, returns None.

    Returns:
        Datetime threshold if days > 0, otherwise None.
    """
    if days <= 0:
        return None
    return datetime.combine(datetime.today(), datetime.min.time()) - timedelta(days=days)


def is_date_within_threshold(
    date_to_check: Optional[datetime], threshold: Optional[datetime]
) -> bool:
    """
    Check if a date is within the specified threshold.

    Args:
        date_to_check: The date to check. If None, returns True (considered within).
        threshold: The threshold date. If None, returns True (no filtering).

    Returns:
        True if the date is within the threshold or if no filtering applies.
    """
    if threshold is None:
        return True
    if date_to_check is None:
        return True
    return date_to_check >= threshold


def is_date_older_than_threshold(
    date_to_check: Optional[datetime], threshold: Optional[datetime]
) -> bool:
    """
    Check if a date is older than the specified threshold.

    Args:
        date_to_check: The date to check. If None, returns True (considered old).
        threshold: The threshold date. If None, returns False (no filtering).

    Returns:
        True if the date is older than the threshold.
    """
    if threshold is None:
        return False
    if date_to_check is None:
        return True
    return date_to_check < threshold


# =============================================================================
# VALIDATION UTILITY FUNCTIONS
# =============================================================================


def validate_content_fields(doc: dict) -> bool:
    """
    Validate that a content document has required fields.

    Args:
        doc: Document dictionary to validate

    Returns:
        True if valid, False otherwise
    """
    return "url" in doc and "text" in doc


def validate_tag_fields(tag: dict) -> bool:
    """
    Validate that a tag dictionary has required fields.

    Args:
        tag: Tag dictionary to validate

    Returns:
        True if valid, False otherwise
    """
    required_fields = ["url", "crime_type", "probability"]
    return all(field in tag for field in required_fields)


def normalize_fields(company_name: str, lang: str) -> Tuple[str, str]:
    """
    Normalize company name and language for consistent storage/queries.

    Args:
        company_name: Company name to normalize
        lang: Language code to normalize

    Returns:
        Tuple of (normalized_company, normalized_lang)
    """
    return company_name.lower(), lang.lower()


def normalize_url(url: str) -> str:
    """
    Normalize URL for consistent storage/queries.

    Args:
        url: URL to normalize

    Returns:
        Normalized URL (lowercase)
    """
    return url.lower()


class MongoConnectionManager:
    """Singleton MongoDB connection manager with connection pooling for thread safety."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._client = None
                    instance._uri = None
                    instance._initialized = True
                    cls._instance = instance
        return cls._instance

    def get_client(self, uri: Optional[str] = None) -> MongoClient:
        """Get or create MongoDB client with connection pooling.
        
        Args:
            uri: MongoDB URI string
            
        Returns:
            MongoClient instance with connection pooling
        """
        if uri is None:
            uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
            
        # If client doesn't exist or URI changed, create new client
        if self._client is None or self._uri != uri:
            with self._lock:
                if self._client is None or self._uri != uri:
                    if self._client:
                        self._client.close()
                    
                    # Configure connection pooling for concurrent access
                    self._client = MongoClient(
                        uri,
                        maxPoolSize=20,  # Maximum number of connections in the pool
                        minPoolSize=5,   # Minimum number of connections in the pool
                        maxIdleTimeMS=30000,  # Close connections after 30 seconds of inactivity
                        waitQueueTimeoutMS=5000,  # Wait 5 seconds for a connection from pool
                        serverSelectionTimeoutMS=5000,  # Wait 5 seconds for server selection
                        connectTimeoutMS=10000,  # 10 second connection timeout
                        socketTimeoutMS=20000,   # 20 second socket timeout
                        heartbeatFrequencyMS=10000,  # Heartbeat every 10 seconds
                    )
                    self._uri = uri
                    logger.info(f"MongoDB client created with connection pooling: {uri}")
        
        return self._client
    
    def close(self):
        """Close the MongoDB client connection."""
        with self._lock:
            if self._client:
                self._client.close()
                self._client = None
                self._uri = None
                logger.info("MongoDB connection closed")


# Global MongoDB connection manager instance
_mongo_manager = MongoConnectionManager()


class DocStore(ABC):
    """
    Abstract base class for document storage systems.

    This class provides a common interface for different document storage implementations,
    defining the basic structure and required methods for content and tag management.
    """

    def __init__(self, company_name: str, lang: str) -> None:
        """Initialize the document store.

        Args:
            company_name: Name of the company
            lang: Language code
        """
        self.company_name = company_name
        self.lang = lang

    @abstractmethod
    def load_contents(self, urls: List[str]) -> List[dict]:
        """Load document contents from storage.

        Args:
            urls: List of URLs to load contents for

        Returns:
            List of dictionaries containing document contents
        """
        raise NotImplementedError

    @abstractmethod
    def save_contents(self, contents: List[dict]) -> None:
        """Save document contents to storage.

        Args:
            contents: List of dictionaries containing document contents
        """
        raise NotImplementedError

    @abstractmethod
    def load_tags(self, urls: List[str]) -> List[dict]:
        """Load document tags from storage.

        Args:
            urls: List of URLs to load tags for

        Returns:
            List of dictionaries containing document tags
        """
        raise NotImplementedError

    @abstractmethod
    def save_tags(self, tags: List[dict]) -> None:
        """Save document tags to storage.

        Args:
            tags: List of dictionaries containing document tags
        """
        raise NotImplementedError


class MongoStore(DocStore):
    """
    MongoDB implementation of document storage.

    This class provides document storage functionality using MongoDB,
    with support for content management and tag storage operations.
    Uses connection pooling via MongoConnectionManager for thread safety.
    """

    def __init__(
        self,
        company_name: str,
        lang: str,
        client: Optional[MongoClient] = None,
        db: Optional[str] = None,
    ) -> None:
        """Initialize MongoDB document store.

        Args:
            company_name: Name of the company
            lang: Language code
            client: Optional MongoDB client instance (uses connection manager if None)
            db: Database name to use
        """
        super().__init__(company_name, lang)

        # Use connection manager for pooled connections (recommended)
        # or provided client for custom configurations
        self.client = client or _mongo_manager.get_client()
        self._uses_connection_manager = client is None

        # Use provided db name or get from environment variable
        self.db = db or os.getenv("MONGO_DB", "adverse_news_screening")
        logger.info(
            f"MongoStore initialized for company: {company_name}, lang: {lang}, db: {db}"
        )

    @contextmanager
    def _get_collection(self, collection: str):
        """Context manager for safely accessing MongoDB collections.

        Args:
            collection: Name of the collection to access

        Yields:
            MongoDB collection object

        Raises:
            PyMongoError: If database operation fails
            Exception: If unexpected error occurs
        """
        try:
            col = self.client[self.db][collection]
            yield col
        except PyMongoError as e:
            logger.error(f"Database error accessing collection {collection}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error accessing collection {collection}: {e}")
            raise

    def _ensure_indexes(self, collection) -> None:
        """Ensure required indexes exist for optimal query performance.

        Args:
            collection: MongoDB collection object
        """
        try:
            # Unique compound index for multi-tenant content storage
            # Same URL can exist for different companies/languages
            collection.create_index(
                [("company_name_lower", 1), ("lang", 1), ("url_lower", 1)],
                name="unique_company_lang_url_idx",
                unique=True,
                background=True,
            )
            # Index for date-based queries
            collection.create_index(
                [("modified_date", -1)],
                name="modified_date_idx",
                background=True,
            )
            logger.debug(f"Indexes ensured for collection")
        except Exception as e:
            logger.warning(f"Could not create indexes: {e}")

    def load_contents(
        self,
        urls: List[str],
        collection: Optional[str] = None,
        days: int = 0,
    ) -> List[dict]:
        """Load document contents from MongoDB.

        Args:
            urls: List of URLs to load contents for
            collection: MongoDB collection name to query
            days: Number of days to look back for data (0 for all)

        Returns:
            List of dictionaries containing document contents

        Raises:
            Exception: If database operation fails
        """
        if not urls:
            logger.warning("Empty URLs list provided to load_contents")
            return []

        # Use provided collection name or get from environment variable
        collection_name = collection or os.getenv("MONGO_CONTENTS_COLLECTION", "web_contents")

        try:
            with self._get_collection(collection_name) as col:
                # Ensure indexes exist
                self._ensure_indexes(col)

                # Build query with normalized fields for index usage
                company_lower, lang_lower = normalize_fields(self.company_name, self.lang)
                urls_lower = [normalize_url(url) for url in urls]

                query = {
                    "company_name_lower": company_lower,
                    "lang": lang_lower,
                    "url_lower": {"$in": urls_lower},
                }

                # Add date filter if days is specified
                date_threshold = get_date_threshold(days)
                if date_threshold:
                    query["modified_date"] = {"$gte": date_threshold}

                cursor = col.find(query, {"url": 1, "text": 1, "_id": 0})
                result = list(cursor)

                logger.info(
                    f"Loaded {len(result)} contents for {len(urls)} URLs (within {days} days)"
                )
                return result

        except Exception as e:
            logger.error(f"Error loading contents: {e}")
            raise

    def save_contents(
        self,
        contents: List[dict],
        collection: Optional[str] = None,
        days: int = 0,
    ) -> None:
        """Save document contents to MongoDB.

        Args:
            contents: List of dictionaries containing document contents
            collection: MongoDB collection name to save to
            days: Only update contents older than this many days (0 for always update)

        Raises:
            Exception: If database operation fails
        """
        if not contents:
            logger.warning("Empty contents list provided to save_contents")
            return

        # Use provided collection name or get from environment variable
        collection_name = collection or os.getenv("MONGO_CONTENTS_COLLECTION", "web_contents")

        try:
            with self._get_collection(collection_name) as col:
                # Ensure indexes exist
                self._ensure_indexes(col)

                company_lower, lang_lower = normalize_fields(self.company_name, self.lang)
                updated_count = 0
                skipped_count = 0

                for doc in contents:
                    if not validate_content_fields(doc):
                        logger.warning(
                            f"Skipping document with missing required fields: {doc}"
                        )
                        continue

                    url_lower = normalize_url(doc["url"])

                    # Check if we should update based on days parameter
                    should_update = True
                    if days > 0:
                        # Check if document exists and its age using normalized query
                        existing_doc = col.find_one(
                            {
                                "company_name_lower": company_lower,
                                "lang": lang_lower,
                                "url_lower": url_lower,
                            },
                            {"modified_date": 1},
                        )

                        if existing_doc and "modified_date" in existing_doc:
                            age_threshold = get_date_threshold(days)
                            # Only update if the document is older than the threshold
                            if not is_date_older_than_threshold(existing_doc["modified_date"], age_threshold):
                                should_update = False
                                skipped_count += 1
                                logger.info(
                                    f"Skipping update for {doc['url']} (not older than {days} days)"
                                )

                    if should_update:
                        col.update_one(
                            {
                                "company_name_lower": company_lower,
                                "lang": lang_lower,
                                "url_lower": url_lower,
                            },
                            {
                                "$currentDate": {"modified_date": {"$type": "date"}},
                                "$set": {
                                    "company_name": self.company_name,
                                    "company_name_lower": company_lower,
                                    "lang": lang_lower,
                                    "url": doc["url"],
                                    "url_lower": url_lower,
                                    "text": doc["text"],
                                },
                            },
                            upsert=True,
                        )
                        updated_count += 1

                logger.info(
                    f"Saved {updated_count} contents, skipped {skipped_count} (not older than {days} days)"
                )

        except Exception as e:
            logger.error(f"Error saving contents: {e}")
            raise

    def load_tags(
        self,
        urls: List[str],
        method: str,
        llm_name: str,
        collection: Optional[str] = None,
        days: int = 0,
    ) -> List[dict]:
        """Load document tags from MongoDB.

        Args:
            urls: List of URLs to load tags for
            method: Tagging method used
            llm_name: Name of the LLM used for tagging
            collection: MongoDB collection name to query
            days: Number of days to look back for data (0 for all)

        Returns:
            List of dictionaries containing document tags

        Raises:
            Exception: If database operation fails
        """
        if not urls:
            logger.warning("Empty URLs list provided to load_tags")
            return []

        # Use provided collection name or get from environment variable
        collection_name = collection or os.getenv("MONGO_TAGS_COLLECTION", "fc_tags")

        try:
            with self._get_collection(collection_name) as col:
                # Ensure indexes exist
                self._ensure_indexes(col)

                # Build query with normalized fields for index usage
                company_lower, lang_lower = normalize_fields(self.company_name, self.lang)
                urls_lower = [normalize_url(url) for url in urls]

                query = {
                    "company_name_lower": company_lower,
                    "lang": lang_lower,
                    "method": method,
                    "llm_name": llm_name,
                    "url_lower": {"$in": urls_lower},
                }

                # Add date filter if days is specified
                date_threshold = get_date_threshold(days)
                if date_threshold:
                    query["modified_date"] = {"$gte": date_threshold}

                cursor = col.find(
                    query, {"url": 1, "crime_type": 1, "probability": 1, "description": 1, "_id": 0}
                )
                result = list(cursor)

                logger.info(
                    f"Loaded {len(result)} tags for {len(urls)} URLs (within {days} days)"
                )
                return result

        except Exception as e:
            logger.error(f"Error loading tags: {e}")
            raise

    def save_tags(
        self,
        tags: List[dict],
        method: str,
        llm_name: str,
        collection: Optional[str] = None,
        days: int = 0,
    ) -> None:
        """Save document tags to MongoDB.

        Args:
            tags: List of dictionaries containing document tags
            method: Tagging method used
            llm_name: Name of the LLM used for tagging
            collection: MongoDB collection name to save to
            days: Only update tags older than this many days (0 for always update)

        Raises:
            Exception: If database operation fails
        """
        if not tags:
            logger.warning("Empty tags list provided to save_tags")
            return

        # Use provided collection name or get from environment variable
        collection_name = collection or os.getenv("MONGO_TAGS_COLLECTION", "fc_tags")

        try:
            with self._get_collection(collection_name) as col:
                # Ensure indexes exist
                self._ensure_indexes(col)

                company_lower, lang_lower = normalize_fields(self.company_name, self.lang)

                for item in tags:
                    if not validate_tag_fields(item):
                        logger.warning(
                            f"Skipping item with missing required fields: {item}"
                        )
                        continue

                    url_lower = normalize_url(item["url"])

                    # Build filter query with normalized fields
                    filter_query = {
                        "company_name_lower": company_lower,
                        "lang": lang_lower,
                        "method": method,
                        "llm_name": llm_name,
                        "url_lower": url_lower,
                    }

                    # If days is specified, add date filter to only update older records
                    date_threshold = get_date_threshold(days)
                    if date_threshold:
                        filter_query["$or"] = [
                            {"modified_date": {"$lt": date_threshold}},
                            {"modified_date": {"$exists": False}},
                        ]

                    col.update_one(
                        filter_query,
                        {
                            "$set": {
                                "company_name": self.company_name,
                                "company_name_lower": company_lower,
                                "lang": lang_lower,
                                "method": method,
                                "llm_name": llm_name,
                                "url": item["url"],
                                "url_lower": url_lower,
                                "crime_type": item["crime_type"],
                                "probability": item["probability"],
                                "description": item.get("description", "N/A"),
                                "modified_date": datetime.now(),
                            }
                        },
                        upsert=True,
                    )

                logger.info(f"Saved {len(tags)} tags to MongoDB")

        except Exception as e:
            logger.error(f"Error saving tags: {e}")
            raise

    def close(self) -> None:
        """Close the MongoDB database connection.

        Note: When using the connection manager (default), individual close calls
        do not close the shared connection pool. Use MongoConnectionManager.close()
        to close the global connection pool when shutting down the application.
        Only closes connections that were explicitly provided to the constructor.

        Raises:
            Exception: If error occurs while closing connection
        """
        try:
            # Only close if we have our own client (not from connection manager)
            if not self._uses_connection_manager:
                self.client.close()
                logger.info("Database connection closed")
            else:
                logger.debug("Connection managed by connection pool - not closing")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    def __enter__(self):
        """Context manager entry point."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point."""
        # Parameters are required by context manager protocol
        _ = exc_type, exc_val, exc_tb  # Suppress unused variable warnings
        self.close()


class RedisStore(DocStore):
    """
    Redis implementation of document storage.

    This class provides document storage functionality using Redis,
    with support for content management and tag storage operations.
    """

    def __init__(
        self,
        company_name: str,
        lang: str,
        redis_url: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
    ) -> None:
        """Initialize Redis document store.

        Args:
            company_name: Name of the company
            lang: Language code
            redis_url: Redis connection URL
            redis_client: Optional Redis client instance
        """
        super().__init__(company_name, lang)

        # Use provided client or create from URL
        if redis_client:
            self.client = redis_client
            self._uses_external_client = True
        else:
            redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
            self.client = redis.from_url(redis_url, decode_responses=True)
            self._uses_external_client = False

        logger.info(
            f"RedisStore initialized for company: {company_name}, lang: {lang}"
        )

    def _get_content_key(self, url: str) -> str:
        """Generate Redis key for content storage."""
        return f"news_scr:content:{self.company_name}:{self.lang}:{url}"

    def _get_tag_key(self, url: str, method: str, llm_name: str) -> str:
        """Generate Redis key for tag storage."""
        return f"news_scr:tags:{self.company_name}:{self.lang}:{method}:{llm_name}:{url}"

    def load_contents(
        self,
        urls: List[str],
        collection: Optional[str] = None,
        days: int = 0,
    ) -> List[dict]:
        """Load document contents from Redis.

        Args:
            urls: List of URLs to load contents for
            collection: Not used in Redis implementation (for API compatibility)
            days: Number of days to look back for data (0 for all)

        Returns:
            List of dictionaries containing document contents
        """
        if not urls:
            logger.warning("Empty URLs list provided to load_contents")
            return []

        try:
            result = []
            current_time = datetime.now()
            
            for url in urls:
                key = self._get_content_key(url)
                content_data = self.client.get(key)
                if content_data:
                    # Ensure content_data is a string before parsing JSON
                    if isinstance(content_data, bytes):
                        content_data = content_data.decode('utf-8')
                    elif not isinstance(content_data, str):
                        content_data = str(content_data)
                    content = json.loads(content_data)
                    
                    # Apply days filter if specified
                    date_threshold = get_date_threshold(days)
                    if date_threshold and "modified_date" in content:
                        try:
                            modified_date = datetime.fromisoformat(content["modified_date"])
                            if modified_date < date_threshold:
                                continue  # Skip old content
                        except (ValueError, TypeError):
                            # If date parsing fails, include the content
                            pass
                    
                    result.append({"url": url, "text": content.get("text", "")})

            logger.info(
                f"Loaded {len(result)} contents for {len(urls)} URLs (within {days} days) from Redis"
            )
            return result

        except Exception as e:
            logger.error(f"Error loading contents from Redis: {e}")
            raise

    def save_contents(
        self,
        contents: List[dict],
        collection: Optional[str] = None,
        days: int = 0,
    ) -> None:
        """Save document contents to Redis.

        Args:
            contents: List of dictionaries containing document contents
            collection: Not used in Redis implementation (for API compatibility)
            days: Only update contents older than this many days (0 for always update)
        """
        if not contents:
            logger.warning("Empty contents list provided to save_contents")
            return

        try:
            current_time = datetime.now()
            updated_count = 0
            skipped_count = 0

            # Filter valid documents
            valid_docs = [
                doc for doc in contents
                if validate_content_fields(doc)
            ]
            if len(valid_docs) < len(contents):
                logger.warning(f"Skipped {len(contents) - len(valid_docs)} documents with missing required fields")

            if not valid_docs:
                return

            # Batch fetch existing data if days filtering is needed
            existing_data_map = {}
            if days > 0:
                check_pipe = self.client.pipeline()
                keys_to_check = [self._get_content_key(doc["url"]) for doc in valid_docs]
                for key in keys_to_check:
                    check_pipe.get(key)
                existing_results = check_pipe.execute()

                age_threshold = get_date_threshold(days)
                for doc, key, existing_data in zip(valid_docs, keys_to_check, existing_results):
                    if existing_data:
                        try:
                            if isinstance(existing_data, bytes):
                                existing_data = existing_data.decode('utf-8')
                            elif not isinstance(existing_data, str):
                                existing_data = str(existing_data)
                            existing_content = json.loads(existing_data)
                            if "modified_date" in existing_content:
                                modified_date = datetime.fromisoformat(existing_content["modified_date"])
                                if not is_date_older_than_threshold(modified_date, age_threshold):
                                    existing_data_map[doc["url"]] = True
                                    skipped_count += 1
                                    logger.info(
                                        f"Skipping update for {doc['url']} (not older than {days} days)"
                                    )
                        except (ValueError, TypeError, json.JSONDecodeError):
                            pass

            # Build and execute save pipeline
            pipe = self.client.pipeline()
            for doc in valid_docs:
                if doc["url"] not in existing_data_map:
                    key = self._get_content_key(doc["url"])
                    content_data = {
                        "text": doc["text"],
                        "modified_date": current_time.isoformat(),
                        "company_name": self.company_name,
                        "lang": self.lang,
                        "url": doc["url"]
                    }
                    pipe.set(key, json.dumps(content_data))
                    updated_count += 1

            pipe.execute()
            logger.info(
                f"Saved {updated_count} contents, skipped {skipped_count} (not older than {days} days)"
            )

        except Exception as e:
            logger.error(f"Error saving contents to Redis: {e}")
            raise

    def load_tags(
        self,
        urls: List[str],
        method: str,
        llm_name: str,
        collection: Optional[str] = None,
        days: int = 0,
    ) -> List[dict]:
        """Load document tags from Redis.

        Args:
            urls: List of URLs to load tags for
            method: Tagging method used
            llm_name: Name of the LLM used for tagging
            collection: Not used in Redis implementation (for API compatibility)
            days: Number of days to look back for data (0 for all)

        Returns:
            List of dictionaries containing document tags
        """
        if not urls:
            logger.warning("Empty URLs list provided to load_tags")
            return []

        try:
            result = []
            current_time = datetime.now()
            
            for url in urls:
                key = self._get_tag_key(url, method, llm_name)
                tag_data = self.client.get(key)
                if tag_data:
                    # Ensure tag_data is a string before parsing JSON
                    if isinstance(tag_data, bytes):
                        tag_data = tag_data.decode('utf-8')
                    elif not isinstance(tag_data, str):
                        tag_data = str(tag_data)
                    tag = json.loads(tag_data)
                    
                    # Apply days filter if specified
                    date_threshold = get_date_threshold(days)
                    if date_threshold and "modified_date" in tag:
                        try:
                            modified_date = datetime.fromisoformat(tag["modified_date"])
                            if modified_date < date_threshold:
                                continue  # Skip old tags
                        except (ValueError, TypeError):
                            # If date parsing fails, include the tag
                            pass
                    
                    result.append({
                        "url": url,
                        "crime_type": tag.get("crime_type", ""),
                        "probability": tag.get("probability", 0.0),
                        "description": tag.get("description", "")
                    })

            logger.info(
                f"Loaded {len(result)} tags for {len(urls)} URLs (within {days} days) from Redis"
            )
            return result

        except Exception as e:
            logger.error(f"Error loading tags from Redis: {e}")
            raise

    def save_tags(
        self,
        tags: List[dict],
        method: str,
        llm_name: str,
        collection: Optional[str] = None,
        days: int = 0,
    ) -> None:
        """Save document tags to Redis.

        Args:
            tags: List of dictionaries containing document tags
            method: Tagging method used
            llm_name: Name of the LLM used for tagging
            collection: Not used in Redis implementation (for API compatibility)
            days: Only update tags older than this many days (0 for always update)
        """
        if not tags:
            logger.warning("Empty tags list provided to save_tags")
            return

        try:
            current_time = datetime.now()
            updated_count = 0
            skipped_count = 0

            # Filter valid tags
            valid_tags = [
                item for item in tags
                if validate_tag_fields(item)
            ]
            if len(valid_tags) < len(tags):
                logger.warning(f"Skipped {len(tags) - len(valid_tags)} items with missing required fields")

            if not valid_tags:
                return

            # Batch fetch existing data if days filtering is needed
            existing_data_map = {}
            if days > 0:
                check_pipe = self.client.pipeline()
                keys_to_check = [self._get_tag_key(item["url"], method, llm_name) for item in valid_tags]
                for key in keys_to_check:
                    check_pipe.get(key)
                existing_results = check_pipe.execute()

                age_threshold = get_date_threshold(days)
                for item, key, existing_data in zip(valid_tags, keys_to_check, existing_results):
                    if existing_data:
                        try:
                            if isinstance(existing_data, bytes):
                                existing_data = existing_data.decode('utf-8')
                            elif not isinstance(existing_data, str):
                                existing_data = str(existing_data)
                            existing_tag = json.loads(existing_data)
                            if "modified_date" in existing_tag:
                                modified_date = datetime.fromisoformat(existing_tag["modified_date"])
                                if not is_date_older_than_threshold(modified_date, age_threshold):
                                    existing_data_map[item["url"]] = True
                                    skipped_count += 1
                                    logger.info(
                                        f"Skipping update for {item['url']} (not older than {days} days)"
                                    )
                        except (ValueError, TypeError, json.JSONDecodeError):
                            pass

            # Build and execute save pipeline
            pipe = self.client.pipeline()
            for item in valid_tags:
                if item["url"] not in existing_data_map:
                    key = self._get_tag_key(item["url"], method, llm_name)
                    tag_data = {
                        "crime_type": item["crime_type"],
                        "probability": item["probability"],
                        "description": item.get("description", "N/A"),
                        "modified_date": current_time.isoformat(),
                        "company_name": self.company_name,
                        "lang": self.lang,
                        "method": method,
                        "llm_name": llm_name,
                        "url": item["url"]
                    }
                    pipe.set(key, json.dumps(tag_data))
                    updated_count += 1

            pipe.execute()
            logger.info(f"Saved {updated_count} tags, skipped {skipped_count} (not older than {days} days)")

        except Exception as e:
            logger.error(f"Error saving tags to Redis: {e}")
            raise

    def close(self) -> None:
        """Close the Redis database connection.

        Note: Only closes connections that were created internally (not provided).
        External clients are managed by their creators.
        """
        try:
            if not self._uses_external_client:
                self.client.close()
                logger.info("Redis connection closed")
            else:
                logger.debug("Redis connection managed externally - not closing")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

    def __enter__(self):
        """Context manager entry point."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point."""
        # Parameters are required by context manager protocol
        _ = exc_type, exc_val, exc_tb  # Suppress unused variable warnings
        self.close()
