"""Database connection and query utilities for ShiftGuard.

This module provides a connection pool manager and context managers for
safe database operations with automatic transaction handling.
"""

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from src.config import settings

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Custom exception for database operations."""

    pass


class DatabasePool:
    """Manages a PostgreSQL connection pool.

    Provides thread-safe connection pooling for the application with
    automatic connection recycling and health checks.

    Attributes:
        _pool: The underlying psycopg2 connection pool.
    """

    _instance: Optional["DatabasePool"] = None
    _pool: Optional[pool.ThreadedConnectionPool] = None

    def __new__(cls) -> "DatabasePool":
        """Ensure singleton pattern for the database pool.

        Returns:
            The singleton DatabasePool instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(
        self,
        min_connections: int = 1,
        max_connections: int = 10,
    ) -> None:
        """Initialize the connection pool.

        Args:
            min_connections: Minimum connections to maintain in the pool.
            max_connections: Maximum connections allowed in the pool.

        Raises:
            DatabaseError: If pool initialization fails.
        """
        if self._pool is not None:
            logger.warning("Connection pool already initialized")
            return

        try:
            self._pool = pool.ThreadedConnectionPool(
                minconn=min_connections,
                maxconn=max_connections,
                dsn=settings.database_url,
            )
            logger.info(
                "Database pool initialized with %d-%d connections",
                min_connections,
                max_connections,
            )
        except psycopg2.Error as e:
            logger.error("Failed to initialize database pool: %s", e)
            raise DatabaseError(f"Pool initialization failed: {e}") from e

    def get_connection(self) -> Any:
        """Get a connection from the pool.

        Returns:
            A psycopg2 connection object.

        Raises:
            DatabaseError: If pool is not initialized or connection fails.
        """
        if self._pool is None:
            raise DatabaseError("Connection pool not initialized")

        try:
            return self._pool.getconn()
        except psycopg2.Error as e:
            logger.error("Failed to get connection from pool: %s", e)
            raise DatabaseError(f"Failed to get connection: {e}") from e

    def return_connection(self, conn: Any) -> None:
        """Return a connection to the pool.

        Args:
            conn: The connection to return.
        """
        if self._pool is not None:
            self._pool.putconn(conn)

    def close_all(self) -> None:
        """Close all connections in the pool."""
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            logger.info("All database connections closed")


# Global pool instance
db_pool = DatabasePool()


@contextmanager
def get_db_connection() -> Generator[Any, None, None]:
    """Context manager for database connections.

    Automatically handles connection acquisition and release,
    ensuring connections are returned to the pool.

    Yields:
        A psycopg2 connection object.

    Raises:
        DatabaseError: If connection operations fail.

    Example:
        >>> with get_db_connection() as conn:
        ...     with conn.cursor() as cur:
        ...         cur.execute("SELECT 1")
    """
    conn = None
    try:
        conn = db_pool.get_connection()
        yield conn
    finally:
        if conn is not None:
            db_pool.return_connection(conn)


@contextmanager
def get_db_cursor(
    commit: bool = True,
    dict_cursor: bool = True,
) -> Generator[Any, None, None]:
    """Context manager for database cursors with automatic transaction handling.

    Provides a cursor with automatic commit/rollback behavior and
    optional dictionary-style row access.

    Args:
        commit: Whether to commit the transaction on successful exit.
        dict_cursor: Whether to use RealDictCursor for dict-style row access.

    Yields:
        A psycopg2 cursor object.

    Raises:
        DatabaseError: If cursor operations fail.

    Example:
        >>> with get_db_cursor() as cur:
        ...     cur.execute("SELECT * FROM employees WHERE id = %s", (emp_id,))
        ...     employee = cur.fetchone()
    """
    with get_db_connection() as conn:
        cursor_factory = RealDictCursor if dict_cursor else None
        cursor = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Database operation failed, rolling back: %s", e)
            raise
        finally:
            cursor.close()


def init_db() -> None:
    """Initialize the database connection pool.

    Should be called once at application startup.

    Raises:
        DatabaseError: If initialization fails.
    """
    db_pool.initialize()


def close_db() -> None:
    """Close all database connections.

    Should be called at application shutdown.
    """
    db_pool.close_all()
