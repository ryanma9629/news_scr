# =============================================================================
# IMPORTS AND DEPENDENCIES
# =============================================================================
import hashlib
import logging
import os
import secrets
import signal
import socket
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.documents import Document
from langchain_deepseek import ChatDeepSeek
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field, SecretStr
from starlette.middleware.sessions import SessionMiddleware

from .crawler import ApifyCrawler, CrawlerType
from .doc_store import MongoStore, _mongo_manager
from .postgres_store import PostgreSQLTagStore
from .query import QAWithContext
from .summarization import (
    SUMMARY_LEVELS,
    MapReduceSummarization,
    RefinementSummarization,
)
from .tagging import FCTagging
from .websearch import BingSearch, GoogleSerperNews

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize logger
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION AND CONSTANTS
# =============================================================================

# Default configuration
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_SESSION_TIMEOUT_HOURS = 2
DEFAULT_STORAGE_DAYS = 90

# Deployment configuration
VI_DEPLOY = os.getenv("VI_DEPLOY", "false").lower() == "true"

# Cookie and IFRAME configuration
ALLOW_IFRAME_EMBEDDING = os.getenv("ALLOW_IFRAME_EMBEDDING", "false").lower() == "true"
IFRAME_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("IFRAME_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", secrets.token_urlsafe(32))

# LLM configuration
SUPPORTED_LLM_DEPLOYMENTS = {
    "gpt-4.1": "gpt-4.1",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "deepseek-chat": "deepseek-chat",
    "qwen-max": "qwen-max",
    "qwen-plus": "qwen-plus",
    "qwen-turbo": "qwen-turbo",
}
DEFAULT_LLM_DEPLOYMENT = "gpt-4o"

# Language and search configuration
LANGUAGE_DISPLAY_MAP = {
    "zh-CN": "Simplified Chinese",
    "zh-HK": "Traditional Chinese(HK)",
    "zh-TW": "Traditional Chinese(TW)",
    "en-US": "English",
    "ja-JP": "Japanese",
}

SEARCH_SUFFIX_MAP = {
    "negative": {
        "zh-CN": "负面新闻",
        "zh-HK": "負面新聞",
        "zh-TW": "負面新聞",
        "en-US": "negative news",
        "ja-JP": "ネガティブニュース",
    },
    "crime": {
        "zh-CN": "犯罪嫌疑",
        "zh-HK": "犯罪嫌疑",
        "zh-TW": "犯罪嫌疑",
        "en-US": "criminal suspect",
        "ja-JP": "犯罪容疑",
    },
    "everything": {"zh-CN": "", "zh-HK": "", "zh-TW": "", "en-US": "", "ja-JP": ""},
}

# =============================================================================
# SESSION MANAGEMENT
# =============================================================================


class ThreadSafeSessionManager:
    """Thread-safe session management with automatic cleanup."""

    def __init__(self, timeout_hours: int = DEFAULT_SESSION_TIMEOUT_HOURS):
        self._sessions = {}
        self._lock = threading.RLock()
        self._timeout_hours = timeout_hours

    def create_session(self, session_id: str) -> dict:
        """Create a new session with thread-safe initialization."""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "created_at": datetime.now(),
                    "last_accessed": datetime.now(),
                    "search_results": [],
                    "web_contents": {},
                    "user_context": {},
                }
            return self._sessions[session_id]

    def get_session(self, session_id: str) -> dict:
        """Get session data with thread-safe access."""
        with self._lock:
            session = self._sessions.get(session_id, {})
            if session:
                session["last_accessed"] = datetime.now()
            return session.copy()

    def update_session(self, session_id: str, key: str, value) -> None:
        """Update session data with thread-safe access."""
        with self._lock:
            if session_id not in self._sessions:
                self.create_session(session_id)
            self._sessions[session_id][key] = value
            self._sessions[session_id]["last_accessed"] = datetime.now()

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count of removed sessions."""
        cutoff_time = datetime.now() - timedelta(hours=self._timeout_hours)
        with self._lock:
            expired_sessions = [
                session_id
                for session_id, session_data in self._sessions.items()
                if session_data.get("last_accessed", datetime.now()) < cutoff_time
            ]
            for session_id in expired_sessions:
                del self._sessions[session_id]
            return len(expired_sessions)

    def get_session_count(self) -> int:
        """Get total number of active sessions."""
        with self._lock:
            return len(self._sessions)

    def remove_session(self, session_id: str) -> bool:
        """Remove a specific session."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False


# Global session manager
session_manager = ThreadSafeSessionManager()

# =============================================================================
# PYDANTIC MODELS
# =============================================================================


