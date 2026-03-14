"""
Shared logging configuration for the application.

This module provides centralized logging setup that should be called once
at application startup. All other modules should use logging.getLogger(__name__)
to obtain a logger instance.
"""

__all__ = ["setup_logging", "get_logger"]

import logging
from typing import Optional


def setup_logging(
    level: int = logging.INFO,
    log_format: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    date_format: str = '%Y-%m-%d %H:%M:%S',
    force: bool = False
) -> None:
    """
    Setup logging configuration for the entire application.

    This function should be called once at application startup.
    Using force=True ensures the configuration is applied even if
    basicConfig was already called.

    Args:
        level: Logging level (default: logging.INFO)
        log_format: Format string for log messages
        date_format: Format string for timestamps
        force: If True, force reconfiguration even if already configured
    """
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        force=force
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name, typically __name__ of the calling module

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)