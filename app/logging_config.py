"""
Centralized logging configuration for the news screening application.

This module provides consistent logging setup across all application modules.
"""

import logging
import sys
from typing import Optional


class AppLogger:
    """
    Centralized logger configuration for consistent logging across the application.
    """
    
    _configured = False
    
    @classmethod
    def configure(cls, 
                  level: int = logging.INFO,
                  format_string: Optional[str] = None,
                  include_module_name: bool = True) -> None:
        """
        Configure application-wide logging settings.
        
        Args:
            level: Logging level (default: INFO)
            format_string: Custom format string (optional)
            include_module_name: Whether to include module names in logs
        """
        if cls._configured:
            return
            
        if format_string is None:
            if include_module_name:
                format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            else:
                format_string = "%(asctime)s - %(levelname)s - %(message)s"
        
        # Remove any existing handlers to avoid duplication
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            
        # Configure logging with consistent format
        logging.basicConfig(
            level=level,
            format=format_string,
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        # Suppress noisy third-party loggers
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        
        cls._configured = True
    
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """
        Get a logger instance with the given name.
        
        Args:
            name: Logger name (typically __name__)
            
        Returns:
            Configured logger instance
        """
        # Ensure logging is configured
        AppLogger.configure()
        return logging.getLogger(name)


# Convenience function for easy import
def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with consistent configuration.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger instance
    """
    return AppLogger.get_logger(name)