# Request models
class SearchRequest(BaseModel):
    company_name: str = Field(..., description="Company name to search for")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code (e.g., 'zh-CN', 'en-US')")
    search_suffix: str = Field(..., description="Search topic suffix")
    search_engine: str = Field(..., description="Search engine ('Google' or 'Bing')")
    num_results: int = Field(
        ..., ge=1, le=100, description="Number of results to return"
    )
    llm_model: str = Field(..., description="LLM model to use")
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class CrawlerRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to crawl")
    crawler_type: CrawlerType = Field(
        default="playwright:adaptive", description="Crawler type"
    )
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code for storage")
    contents_save: bool = Field(default=True, description="Save contents to storage")
    contents_load: bool = Field(
        default=True, description="Load contents from storage if possible"
    )
    contents_save_days: int = Field(
        default=90, description="Only update contents older than this many days"
    )
    contents_load_days: int = Field(
        default=90, description="Only load contents no older than this many days"
    )
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class TaggingRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to tag")
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code for storage")
    tagging_method: str = Field(
        default="rag", description="Tagging method ('rag' or 'all')"
    )
    llm_model: str = Field(default="gpt-4o", description="LLM model to use")
    tags_save: bool = Field(default=True, description="Save tags to storage")
    tags_load: bool = Field(
        default=True, description="Load tags from storage if possible"
    )
    tags_save_days: int = Field(
        default=90, description="Only update tags older than this many days"
    )
    tags_load_days: int = Field(
        default=90, description="Only load tags no older than this many days"
    )
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class SummaryRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to summarize")
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code for storage")
    summary_method: str = Field(default="map-reduce", description="Summary method")
    llm_model: str = Field(default="gpt-4o", description="LLM model to use")
    summary_level: str = Field(default="moderate", description="Summary detail level")
    cluster_docs: bool = Field(
        default=True, description="Whether to cluster documents before summarization"
    )
    num_clusters: int = Field(
        default=2, description="Number of clusters for document clustering"
    )
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


class QARequest(BaseModel):
    question: str = Field(..., description="Question to ask")
    company_name: str = Field(..., description="Company name for context")
    customer_id: Optional[str] = Field(
        None, description="Customer identifier for multi-tenant support"
    )
    lang: str = Field(..., description="Language code")
    urls: List[str] = Field(..., description="URLs to use as context")
    llm_model: str = Field(default="gpt-4o-mini", description="LLM model to use")
    session_id: Optional[str] = Field(
        None, description="Session ID for data persistence"
    )


# Response models
class SearchResultResponse(BaseModel):
    url: str
    title: str


class CrawlerResultResponse(BaseModel):
    url: str
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None


class SearchResponse(BaseModel):
    success: bool
    results: List[SearchResultResponse]
    total_results: int
    message: str
    session_id: Optional[str] = None


class CrawlerResponse(BaseModel):
    success: bool
    results: List[CrawlerResultResponse]
    total_results: int
    message: str


class TaggingResultResponse(BaseModel):
    url: str
    success: bool
    crime_type: Optional[str] = None
    probability: Optional[str] = None
    error: Optional[str] = None


class TaggingResponse(BaseModel):
    success: bool
    results: List[TaggingResultResponse]
    total_results: int
    message: str


class SummaryResponse(BaseModel):
    success: bool
    summary: Optional[str] = None
    message: str


class QAResponse(BaseModel):
    success: bool
    question: Optional[str] = None
    answer: Optional[str] = None
    urls: Optional[List[str]] = None
    message: str


# =============================================================================
# UTILITY FUNCTIONS AND MANAGERS
# =============================================================================


class ContentManager:
    """Unified content loading and validation manager."""

    @staticmethod
    def get_from_session_with_validation(
        session_id: str, urls: List[str], operation_name: str
    ):
        """Get contents from session with comprehensive validation."""
        session_data = get_session_data(session_id)
        session_contents = session_data.get("web_contents", {})
        contents = []
        missing_urls = []

        for url in urls:
            if url in session_contents:
                contents.append({"url": url, "text": session_contents[url]})
            else:
                missing_urls.append(url)

        if not contents:
            return (
                [],
                missing_urls,
                f"Content not found for {operation_name}. Please get content first.",
            )
        return contents, missing_urls, None

    @staticmethod
    def load_with_fallback(
        mongo_store: MongoStore, urls: List[str], session_id: str, days: int = 0
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        """Load contents from storage with session fallback."""
        session_data = get_session_data(session_id)
        session_contents = session_data.get("web_contents", {})
        contents = []
        missing_urls = []

        for url in urls:
            if url in session_contents:
                contents.append({"url": url, "text": session_contents[url]})
            else:
                missing_urls.append(url)

        if missing_urls:
            try:
                fallback_contents = mongo_store.load_contents(missing_urls, days=days)
                contents.extend(fallback_contents)
                fallback_urls = {content["url"] for content in fallback_contents}
                missing_urls = [url for url in missing_urls if url not in fallback_urls]
            except Exception as e:
                logger.error(f"Error loading from MongoDB: {e}")

        return contents, missing_urls


class ValidationManager:
    """Unified validation manager for common request validations."""

    @staticmethod
    def validate_session_and_urls(
        session_id: Optional[str], urls: List[str], operation_name: str
    ):
        """Centralized validation for session ID and URLs."""
        if not session_id:
            return (
                False,
                f"Session is required. Please search for news and get content first, then try {operation_name} again.",
            )
        if not urls:
            return False, f"No URLs provided for {operation_name}"
        return True, ""

    @staticmethod
    def validate_llm_deployment(llm_model: str) -> str:
        """Validate and return the correct deployment name for the given LLM model."""
        if llm_model not in SUPPORTED_LLM_DEPLOYMENTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported LLM model: {llm_model}. Supported models: {list(SUPPORTED_LLM_DEPLOYMENTS.keys())}",
            )
        return SUPPORTED_LLM_DEPLOYMENTS[llm_model]


