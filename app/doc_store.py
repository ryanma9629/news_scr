"""
Document storage implementations using MongoDB.

This module (doc_store.py) provides abstract and concrete implementations for
document storage functionality, including content and tag management with MongoDB backend.
"""

import json
import logging
import os
import re
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import redis
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .logging_config import get_logger

# Initialize logger using shared configuration
logger = get_logger(__name__)


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
            client: Optional MongoDB client instance (deprecated - use connection manager)
            db: Database name to use
        """
        super().__init__(company_name, lang)

        # Use provided client or get from connection manager (thread-safe singleton)
        if client:
            self.client = client
            self._owns_client = True  # We own this client and can close it
            logger.warning("Using provided MongoDB client - connection pooling not available")
        else:
            self.client = _mongo_manager.get_client()
            self._owns_client = False  # Connection manager owns the client
            
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
                # Build query conditions with case-insensitive matching
                query = {
                    "company_name": {
                        "$regex": f"^{re.escape(self.company_name)}$",
                        "$options": "i",
                    },
                    "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                    "$or": [
                        {"url": {"$regex": f"^{re.escape(url)}$", "$options": "i"}}
                        for url in urls
                    ],
                }

                # Add date filter if days is specified
                if days > 0:
                    within_date = datetime.combine(
                        datetime.today(), datetime.min.time()
                    ) - timedelta(days=days)
                    query["modified_date"] = {"$gte": within_date}

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
                updated_count = 0
                skipped_count = 0

                for doc in contents:
                    if "url" not in doc or "text" not in doc:
                        logger.warning(
                            f"Skipping document with missing required fields: {doc}"
                        )
                        continue

                    # Check if we should update based on days parameter
                    should_update = True
                    if days > 0:
                        # Check if document exists and its age
                        existing_doc = col.find_one(
                            {
                                "company_name": {
                                    "$regex": f"^{re.escape(self.company_name)}$",
                                    "$options": "i",
                                },
                                "lang": {
                                    "$regex": f"^{re.escape(self.lang)}$",
                                    "$options": "i",
                                },
                                "url": {
                                    "$regex": f"^{re.escape(doc['url'])}$",
                                    "$options": "i",
                                },
                            },
                            {"modified_date": 1},
                        )

                        if existing_doc and "modified_date" in existing_doc:
                            # Calculate the age of the existing document
                            age_threshold = datetime.combine(
                                datetime.today(), datetime.min.time()
                            ) - timedelta(days=days)

                            # Only update if the document is older than the threshold
                            if existing_doc["modified_date"] > age_threshold:
                                should_update = False
                                skipped_count += 1
                                logger.info(
                                    f"Skipping update for {doc['url']} (not older than {days} days)"
                                )

                    if should_update:
                        col.update_one(
                            {
                                "company_name": {
                                    "$regex": f"^{re.escape(self.company_name)}$",
                                    "$options": "i",
                                },
                                "lang": {
                                    "$regex": f"^{re.escape(self.lang)}$",
                                    "$options": "i",
                                },
                                "url": {
                                    "$regex": f"^{re.escape(doc['url'])}$",
                                    "$options": "i",
                                },
                            },
                            {
                                "$currentDate": {"modified_date": {"$type": "date"}},
                                "$set": {
                                    "company_name": self.company_name,
                                    "lang": self.lang,
                                    "url": doc["url"],
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
                # Build query conditions with case-insensitive matching
                query = {
                    "company_name": {
                        "$regex": f"^{re.escape(self.company_name)}$",
                        "$options": "i",
                    },
                    "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                    "method": method,
                    "llm_name": llm_name,
                    "$or": [
                        {"url": {"$regex": f"^{re.escape(url)}$", "$options": "i"}}
                        for url in urls
                    ],
                }

                # Add date filter if days is specified
                if days > 0:
                    within_date = datetime.combine(
                        datetime.today(), datetime.min.time()
                    ) - timedelta(days=days)
                    query["modified_date"] = {"$gte": within_date}

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
                for item in tags:
                    required_fields = ["url", "crime_type", "probability"]
                    if not all(field in item for field in required_fields):
                        logger.warning(
                            f"Skipping item with missing required fields: {item}"
                        )
                        continue

                    # Build update query with case-insensitive matching
                    filter_query = {
                        "company_name": {
                            "$regex": f"^{re.escape(self.company_name)}$",
                            "$options": "i",
                        },
                        "lang": {
                            "$regex": f"^{re.escape(self.lang)}$",
                            "$options": "i",
                        },
                        "method": method,
                        "llm_name": llm_name,
                        "url": {
                            "$regex": f"^{re.escape(item['url'])}$",
                            "$options": "i",
                        },
                    }

                    # If days is specified, add date filter to only update older records
                    if days > 0:
                        older_than_date = datetime.combine(
                            datetime.today(), datetime.min.time()
                        ) - timedelta(days=days)
                        filter_query["$or"] = [
                            {"modified_date": {"$lt": older_than_date}},
                            {"modified_date": {"$exists": False}},
                        ]

                    col.update_one(
                        filter_query,
                        {
                            "$set": {
                                "company_name": self.company_name,
                                "lang": self.lang,
                                "method": method,
                                "llm_name": llm_name,
                                "url": item["url"],
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
        
        Note: When using the connection manager, individual close calls do not
        close the shared connection pool. Use MongoConnectionManager.close() 
        to close the global connection pool when shutting down the application.

        Raises:
            Exception: If error occurs while closing connection
        """
        try:
            # Only close if we own the client (not using connection manager)
            if self._owns_client:
                self.client.close()
                logger.info("Individual database connection closed")
            else:
                logger.info("Database connection managed by connection pool")
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

        if redis_client:
            self.client = redis_client
            self._owns_client = False
        else:
            redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
            self.client = redis.from_url(redis_url, decode_responses=True)
            self._owns_client = True
            
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
                    if days > 0 and "modified_date" in content:
                        try:
                            modified_date = datetime.fromisoformat(content["modified_date"])
                            age_threshold = current_time - timedelta(days=days)
                            if modified_date < age_threshold:
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
                if "url" in doc and "text" in doc
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

                age_threshold = current_time - timedelta(days=days)
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
                                if modified_date > age_threshold:
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
                    if days > 0 and "modified_date" in tag:
                        try:
                            modified_date = datetime.fromisoformat(tag["modified_date"])
                            age_threshold = current_time - timedelta(days=days)
                            if modified_date < age_threshold:
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
            required_fields = ["url", "crime_type", "probability"]
            valid_tags = [
                item for item in tags
                if all(field in item for field in required_fields)
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

                age_threshold = current_time - timedelta(days=days)
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
                                if modified_date > age_threshold:
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
        """Close the Redis database connection."""
        try:
            if self._owns_client:
                self.client.close()
                logger.info("Redis connection closed")
            else:
                logger.info("Redis connection managed externally")
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
