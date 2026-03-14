"""
Vector store implementations using Chroma.

This module provides a singleton Chroma vector store manager for persistent
embedding storage across the application.
"""

__all__ = [
    "ChromaVectorStoreManager",
    "get_chroma_store",
    "get_company_chroma_store",
    "setup_vector_store",
]

import os
import threading
from typing import List, Optional

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma

from .config import DEFAULT_CHROMA_PERSIST_DIR
from .logging_config import get_logger

# Load environment variables
load_dotenv()

# Initialize logger
logger = get_logger(__name__)


class ChromaVectorStoreManager:
    """
    Singleton manager for Chroma vector store instances.

    This class provides thread-safe access to Chroma vector stores with
    persistent storage, allowing reuse of embeddings across requests.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._stores = {}  # collection_name -> Chroma instance
                    instance._persist_dir = os.getenv(
                        "CHROMA_PERSIST_DIR", DEFAULT_CHROMA_PERSIST_DIR
                    )
                    instance._stores_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    def get_store(
        self,
        collection_name: str,
        embedding_function: Embeddings,
        persist_directory: Optional[str] = None,
    ) -> Chroma:
        """
        Get or create a Chroma vector store for the given collection.

        Args:
            collection_name: Name of the collection to use
            embedding_function: Embedding function for the vector store
            persist_directory: Optional custom persist directory

        Returns:
            Chroma vector store instance
        """
        key = (collection_name, id(embedding_function))

        with self._stores_lock:
            if key not in self._stores:
                persist_dir = persist_directory or self._persist_dir

                # Ensure directory exists
                os.makedirs(persist_dir, exist_ok=True)

                logger.info(
                    f"Creating Chroma vector store: collection={collection_name}, "
                    f"persist_dir={persist_dir}"
                )

                self._stores[key] = Chroma(
                    collection_name=collection_name,
                    embedding_function=embedding_function,
                    persist_directory=persist_dir,
                )

            return self._stores[key]

    def get_company_store(
        self,
        company_name: str,
        lang: str,
        embedding_function: Embeddings,
    ) -> Chroma:
        """
        Get a Chroma store scoped to a specific company and language.

        This creates a unique collection name based on company and language,
        allowing isolation of embeddings per company.

        Args:
            company_name: Company name for collection naming
            lang: Language code for collection naming
            embedding_function: Embedding function for the vector store

        Returns:
            Chroma vector store instance for the company
        """
        # Create a safe collection name (lowercase, no special chars)
        safe_company = "".join(
            c.lower() if c.isalnum() else "_" for c in company_name
        )
        safe_lang = lang.lower().replace("-", "_")
        collection_name = f"news_{safe_company}_{safe_lang}"

        return self.get_store(collection_name, embedding_function)

    def clear_store(self, collection_name: str, embedding_function: Embeddings) -> None:
        """
        Clear a specific vector store collection.

        Args:
            collection_name: Name of the collection to clear
            embedding_function: Embedding function used to create the store
        """
        key = (collection_name, id(embedding_function))

        with self._stores_lock:
            if key in self._stores:
                # Delete the collection
                store = self._stores[key]
                store.delete_collection()
                del self._stores[key]
                logger.info(f"Cleared Chroma collection: {collection_name}")

    def clear_all(self) -> None:
        """Clear all cached vector store instances."""
        with self._stores_lock:
            for key, store in self._stores.items():
                try:
                    store.delete_collection()
                    logger.info(f"Cleared Chroma collection: {key[0]}")
                except Exception as e:
                    logger.warning(f"Error clearing collection {key[0]}: {e}")
            self._stores.clear()


# Global instance
_chroma_manager = ChromaVectorStoreManager()


def get_chroma_store(
    collection_name: str,
    embedding_function: Embeddings,
    persist_directory: Optional[str] = None,
) -> Chroma:
    """
    Get a Chroma vector store instance.

    Args:
        collection_name: Name of the collection to use
        embedding_function: Embedding function for the vector store
        persist_directory: Optional custom persist directory

    Returns:
        Chroma vector store instance
    """
    return _chroma_manager.get_store(collection_name, embedding_function, persist_directory)


def get_company_chroma_store(
    company_name: str,
    lang: str,
    embedding_function: Embeddings,
) -> Chroma:
    """
    Get a Chroma store scoped to a specific company and language.

    Args:
        company_name: Company name for collection naming
        lang: Language code for collection naming
        embedding_function: Embedding function for the vector store

    Returns:
        Chroma vector store instance for the company
    """
    return _chroma_manager.get_company_store(company_name, lang, embedding_function)


async def setup_vector_store(
    docs: Optional[List],
    embedding_function: Embeddings,
    vectordb: Optional[Chroma] = None,
    company_name: Optional[str] = None,
    lang: Optional[str] = None,
) -> tuple[Chroma, Optional[dict]]:
    """
    Set up a vector store for document retrieval.

    This function handles the common pattern of creating or using a vector store
    with optional company/language scoping for persistence.

    Args:
        docs: Optional list of documents to add to the vector store
        embedding_function: Embedding function for the vector store
        vectordb: Optional pre-existing vector store
        company_name: Optional company name for persistent store scoping
        lang: Optional language for persistent store scoping

    Returns:
        Tuple of (vectordb, filter_dict) where filter_dict is None if a new
        vectordb was created, or {} if an existing one was provided

    Raises:
        ValueError: If neither docs nor vectordb are provided
    """
    if not docs and not vectordb:
        raise ValueError("At least one of 'docs' or 'vectordb' must be provided.")

    if not vectordb:
        if company_name and lang:
            logger.info(f"Using persistent Chroma store for company: {company_name}, lang: {lang}")
            vectordb = get_company_chroma_store(company_name, lang, embedding_function)
        else:
            logger.info("Creating transient Chroma store")
            vectordb = Chroma(embedding_function=embedding_function)

        if docs:
            await vectordb.aadd_documents(docs)
        return vectordb, None

    return vectordb, {}