class StorageManager:
    """Unified storage operations manager."""

    @staticmethod
    def handle_operation(operation_func, operation_name: str, *args, **kwargs):
        """Generic handler for storage operations with error handling."""
        try:
            return operation_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error {operation_name}: {e}")
            return None


class ResponseManager:
    """Unified response creation manager."""

    @staticmethod
    def create_error_response(
        response_class, urls: List[str], error_message: str, **kwargs
    ):
        """Create standardized error responses."""
        if (
            hasattr(response_class, "model_fields")
            and "results" in response_class.model_fields
        ):
            # For responses with results (like TaggingResponse, CrawlerResponse)
            failed_results = []
            for url in urls:
                if response_class.__name__ == "TaggingResponse":
                    failed_results.append(
                        TaggingResultResponse(
                            url=url,
                            success=False,
                            error=error_message,
                            crime_type=None,
                            probability=None,
                        )
                    )
                elif response_class.__name__ == "CrawlerResponse":
                    failed_results.append(
                        CrawlerResultResponse(
                            url=url, success=False, error=error_message, content=None
                        )
                    )
            return response_class(
                success=False,
                results=failed_results,
                total_results=len(failed_results),
                message=error_message,
                **kwargs,
            )
        else:
            # For simple responses (like SummaryResponse, QAResponse)
            return response_class(success=False, message=error_message, **kwargs)


def require_session(strict: bool = True):
    """Decorator to validate session requirement and cleanup expired sessions."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            session_manager.cleanup_expired_sessions()
            request = None
            for arg in args:
                if hasattr(arg, "session_id"):
                    request = arg
                    break
            if strict and (not request or not request.session_id):
                raise HTTPException(status_code=400, detail="Session ID is required")
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def handle_api_errors(response_class):
    """Decorator to handle common API errors and responses."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException as he:
                # Re-raise HTTP exceptions
                raise he
            except Exception as e:
                logger.error(f"API error in {func.__name__}: {e}")
                # Extract request object to get URLs for error response
                request = None
                for arg in args:
                    if hasattr(arg, "urls"):
                        request = arg
                        break

                urls = getattr(request, "urls", []) if request else []
                return ResponseManager.create_error_response(
                    response_class, urls, f"System error: {e}"
                )

        return wrapper

    return decorator


# Essential utility functions
def generate_session_id(ip: str, user_agent: str = "") -> str:
    """Generate session ID based on client info and timestamp."""
    timestamp = str(datetime.now().timestamp())
    content = f"{ip}_{user_agent}_{timestamp}"
    return hashlib.md5(content.encode()).hexdigest()


def get_session_data(session_id: str) -> dict:
    """Get session data for given session ID."""
    return session_manager.get_session(session_id)


def update_session_data(session_id: str, key: str, value):
    """Update session data for given session ID and key."""
    session_manager.update_session(session_id, key, value)


def set_session_cookie(
    response: Response, session_id: str, max_age: int = SESSION_MAX_AGE
):
    """Set session cookie with proper SameSite and Secure policies."""
    cookie_kwargs = {
        "key": "session_id",
        "value": session_id,
        "max_age": max_age,
        "httponly": True,
        "samesite": COOKIE_SAMESITE,
        "secure": COOKIE_SECURE,
    }
    if COOKIE_DOMAIN:
        cookie_kwargs["domain"] = COOKIE_DOMAIN
    response.set_cookie(**cookie_kwargs)
    return response


def create_json_response_with_cookies(
    data: dict, session_id: Optional[str] = None
) -> JSONResponse:
    """Create a JSON response with proper cookie settings."""
    response = JSONResponse(content=data)
    if session_id:
        set_session_cookie(response, session_id)
    return response


# Essential utility functions (restored)
def init_llm_and_embeddings(deployment: str = "gpt-4o", model: str = "gpt-4o"):
    """Initialize LLM and embeddings with common configuration."""
    if deployment not in SUPPORTED_LLM_DEPLOYMENTS:
        raise ValueError(f"Unsupported LLM deployment: {deployment}")

    if deployment.startswith("deepseek"):
        llm = ChatDeepSeek(model=deployment, temperature=0)
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    elif deployment.startswith("qwen"):
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY environment variable is required for Qwen models"
            )
        llm = ChatTongyi(model=deployment, api_key=SecretStr(api_key))
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    else:
        azure_deployment = SUPPORTED_LLM_DEPLOYMENTS[deployment]
        llm = AzureChatOpenAI(
            azure_deployment=azure_deployment, model=model, temperature=0
        )
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")

    return llm, emb


