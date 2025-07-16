from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Optional
import logging
from contextlib import contextmanager

from pymongo import MongoClient
from pymongo.errors import PyMongoError

# Constants definition
DEFAULT_DB_NAME = "adverse_news_screening"
DEFAULT_CONTENTS_COLLECTION = "web_contents"
DEFAULT_TAGS_COLLECTION = "fc_tags"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DocStore(ABC):
    def __init__(self, company_name: str, lang: str) -> None:
        self.company_name = company_name
        self.lang = lang

    @abstractmethod
    def load_contents(self, urls: List[str]) -> List[dict]:
        raise NotImplementedError

    @abstractmethod
    def save_contents(self, contents: List[dict]) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_tags(self, urls: List[str]) -> List[dict]:
        raise NotImplementedError

    @abstractmethod
    def save_tags(self, tags: List[dict]) -> None:
        raise NotImplementedError


class MongoStore(DocStore):
    def __init__(
        self,
        company_name: str,
        lang: str,
        client: Optional[MongoClient] = None,
        db: str = DEFAULT_DB_NAME,
    ) -> None:
        super().__init__(company_name, lang)
        self.client = client or MongoClient()
        self.db = db
        logger.info(f"MongoStore initialized for company: {company_name}, lang: {lang}")

    @contextmanager
    def _get_collection(self, collection: str):
        """Context manager for safely accessing collections"""
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
        data_within_days: int = 0,
        collection: str = DEFAULT_CONTENTS_COLLECTION,
    ) -> List[dict]:
        if not urls:
            logger.warning("Empty URLs list provided to load_contents")
            return []

        try:
            with self._get_collection(collection) as col:
                # Build query conditions
                query = {
                    "company_name": self.company_name,
                    "lang": self.lang,
                    "url": {"$in": urls},
                }

                if data_within_days:
                    within_date = datetime.combine(
                        datetime.today(), datetime.min.time()
                    ) - timedelta(data_within_days)
                    query["modified_date"] = {"$gte": within_date}

                cursor = col.find(query, {"url": 1, "text": 1, "_id": 0})
                result = list(cursor)
                
                logger.info(f"Loaded {len(result)} contents for {len(urls)} URLs")
                return result
                
        except Exception as e:
            logger.error(f"Error loading contents: {e}")
            raise

    def save_contents(
        self, contents: List[dict], collection: str = DEFAULT_CONTENTS_COLLECTION
    ) -> None:
        if not contents:
            logger.warning("Empty contents list provided to save_contents")
            return

        try:
            with self._get_collection(collection) as col:
                for doc in contents:
                    if "url" not in doc or "text" not in doc:
                        logger.warning(f"Skipping document with missing required fields: {doc}")
                        continue
                        
                    col.update_one(
                        {
                            "company_name": self.company_name,
                            "lang": self.lang,
                            "url": doc["url"],
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
                    
                logger.info(f"Saved {len(contents)} contents")
                
        except Exception as e:
            logger.error(f"Error saving contents: {e}")
            raise

    def load_tags(
        self,
        urls: List[str],
        method: str,
        llm_name: str,
        data_within_days: int = 0,
        collection: str = DEFAULT_TAGS_COLLECTION,
    ) -> List[dict]:
        if not urls:
            logger.warning("Empty URLs list provided to load_tags")
            return []

        try:
            with self._get_collection(collection) as col:
                # Build query conditions
                query = {
                    "company_name": self.company_name,
                    "lang": self.lang,
                    "method": method,
                    "llm_name": llm_name,
                    "url": {"$in": urls},
                }

                if data_within_days:
                    within_date = datetime.combine(
                        datetime.today(), datetime.min.time()
                    ) - timedelta(data_within_days)
                    query["modified_date"] = {"$gte": within_date}

                cursor = col.find(query, {"url": 1, "crime_type": 1, "probability": 1, "_id": 0})
                result = list(cursor)
                
                logger.info(f"Loaded {len(result)} tags for {len(urls)} URLs")
                return result
                
        except Exception as e:
            logger.error(f"Error loading tags: {e}")
            raise

    def save_tags(
        self, tags: List[dict], method: str, llm_name: str, collection: str = DEFAULT_TAGS_COLLECTION
    ) -> None:
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
                        
                    col.update_one(
                        {
                            "company_name": self.company_name,
                            "lang": self.lang,
                            "method": method,
                            "llm_name": llm_name,
                            "url": item["url"],
                        },
                        {
                            "$currentDate": {"modified_date": {"$type": "date"}},
                            "$set": {
                                "company_name": self.company_name,
                                "lang": self.lang,
                                "method": method,
                                "llm_name": llm_name,
                                "url": item["url"],
                                "crime_type": item["crime_type"],
                                "probability": item["probability"],
                            },
                        },
                        upsert=True,
                    )
                    
                logger.info(f"Saved {len(tags)} tags")
                
        except Exception as e:
            logger.error(f"Error saving tags: {e}")
            raise

    def close(self) -> None:
        """Close database connection"""
        try:
            self.client.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
