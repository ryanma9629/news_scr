"""
PostgreSQL storage implementations for tag management.

This module provides PostgreSQL-based storage functionality for managing
document tags with connection pooling and thread safety.
"""

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional
from functools import lru_cache

import psycopg2
from psycopg2 import sql

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize logger
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_connection_params() -> dict:
    """Get PostgreSQL connection parameters from environment variables (cached).
    
    Returns:
        Dictionary containing connection parameters
    """
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise ValueError(
            "POSTGRES_PASSWORD environment variable is required but not set. "
            "Please set a secure PostgreSQL password in your .env file."
        )
    
    params = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "SharedServices"),
        "user": os.getenv("POSTGRES_USER", "dbmsowner"),
        "password": password,
    }
    
    logger.info(f"PostgreSQL connection parameters loaded: {params['host']}:{params['port']}/{params['database']}")
    return params


@contextmanager
def get_connection():
    """Get a PostgreSQL connection with automatic cleanup.
    
    Yields:
        psycopg2 connection object
    """
    conn = None
    try:
        conn = psycopg2.connect(**get_connection_params())
        yield conn
    except Exception as e:
        logger.error(f"PostgreSQL connection error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


class PostgreSQLTagStore:
    """PostgreSQL implementation for storing tagging results."""

    def __init__(self, table_name: Optional[str] = None, schema: Optional[str] = None):
        """Initialize PostgreSQL tag store.

        Args:
            table_name: Optional table name override
            schema: Optional schema name override
        """
        self.table_name = table_name or os.getenv("POSTGRES_TAGS_TABLE", "fc_tags")
        self.schema = schema or os.getenv("POSTGRES_SCHEMA", "namecheck")
        self.qualified_table = sql.Identifier(self.schema, self.table_name)
        self._ensure_schema_and_table_exist()
        logger.info(f"PostgreSQLTagStore initialized: {self.schema}.{self.table_name}")

    def _create_indexes(self, cursor):
        """Create database indexes for better performance."""
        indexes = [
            (f"{self.schema}_{self.table_name}_customer_company_lang_idx", "(customer_id, company_name, lang)"),
            (f"{self.schema}_{self.table_name}_url_idx", "(url)"),
            (f"{self.schema}_{self.table_name}_method_llm_idx", "(method, llm_name)"),
            (f"{self.schema}_{self.table_name}_modified_date_idx", "(modified_date)"),
        ]
        
        for idx_name, columns in indexes:
            query = sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} {}").format(
                sql.Identifier(idx_name), self.qualified_table, sql.SQL(columns)
            )
            cursor.execute(query)

    def _ensure_schema_and_table_exist(self):
        """Ensure the schema and tags table exist with proper indexes."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    # Create schema if needed
                    if self.schema != "public":
                        cursor.execute(
                            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema))
                        )

                    # Create table
                    cursor.execute(sql.SQL("""
                        CREATE TABLE IF NOT EXISTS {} (
                            id SERIAL PRIMARY KEY,
                            customer_id VARCHAR(64),
                            company_name VARCHAR(255) NOT NULL,
                            lang VARCHAR(10) NOT NULL,
                            url TEXT NOT NULL,
                            title TEXT,
                            method VARCHAR(50) NOT NULL,
                            llm_name VARCHAR(100) NOT NULL,
                            crime_type VARCHAR(255),
                            probability VARCHAR(50),
                            description TEXT,
                            modified_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(customer_id, company_name, lang, url, method, llm_name)
                        )
                    """).format(self.qualified_table))

                    # Create indexes
                    self._create_indexes(cursor)
                    conn.commit()
                    logger.info(f"Table '{self.schema}.{self.table_name}' ensured with indexes")

        except Exception as e:
            logger.error(f"Error ensuring table exists: {e}")
            raise

    def _should_update_record(self, cursor, company_name: str, lang: str, url: str, 
                             method: str, llm_name: str, customer_id: str, days: int) -> bool:
        """Check if a record should be updated based on age threshold."""
        if days <= 0:
            return True
            
        cursor.execute(sql.SQL("""
            SELECT modified_date FROM {} 
            WHERE LOWER(company_name) = LOWER(%s) AND LOWER(lang) = LOWER(%s) 
            AND url = %s AND method = %s AND llm_name = %s AND customer_id = %s
        """).format(self.qualified_table), 
        (company_name, lang, url, method, llm_name, customer_id))
        
        record = cursor.fetchone()
        if not record:
            return True
            
        age_threshold = datetime.now() - timedelta(days=days)
        return record[0] <= age_threshold

    def save_tags(
        self,
        tags: List[dict],
        company_name: str,
        lang: str,
        method: str,
        llm_name: str,
        days: int = 0,
        customer_id: Optional[str] = None,
    ) -> None:
        """Save document tags to PostgreSQL.

        Args:
            tags: List of dictionaries containing document tags
            company_name: Name of the company
            lang: Language code
            method: Tagging method used
            llm_name: Name of the LLM used for tagging
            days: Only update tags older than this many days (0 for always update)
            customer_id: Customer identifier for multi-tenant support
        """
        if not tags:
            logger.warning("Empty tags list provided to save_tags")
            return

        customer_id = customer_id or "default"
        logger.info(f"Saving {len(tags)} tags for customer: {customer_id}")

        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    saved_count = skipped_count = 0

                    for item in tags:
                        # Validate required fields
                        if not all(field in item for field in ["url", "crime_type", "probability"]):
                            logger.warning(f"Skipping item with missing fields: {item}")
                            continue

                        # Check if update is needed
                        if not self._should_update_record(cursor, company_name, lang, item["url"], 
                                                        method, llm_name, customer_id, days):
                            skipped_count += 1
                            continue

                        # Simplified upsert
                        cursor.execute(sql.SQL("""
                            INSERT INTO {} (customer_id, company_name, lang, url, title, method, 
                                          llm_name, crime_type, probability, description, modified_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (customer_id, company_name, lang, url, method, llm_name)
                            DO UPDATE SET
                                title = EXCLUDED.title,
                                crime_type = EXCLUDED.crime_type,
                                probability = EXCLUDED.probability,
                                description = EXCLUDED.description,
                                modified_date = EXCLUDED.modified_date
                        """).format(self.qualified_table), (
                            customer_id, company_name, lang, item["url"], item.get("title"),
                            method, llm_name, item["crime_type"], item["probability"], 
                            item.get("description", "N/A"), datetime.now()
                        ))
                        saved_count += 1

                    conn.commit()
                    logger.info(f"Saved {saved_count} tags, skipped {skipped_count}")

        except Exception as e:
            logger.error(f"Error saving tags: {e}")
            raise

    def close(self):
        """Close method for consistency with other stores."""
        logger.info("PostgreSQL tag store close() called")


# Export the main class
__all__ = ["PostgreSQLTagStore"]