def get_search_keywords(company_name: str, search_suffix: str, lang: str) -> str:
    """Generate search keywords based on company name, suffix, and language."""
    base_keywords = company_name
    if search_suffix != "everything":
        suffix_mapping = SEARCH_SUFFIX_MAP.get(search_suffix, {})
        suffix_text = suffix_mapping.get(lang, suffix_mapping.get("en-US", ""))
        if suffix_text:
            base_keywords += f" {suffix_text}"
    return base_keywords


def get_search_engine(engine_name: str, lang: str):
    """Get search engine instance based on engine name and language."""
    display_lang = LANGUAGE_DISPLAY_MAP.get(lang, "English")
    if engine_name.lower() == "google":
        return GoogleSerperNews(lang=display_lang)
    elif engine_name.lower() == "bing":
        return BingSearch(lang=display_lang)
    return None


# Use manager functions but provide backward compatibility
def validate_llm_deployment(llm_model: str) -> str:
    """Validate and return the correct deployment name for the given LLM model."""
    return ValidationManager.validate_llm_deployment(llm_model)


def validate_session_and_urls(
    session_id: Optional[str], urls: List[str], operation_name: str
):
    """Centralized validation for session ID and URLs."""
    return ValidationManager.validate_session_and_urls(session_id, urls, operation_name)


def get_contents_from_session_with_validation(
    session_id: str, urls: List[str], operation_name: str
):
    """Get contents from session with comprehensive validation."""
    return ContentManager.get_from_session_with_validation(
        session_id, urls, operation_name
    )


