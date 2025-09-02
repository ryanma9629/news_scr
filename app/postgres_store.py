"""
PostgreSQL storage implementations for tag management.

This module provides PostgreSQL-based storage functionality for managing
document tags with connection pooling and thread safety.
"""

import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import psycopg2
import psycopg2.extras
from psycopg2 import sql

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize logger
logger = logging.getLogger(__name__)


class PostgreSQLConnectionManager:
    """Singleton PostgreSQL connection manager with connection pooling for thread safety."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._connection_params = None
            self._initialized = True

    def get_connection_params(self) -> dict:
        """Get PostgreSQL connection parameters from environment variables.

        Returns:
            Dictionary containing connection parameters
        """
        if self._connection_params is None:
            with self._lock:
                if self._connection_params is None:
                    self._connection_params = {
                        "host": os.getenv("POSTGRES_HOST", "localhost"),
                        "port": int(os.getenv("POSTGRES_PORT", "5432")),
                        "database": os.getenv("POSTGRES_DB", "SharedServices"),
                        "user": os.getenv("POSTGRES_USER", "dbmsowner"),
                        "password": os.getenv("POSTGRES_PASSWORD"),
                        "schema": os.getenv("POSTGRES_SCHEMA", "namecheck"),
                    }
                    
                    # Validate that password is provided
                    if not self._connection_params["password"]:
                        raise ValueError(
                            "POSTGRES_PASSWORD environment variable is required but not set. "
                            "Please set a secure PostgreSQL password in your .env file."
                        )
                    logger.info(
                        f"PostgreSQL connection parameters loaded: {self._connection_params['host']}:{self._connection_params['port']}/{self._connection_params['database']}"
                    )

        return self._connection_params.copy()

    @contextmanager
    def get_connection(self):
        """Get a PostgreSQL connection with automatic cleanup.

        Yields:
            psycopg2 connection object

        Raises:
            psycopg2.Error: If database connection fails
        """
        conn = None
        try:
            params = self.get_connection_params()
            # Remove 'schema' from connection params as it's not a valid psycopg2 parameter
            connection_params = {k: v for k, v in params.items() if k != 'schema'}
            conn = psycopg2.connect(**connection_params)
            yield conn
        except psycopg2.Error as e:
            logger.error(f"PostgreSQL connection error: {e}")
            if conn:
                conn.rollback()
            raise
        except Exception as e:
            logger.error(f"Unexpected error with PostgreSQL connection: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()


# Global PostgreSQL connection manager instance
_postgres_manager = PostgreSQLConnectionManager()


class PostgreSQLTagStore:
    """
    PostgreSQL implementation for storing tagging results.

    This class provides tag storage functionality using PostgreSQL,
    with automatic table creation and schema management.
    """

    def __init__(self, table_name: Optional[str] = None, schema: Optional[str] = None):
        """Initialize PostgreSQL tag store.

        Args:
            table_name: Optional table name override
            schema: Optional schema name override
        """
        self.table_name = table_name or os.getenv("POSTGRES_TAGS_TABLE", "fc_tags")
        self.schema = schema or os.getenv("POSTGRES_SCHEMA", "namecheck")
        self._ensure_schema_and_table_exist()
        logger.info(f"PostgreSQLTagStore initialized with schema.table: {self.schema}.{self.table_name}")

    def _get_qualified_table_name(self):
        """Get the schema-qualified table name as SQL identifier."""
        return sql.Identifier(self.schema, self.table_name)

    def _ensure_schema_and_table_exist(self):
        """Ensure the schema and tags table exist with proper schema."""
        try:
            with _postgres_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Create schema if it doesn't exist (only if not 'public')
                    if self.schema != "public":
                        create_schema_query = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                            sql.Identifier(self.schema)
                        )
                        cursor.execute(create_schema_query)
                        logger.info(f"Schema '{self.schema}' created or already exists")

                    # Check if table exists and get column information
                    check_table_query = sql.SQL("""
                        SELECT column_name FROM information_schema.columns 
                        WHERE table_schema = %s AND table_name = %s
                    """)
                    cursor.execute(check_table_query, (self.schema, self.table_name))

                    # Create table if it doesn't exist
                    create_table_query = sql.SQL("""
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
                    """).format(self._get_qualified_table_name())

                    cursor.execute(create_table_query)

                    # Create indexes for better performance
                    index_queries = [
                        sql.SQL(
                            "CREATE INDEX IF NOT EXISTS {} ON {} (customer_id, company_name, lang)"
                        ).format(
                            sql.Identifier(f"{self.schema}_{self.table_name}_customer_company_lang_idx"),
                            self._get_qualified_table_name(),
                        ),
                        sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (url)").format(
                            sql.Identifier(f"{self.schema}_{self.table_name}_url_idx"),
                            self._get_qualified_table_name(),
                        ),
                        sql.SQL(
                            "CREATE INDEX IF NOT EXISTS {} ON {} (method, llm_name)"
                        ).format(
                            sql.Identifier(f"{self.schema}_{self.table_name}_method_llm_idx"),
                            self._get_qualified_table_name(),
                        ),
                        sql.SQL(
                            "CREATE INDEX IF NOT EXISTS {} ON {} (modified_date)"
                        ).format(
                            sql.Identifier(f"{self.schema}_{self.table_name}_modified_date_idx"),
                            self._get_qualified_table_name(),
                        ),
                    ]

                    for index_query in index_queries:
                        cursor.execute(index_query)

                    conn.commit()
                    logger.info(
                        f"PostgreSQL table '{self.schema}.{self.table_name}' ensured with proper schema and indexes"
                    )

        except Exception as e:
            logger.error(f"Error ensuring PostgreSQL table exists: {e}")
            raise

    def save_tags(
        self,
        tags: List[dict],
        company_name: str,
        lang: str,
        method: str,
        llm_name: str,
        days: int = 0,
        customer_id: str = None,
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

        Raises:
            Exception: If database operation fails
        """
        if not tags:
            logger.warning("Empty tags list provided to save_tags")
            return

        # Use default customer_id if not provided for backward compatibility
        if customer_id is None:
            customer_id = "default"
            
        logger.info(f"PostgreSQL save_tags called with customer_id: '{customer_id}', tags count: {len(tags)}")

        try:
            with _postgres_manager.get_connection() as conn:
                with conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                ) as cursor:
                    saved_count = 0
                    skipped_count = 0

                    for item in tags:
                        required_fields = ["url", "crime_type", "probability"]
                        if not all(field in item for field in required_fields):
                            logger.warning(
                                f"Skipping item with missing required fields: {item}"
                            )
                            continue

                        # Check if we should update based on days parameter
                        should_update = True
                        if days > 0:
                            # Check if record exists and its age
                            check_query = sql.SQL("""
                                SELECT modified_date FROM {} 
                                WHERE LOWER(company_name) = LOWER(%s) 
                                AND LOWER(lang) = LOWER(%s) 
                                AND url = %s 
                                AND method = %s 
                                AND llm_name = %s
                                AND customer_id = %s
                            """).format(self._get_qualified_table_name())

                            cursor.execute(
                                check_query,
                                (company_name, lang, item["url"], method, llm_name, customer_id),
                            )
                            existing_record = cursor.fetchone()

                            if existing_record:
                                # Calculate the age of the existing record
                                age_threshold = datetime.now() - timedelta(days=days)

                                # Only update if the record is older than the threshold
                                if existing_record["modified_date"] > age_threshold:
                                    should_update = False
                                    skipped_count += 1
                                    logger.info(
                                        f"Skipping update for {item['url']} (not older than {days} days)"
                                    )

                        if should_update:
                            # Use INSERT ... ON CONFLICT for upsert functionality
                            # Only update if values are actually different
                            upsert_query = sql.SQL("""
                                INSERT INTO {} (customer_id, company_name, lang, url, title, method, llm_name, crime_type, probability, description, modified_date)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (customer_id, company_name, lang, url, method, llm_name)
                                DO UPDATE SET
                                    title = EXCLUDED.title,
                                    crime_type = EXCLUDED.crime_type,
                                    probability = EXCLUDED.probability,
                                    description = EXCLUDED.description,
                                    modified_date = EXCLUDED.modified_date
                                WHERE 
                                    {}.title IS DISTINCT FROM EXCLUDED.title OR
                                    {}.crime_type IS DISTINCT FROM EXCLUDED.crime_type OR
                                    {}.probability IS DISTINCT FROM EXCLUDED.probability OR
                                    {}.description IS DISTINCT FROM EXCLUDED.description
                            """).format(
                                self._get_qualified_table_name(),
                                self._get_qualified_table_name(),
                                self._get_qualified_table_name(),
                                self._get_qualified_table_name(),
                                self._get_qualified_table_name(),
                            )

                            # Get description or default to "N/A" if missing
                            description = item.get("description", "N/A")

                            cursor.execute(
                                upsert_query,
                                (
                                    customer_id,
                                    company_name,
                                    lang,
                                    item["url"],
                                    item.get("title"),
                                    method,
                                    llm_name,
                                    item["crime_type"],
                                    item["probability"],
                                    description,
                                    datetime.now(),
                                ),
                            )
                            saved_count += 1

                    conn.commit()
                    logger.info(
                        f"Saved {saved_count} tags to PostgreSQL, skipped {skipped_count} (not older than {days} days)"
                    )

        except Exception as e:
            logger.error(f"Error saving tags to PostgreSQL: {e}")
            raise

    def close(self):
        """Close method for consistency with other stores."""
        # PostgreSQL connections are managed per-request, so no persistent connection to close
        logger.info(
            "PostgreSQL tag store close() called - connections are managed per-request"
        )


# Export the main classes for use in other modules
__all__ = ["PostgreSQLTagStore", "PostgreSQLConnectionManager", "_postgres_manager"]
