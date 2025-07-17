import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Optional
from contextlib import contextmanager

from pymongo import MongoClient
from pymongo.errors import PyMongoError

# Constants definition
DEFAULT_DB_NAME = "adverse_news_screening"
DEFAULT_CONTENTS_COLLECTION = "web_contents"
DEFAULT_TAGS_COLLECTION = "fc_tags"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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
        db: str = DEFAULT_DB_NAME,
    ) -> None:
        """Initialize MongoDB document store.
        
        Args:
            company_name: Name of the company
            lang: Language code
            client: Optional MongoDB client instance
            db: Database name to use
        """
        super().__init__(company_name, lang)
        self.client = client or MongoClient()
        self.db = db
        logger.info(f"MongoStore initialized for company: {company_name}, lang: {lang}")

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
        collection: str = DEFAULT_CONTENTS_COLLECTION,
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

        try:
            with self._get_collection(collection) as col:
                # Build query conditions with case-insensitive matching
                query = {
                    "company_name": {"$regex": f"^{re.escape(self.company_name)}$", "$options": "i"},
                    "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                    "$or": [{"url": {"$regex": f"^{re.escape(url)}$", "$options": "i"}} for url in urls],
                }

                # Add date filter if days is specified
                if days > 0:
                    within_date = datetime.combine(
                        datetime.today(), datetime.min.time()
                    ) - timedelta(days=days)
                    query["modified_date"] = {"$gte": within_date}

                cursor = col.find(query, {"url": 1, "text": 1, "_id": 0})
                result = list(cursor)
                
                logger.info(f"Loaded {len(result)} contents for {len(urls)} URLs (within {days} days)")
                return result
                
        except Exception as e:
            logger.error(f"Error loading contents: {e}")
            raise

    def save_contents(
        self, contents: List[dict], collection: str = DEFAULT_CONTENTS_COLLECTION, days: int = 0
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

        try:
            with self._get_collection(collection) as col:
                updated_count = 0
                skipped_count = 0
                
                for doc in contents:
                    if "url" not in doc or "text" not in doc:
                        logger.warning(f"Skipping document with missing required fields: {doc}")
                        continue
                    
                    # Check if we should update based on days parameter
                    should_update = True
                    if days > 0:
                        # Check if document exists and its age
                        existing_doc = col.find_one(
                            {
                                "company_name": {"$regex": f"^{re.escape(self.company_name)}$", "$options": "i"},
                                "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                                "url": {"$regex": f"^{re.escape(doc['url'])}$", "$options": "i"},
                            },
                            {"modified_date": 1}
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
                                logger.info(f"Skipping update for {doc['url']} (not older than {days} days)")
                    
                    if should_update:
                        col.update_one(
                            {
                                "company_name": {"$regex": f"^{re.escape(self.company_name)}$", "$options": "i"},
                                "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                                "url": {"$regex": f"^{re.escape(doc['url'])}$", "$options": "i"},
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
                    
                logger.info(f"Saved {updated_count} contents, skipped {skipped_count} (not older than {days} days)")
                
        except Exception as e:
            logger.error(f"Error saving contents: {e}")
            raise

    def load_tags(
        self,
        urls: List[str],
        method: str,
        llm_name: str,
        collection: str = DEFAULT_TAGS_COLLECTION,
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

        try:
            with self._get_collection(collection) as col:
                # Build query conditions with case-insensitive matching
                query = {
                    "company_name": {"$regex": f"^{re.escape(self.company_name)}$", "$options": "i"},
                    "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                    "method": method,
                    "llm_name": llm_name,
                    "$or": [{"url": {"$regex": f"^{re.escape(url)}$", "$options": "i"}} for url in urls],
                }

                # Add date filter if days is specified
                if days > 0:
                    within_date = datetime.combine(
                        datetime.today(), datetime.min.time()
                    ) - timedelta(days=days)
                    query["modified_date"] = {"$gte": within_date}

                cursor = col.find(query, {"url": 1, "crime_type": 1, "probability": 1, "_id": 0})
                result = list(cursor)
                
                logger.info(f"Loaded {len(result)} tags for {len(urls)} URLs (within {days} days)")
                return result
                
        except Exception as e:
            logger.error(f"Error loading tags: {e}")
            raise

    def save_tags(
        self, tags: List[dict], method: str, llm_name: str, collection: str = DEFAULT_TAGS_COLLECTION, days: int = 0
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

        try:
            with self._get_collection(collection) as col:
                for item in tags:
                    required_fields = ["url", "crime_type", "probability"]
                    if not all(field in item for field in required_fields):
                        logger.warning(f"Skipping item with missing required fields: {item}")
                        continue
                    
                    # Build update query with case-insensitive matching
                    filter_query = {
                        "company_name": {"$regex": f"^{re.escape(self.company_name)}$", "$options": "i"},
                        "lang": {"$regex": f"^{re.escape(self.lang)}$", "$options": "i"},
                        "method": method,
                        "llm_name": llm_name,
                        "url": {"$regex": f"^{re.escape(item['url'])}$", "$options": "i"},
                    }

                    # If days is specified, add date filter to only update older records
                    if days > 0:
                        older_than_date = datetime.combine(
                            datetime.today(), datetime.min.time()
                        ) - timedelta(days=days)
                        filter_query["$or"] = [
                            {"modified_date": {"$lt": older_than_date}},
                            {"modified_date": {"$exists": False}}
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
        
        Raises:
            Exception: If error occurs while closing connection
        """
        try:
            self.client.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    def __enter__(self):
        """Context manager entry point."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point."""
        self.close()