def load_from_storage_with_fallback(
    mongo_store: MongoStore, urls: List[str], session_id: str, days: int = 0
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Load contents from storage with session fallback."""
    return ContentManager.load_with_fallback(mongo_store, urls, session_id, days)


def handle_storage_operation(operation_func, operation_name: str, *args, **kwargs):
    """Generic handler for storage operations with error handling."""
    return StorageManager.handle_operation(
        operation_func, operation_name, *args, **kwargs
    )


def check_port_availability(port: int) -> bool:
    """Check if a port is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def get_fallback_port(preferred_port: int) -> int:
    """Get a fallback port if the preferred one is not available."""
    for port in range(preferred_port, preferred_port + 100):
        if check_port_availability(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# =============================================================================
# APP CONFIGURATION AND MIDDLEWARE
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    session_manager.cleanup_expired_sessions()
    yield
    try:
        _mongo_manager.close()
    except Exception as e:
        logger.error(f"Error closing MongoDB connections: {e}")


def get_cors_origins():
    """Get CORS origins configuration."""
    cors_origins = [
        "https://localhost:8280",
        "https://127.0.0.1:8280",
        "http://localhost:8280",
        "http://127.0.0.1:8280",
        "https://localhost",
        "https://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1",
        "http://sasserver.demo.sas.com",
        "https://sasserver.demo.sas.com",
        "http://sasserver",
        "https://sasserver",
    ]
    if ALLOW_IFRAME_EMBEDDING and IFRAME_ALLOWED_ORIGINS:
        if "*" in IFRAME_ALLOWED_ORIGINS:
            cors_origins = ["*"]
        else:
            cors_origins.extend(IFRAME_ALLOWED_ORIGINS)
    return cors_origins


def setup_app_configuration():
    """Setup FastAPI app with middleware and static files."""
    app = FastAPI(title="News Search API", version="1.0.0", lifespan=lifespan)

    # Session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET_KEY,
        max_age=SESSION_MAX_AGE,
        same_site=COOKIE_SAMESITE.lower(),  # type: ignore
        https_only=COOKIE_SECURE,
        domain=COOKIE_DOMAIN if COOKIE_DOMAIN else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers including IFRAME and cookie policies."""
        response = await call_next(request)

        # IFRAME embedding headers
        if ALLOW_IFRAME_EMBEDDING:
            if "*" in IFRAME_ALLOWED_ORIGINS or not IFRAME_ALLOWED_ORIGINS:
                response.headers["X-Frame-Options"] = "ALLOWALL"
                response.headers["Content-Security-Policy"] = "frame-ancestors *"
            else:
                allowed_origins = " ".join(IFRAME_ALLOWED_ORIGINS)
                response.headers["Content-Security-Policy"] = (
                    f"frame-ancestors {allowed_origins}"
                )
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"

        # Additional security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response

    # Connection error handling middleware
    @app.middleware("http")
    async def connection_error_handler(request: Request, call_next):
        """Handle connection reset errors gracefully."""
        try:
            return await call_next(request)
        except ConnectionResetError:
            return Response(status_code=499, content="Client closed connection")
        except Exception as e:
            logger.error(f"Unexpected error handling request: {str(e)}")
            raise

    return app


def get_server_config():
    """Get server configuration from environment or defaults."""
    return {
        "host": "0.0.0.0",
        "port": 8280,
        "reload": os.getenv("RELOAD", "false").lower() == "true",
        "ssl_keyfile": os.getenv("SSL_KEYFILE"),
        "ssl_certfile": os.getenv("SSL_CERTFILE"),
        "timeout_keep_alive": int(os.getenv("TIMEOUT_KEEP_ALIVE", "5")),
        "timeout_graceful_shutdown": int(os.getenv("TIMEOUT_GRACEFUL_SHUTDOWN", "30")),
        "limit_concurrency": int(os.getenv("LIMIT_CONCURRENCY", "1000")),
        "limit_max_requests": int(os.getenv("LIMIT_MAX_REQUESTS", "10000")),
    }


# =============================================================================
# APPLICATION INITIALIZATION
# =============================================================================

app = setup_app_configuration()

# =============================================================================
# API ENDPOINTS
# =============================================================================


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve the index.html file with VI_DEPLOY configuration."""
    project_root = Path(__file__).parent.parent
    index_path = project_root / "static" / "index.html"
    if index_path.exists():
        html_content = index_path.read_text(encoding="utf-8")
        company_name = request.query_params.get("company_name", "")
        customer_id = request.query_params.get("customer_id", "")

        config_script = f"""
    <script>
        window.VI_DEPLOY = {str(VI_DEPLOY).lower()};
        window.URL_COMPANY_NAME = "{company_name}";
        window.URL_CUSTOMER_ID = "{customer_id}";
    </script>
</body>"""
        html_content = html_content.replace("</body>", config_script)
        return HTMLResponse(content=html_content)
    else:
        raise HTTPException(status_code=404, detail="index.html not found")


@app.post("/api/search", response_model=SearchResponse)
@require_session(strict=False)
@handle_api_errors(SearchResponse)
async def search_news(http_request: Request, request: SearchRequest):
    """Search for news articles based on company name and parameters."""
    try:
        client_ip = http_request.client.host if http_request.client else "unknown"
        user_agent = http_request.headers.get("user-agent", "")
        session_id = request.session_id or generate_session_id(client_ip, user_agent)

        try:
            validate_llm_deployment(request.llm_model)
        except HTTPException as e:
            return SearchResponse(
                success=False,
                results=[],
                total_results=0,
                message=str(e.detail),
                session_id=session_id,
            )

        keywords = get_search_keywords(
            request.company_name, request.search_suffix, request.lang
        )
        search_engine = get_search_engine(request.search_engine, request.lang)

        if not search_engine:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported search engine: {request.search_engine}",
            )

        # Perform search with better error handling
        try:
            results = search_engine.search(keywords, request.num_results)
        except Exception as search_error:
            # This is definitely an API/network error
            logger.error(f"Search engine error: {search_error}")
            return SearchResponse(
                success=False,
                results=[],
                total_results=0,
                message="Search failed due to network connection or API configuration issues. Please try again later or contact support.",
                session_id=session_id,
            )

        # Handle different result scenarios
        if results is None or len(results) == 0:
            # Either no results found or API returned None/empty list
            # Since we can't distinguish, assume it's "no results found" for better UX
            search_topic_map = {
                "negative": "negative news",
                "crime": "criminal suspect news",
                "everything": "news articles",
            }
            search_topic = search_topic_map.get(request.search_suffix, "news articles")

            return SearchResponse(
                success=True,
                results=[],
                total_results=0,
                message=f"No {search_topic} found for '{request.company_name}'. Try using different search terms, changing the search topic, or checking the spelling.",
                session_id=session_id,
            )

        search_results = [
            SearchResultResponse(url=result["url"], title=result["title"])
            for result in results
        ]

        # Store search results and user context in session
        update_session_data(
            session_id,
            "search_results",
            [{"url": result["url"], "title": result["title"]} for result in results],
        )
        update_session_data(
            session_id,
            "user_context",
            {
                "company_name": request.company_name,
                "lang": request.lang,
                "search_params": {
                    "search_suffix": request.search_suffix,
                    "search_engine": request.search_engine,
                    "num_results": request.num_results,
                    "llm_model": request.llm_model,
                },
            },
        )

        response_data = {
            "success": True,
            "results": [
                {"url": result.url, "title": result.title} for result in search_results
            ],
            "total_results": len(search_results),
            "message": f"Successfully found {len(search_results)} news articles",
            "session_id": session_id,
        }
        return create_json_response_with_cookies(response_data, session_id)

    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return SearchResponse(
            success=False,
            results=[],
            total_results=0,
            message=f"Search error: {str(e)}",
            session_id=request.session_id,
        )


@app.post("/api/crawler", response_model=CrawlerResponse)
@require_session(strict=False)
@handle_api_errors(CrawlerResponse)
async def crawl_news_content(request: CrawlerRequest):
    """Crawl content from news URLs using ApifyCrawler with storage and session support."""
    try:
        session_id = request.session_id
        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "crawling"
        )
        if not is_valid:
            return CrawlerResponse(
                success=False,
                results=[],
                total_results=0,
                message=validation_error or "Validation failed",
            )

        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)
        results = []
        contents_from_db = []

        # Load from storage if enabled
        if request.contents_load:
            contents_from_db = (
                handle_storage_operation(
                    mongo_store.load_contents,
                    "loaded contents from MongoDB",
                    request.urls,
                    days=request.contents_load_days,
                )
                or []
            )

            stored_urls = {content["url"] for content in contents_from_db}
            for content in contents_from_db:
                results.append(
                    CrawlerResultResponse(
                        url=content["url"],
                        success=True,
                        content=content["text"],
                        error=None,
                    )
                )
            urls_to_crawl = [url for url in request.urls if url not in stored_urls]
        else:
            urls_to_crawl = request.urls

        # Crawl remaining URLs
        crawled_contents = []
        if urls_to_crawl:
            try:
                # Use Apify crawler only
                crawler = ApifyCrawler()
                documents = await crawler.get(
                    urls_to_crawl, crawler_type=request.crawler_type
                )

                url_to_doc = {
                    doc.metadata.get("source", ""): doc
                    for doc in documents
                    if doc.metadata.get("source")
                }

                for url in urls_to_crawl:
                    if url in url_to_doc and url_to_doc[url].page_content.strip():
                        content = url_to_doc[url].page_content
                        results.append(
                            CrawlerResultResponse(
                                url=url, success=True, content=content, error=None
                            )
                        )
                        crawled_contents.append({"url": url, "text": content})
                    else:
                        error_msg = (
                            "Content is empty"
                            if url in url_to_doc
                            else "Content not found for this URL"
                        )
                        results.append(
                            CrawlerResultResponse(
                                url=url, success=False, content=None, error=error_msg
                            )
                        )
            except Exception as crawler_error:
                logger.error(f"Crawler execution failed: {crawler_error}")
                for url in urls_to_crawl:
                    results.append(
                        CrawlerResultResponse(
                            url=url,
                            success=False,
                            content=None,
                            error=f"Crawling failed: {crawler_error}",
                        )
                    )

        # Save to storage and session
        if request.contents_save and crawled_contents:
            handle_storage_operation(
                mongo_store.save_contents,
                "saved contents to MongoDB",
                crawled_contents,
                days=request.contents_save_days,
            )

        all_contents = {content["url"]: content["text"] for content in contents_from_db}
        all_contents.update(
            {r.url: r.content for r in results if r.success and r.content}
        )

        if session_id:
            update_session_data(session_id, "web_contents", all_contents)

        success_count = sum(1 for r in results if r.success)
        return CrawlerResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"Crawling completed: {success_count} successful, {len(results) - success_count} failed",
        )

    except Exception as e:
        logger.error(f"Crawler error: {e}")
        failed_results = [
            CrawlerResultResponse(
                url=url, success=False, error=f"System error: {e}", content=None
            )
            for url in request.urls
        ]
        return CrawlerResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"System error: {e}",
        )


@app.post("/api/tagging", response_model=TaggingResponse)
@require_session(strict=False)
@handle_api_errors(TaggingResponse)
async def tag_news_content(request: TaggingRequest):
    """Perform FC Tagging on news content with storage and session support."""
    try:
        session_id = request.session_id

        try:
            deployment = validate_llm_deployment(request.llm_model)
        except HTTPException as e:
            return TaggingResponse(
                success=False, results=[], total_results=0, message=str(e.detail)
            )

        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "tagging"
        )
        if not is_valid:
            return TaggingResponse(
                success=False,
                results=[],
                total_results=0,
                message=validation_error or "Validation failed",
            )

        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)
        results = []

        # Load existing tags from storage
        tags_from_db = []
        if request.tags_load:
            tags_from_db = (
                handle_storage_operation(
                    mongo_store.load_tags,
                    "loaded tags from MongoDB",
                    request.urls,
                    method=request.tagging_method,
                    llm_name=request.llm_model,
                    days=request.tags_load_days,
                )
                or []
            )

            stored_urls = {tag["url"] for tag in tags_from_db}
            for tag in tags_from_db:
                results.append(
                    TaggingResultResponse(
                        url=tag["url"],
                        success=True,
                        crime_type=tag.get("crime_type"),
                        probability=tag.get("probability"),
                        error=None,
                    )
                )
            urls_to_tag = [url for url in request.urls if url not in stored_urls]
        else:
            urls_to_tag = request.urls

        # Tag remaining URLs
        if urls_to_tag:
            contents_to_tag, urls_without_content = load_from_storage_with_fallback(
                mongo_store, urls_to_tag, session_id or ""
            )

            for url in urls_without_content:
                results.append(
                    TaggingResultResponse(
                        url=url,
                        success=False,
                        crime_type=None,
                        probability=None,
                        error="Content not found for this URL, please get content first",
                    )
                )

            if contents_to_tag:
                llm, emb = init_llm_and_embeddings(deployment, request.llm_model)
                fc_tagging = FCTagging(llm, emb)
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
                )

                tagged_results = []
                for content in contents_to_tag:
                    url, text = content["url"], content["text"]
                    try:
                        docs = text_splitter.split_documents(
                            [Document(page_content=text)]
                        )
                        tag_result = (
                            await fc_tagging.tagging_rag(docs)
                            if request.tagging_method == "rag"
                            else await fc_tagging.tagging_combine(docs)
                        )

                        results.append(
                            TaggingResultResponse(
                                url=url,
                                success=True,
                                crime_type=tag_result.get("crime_type"),
                                probability=tag_result.get("probability"),
                                error=None,
                            )
                        )
                        tagged_results.append(
                            {
                                "url": url,
                                "crime_type": tag_result.get("crime_type"),
                                "probability": tag_result.get("probability"),
                                "method": request.tagging_method,
                            }
                        )
                    except Exception as tag_error:
                        results.append(
                            TaggingResultResponse(
                                url=url,
                                success=False,
                                crime_type=None,
                                probability=None,
                                error=f"Tagging failed: {tag_error}",
                            )
                        )

                if tagged_results and request.tags_save:
                    handle_storage_operation(
                        mongo_store.save_tags,
                        "saved tags to MongoDB",
                        tagged_results,
                        method=request.tagging_method,
                        llm_name=request.llm_model,
                        days=request.tags_save_days,
                    )

        # Save ALL results to PostgreSQL when VI_DEPLOY is enabled
        if VI_DEPLOY:
            # Get URL to title mapping from session
            url_title_mapping = get_url_title_mapping(session_id or "")

            all_results_for_postgres = []
            for tag in tags_from_db:
                tag_with_title = {
                    "url": tag["url"],
                    "title": url_title_mapping.get(tag["url"]),
                    "crime_type": tag.get("crime_type"),
                    "probability": tag.get("probability"),
                    "method": request.tagging_method,
                }
                all_results_for_postgres.append(tag_with_title)

            if "tagged_results" in locals():
                for tag in tagged_results:
                    tag_with_title = {
                        "url": tag["url"],
                        "title": url_title_mapping.get(tag["url"]),
                        "crime_type": tag.get("crime_type"),
                        "probability": tag.get("probability"),
                        "method": tag["method"],
                    }
                    all_results_for_postgres.append(tag_with_title)

            if all_results_for_postgres:
                try:
                    postgres_store = PostgreSQLTagStore()

                    effective_customer_id = (
                        request.customer_id if request.customer_id else "default"
                    )

                    postgres_store.save_tags(
                        all_results_for_postgres,
                        company_name=request.company_name,
                        lang=request.lang,
                        method=request.tagging_method,
                        llm_name=request.llm_model,
                        days=request.tags_save_days,
                        customer_id=effective_customer_id,
                    )
                except Exception as postgres_error:
                    logger.error(f"Failed to save tags to PostgreSQL: {postgres_error}")

        success_count = sum(1 for r in results if r.success)
        return TaggingResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"Tagging completed: {success_count} successful, {len(results) - success_count} failed",
        )

    except Exception as e:
        logger.error(f"Tagging error: {e}")
        failed_results = [
            TaggingResultResponse(
                url=url,
                success=False,
                error=f"System error: {e}",
                crime_type=None,
                probability=None,
            )
            for url in request.urls
        ]
        return TaggingResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"System error: {e}",
        )


@app.post("/api/summary", response_model=SummaryResponse)
@require_session(strict=False)
@handle_api_errors(SummaryResponse)
async def summarize_news_content(request: SummaryRequest):
    """Perform summarization on news content from session."""
    try:
        session_id = request.session_id

        try:
            deployment = validate_llm_deployment(request.llm_model)
        except HTTPException as e:
            return SummaryResponse(success=False, message=str(e.detail), summary=None)

        valid_levels = list(SUMMARY_LEVELS.keys())
        if request.summary_level not in valid_levels:
            return SummaryResponse(
                success=False,
                message=f"Invalid summary level '{request.summary_level}'. Valid options: {', '.join(valid_levels)}",
                summary=None,
            )

        if not session_id:
            return SummaryResponse(
                success=False,
                message="Session is required. Please search for news and get content first, then try summarization again.",
                summary=None,
            )

        if not request.urls:
            return SummaryResponse(
                success=False,
                message="No URLs provided for summarization",
                summary=None,
            )

        contents, missing_urls, error_msg = get_contents_from_session_with_validation(
            session_id, request.urls, "summarization"
        )
        if error_msg:
            return SummaryResponse(success=False, message=error_msg, summary=None)

        try:
            llm, emb = init_llm_and_embeddings(deployment, request.llm_model)
            docs = [
                Document(page_content=content["text"], metadata={"url": content["url"]})
                for content in contents
                if content.get("text")
            ]
            num_clusters = request.num_clusters if request.cluster_docs else 0

            if request.summary_method == "map-reduce":
                summarizer = MapReduceSummarization(llm, emb)
            else:
                summarizer = RefinementSummarization(llm, emb)

            summary = await summarizer.summarize(
                docs=docs,
                lang=request.lang,
                summary_level=request.summary_level,
                num_cluster=num_clusters,
            )
            return SummaryResponse(
                success=True,
                message=f"Summary generated successfully, processed {len(contents)} articles",
                summary=summary,
            )

        except Exception as summarization_error:
            logger.error(f"Summarization execution failed: {summarization_error}")
            return SummaryResponse(
                success=False,
                message=f"Summary generation failed: {summarization_error}",
                summary=None,
            )

    except Exception as e:
        logger.error(f"Summary error: {e}")
        return SummaryResponse(
            success=False, message=f"System error: {e}", summary=None
        )


@app.post("/api/qa", response_model=QAResponse)
@require_session(strict=False)
@handle_api_errors(QAResponse)
async def qa_endpoint(request: QARequest):
    """Process QA request with context from session."""
    try:
        session_id = request.session_id

        try:
            deployment = validate_llm_deployment(request.llm_model)
        except HTTPException as e:
            return QAResponse(
                success=False,
                message=str(e.detail),
                question=request.question,
                answer=None,
                urls=[],
            )

        is_valid, validation_error = validate_session_and_urls(
            session_id, request.urls, "Q&A"
        )
        if not is_valid:
            return QAResponse(
                success=False,
                message=validation_error or "Validation failed",
                question=request.question,
                answer=None,
                urls=[],
            )

        contents, missing_urls, error_msg = get_contents_from_session_with_validation(
            session_id or "", request.urls, "Q&A"
        )
        if error_msg:
            return QAResponse(
                success=False,
                message=error_msg,
                question=request.question,
                answer=None,
                urls=[],
            )

        llm, embeddings = init_llm_and_embeddings(deployment, request.llm_model)
        documents = [
            Document(page_content=content["text"], metadata={"url": content["url"]})
            for content in contents
            if content.get("text")
        ]

        if not documents:
            return QAResponse(
                success=False,
                message="No valid document content found for answering the question",
                question=request.question,
                answer=None,
                urls=[],
            )

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
        )
        split_docs = text_splitter.split_documents(documents)
        qa_system = QAWithContext(llm=llm, emb=embeddings)
        result = await qa_system.query(
            query=request.question, lang=request.lang, docs=split_docs
        )

        return QAResponse(
            success=True,
            message="Q&A processing successful",
            question=result.get("question", request.question),
            answer=result.get("answer"),
            urls=result.get("urls", []),
        )

    except Exception as e:
        logger.error(f"Error in QA processing: {str(e)}")
        return QAResponse(
            success=False,
            message=f"Q&A processing failed: {str(e)}",
            question=request.question,
            answer=None,
            urls=[],
        )


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "Adverse News Screening API is running."}


# =============================================================================
# STATIC FILES AND MAIN EXECUTION
# =============================================================================

# Mount static files
project_root = Path(__file__).parent.parent
static_dir = project_root / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def get_url_title_mapping(session_id: str) -> dict:
    """Get URL to title mapping from session search results."""
    session_data = get_session_data(session_id)
    search_results = session_data.get("search_results", [])
    return {
        result["url"]: result["title"]
        for result in search_results
        if "url" in result and "title" in result
    }


if __name__ == "__main__":

    def signal_handler(signum, frame):
        """Handle graceful shutdown on SIGINT/SIGTERM."""
        try:
            session_manager.cleanup_expired_sessions()
            _mongo_manager.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    config = get_server_config()
    preferred_port = config["port"]
    if not check_port_availability(preferred_port):
        config["port"] = get_fallback_port(preferred_port)

    run_args = {
        "app": "app.main:app",
        "host": config["host"],
        "port": config["port"],
        "reload": config["reload"],
        "timeout_keep_alive": config.get("timeout_keep_alive", 5),
        "timeout_graceful_shutdown": config.get("timeout_graceful_shutdown", 30),
        "limit_concurrency": config.get("limit_concurrency", 1000),
        "limit_max_requests": config.get("limit_max_requests", 10000),
        "access_log": config.get("reload", False),
    }

    # SSL configuration
    ssl_keyfile = config.get("ssl_keyfile")
    ssl_certfile = config.get("ssl_certfile")
    project_root = Path(__file__).parent.parent
    default_ssl_dir = project_root / "config" / "ssl"

    if ssl_keyfile and not os.path.isabs(ssl_keyfile):
        ssl_keyfile = str(default_ssl_dir / ssl_keyfile)
    elif not ssl_keyfile and (default_ssl_dir / "key.pem").exists():
        ssl_keyfile = str(default_ssl_dir / "key.pem")

    if ssl_certfile and not os.path.isabs(ssl_certfile):
        ssl_certfile = str(default_ssl_dir / ssl_certfile)
    elif not ssl_certfile and (default_ssl_dir / "cert.pem").exists():
        ssl_certfile = str(default_ssl_dir / "cert.pem")

    if (
        ssl_keyfile
        and ssl_certfile
        and os.path.exists(ssl_keyfile)
        and os.path.exists(ssl_certfile)
    ):
        run_args["ssl_keyfile"] = ssl_keyfile
        run_args["ssl_certfile"] = ssl_certfile
        logger.info(
            f"Starting HTTPS server on https://{config['host']}:{config['port']}"
        )
    else:
        logger.info(f"Starting HTTP server on http://{config['host']}:{config['port']}")

    uvicorn.run(**run_args)
