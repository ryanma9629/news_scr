import hashlib
import logging
import os
import signal
import socket
import threading
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.documents import Document
from langchain_deepseek import ChatDeepSeek
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field, SecretStr

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not available, use system environment variables

from .crawler import ApifyCrawler, CrawlerType
from .docstore import MongoStore, _mongo_manager
from .postgres_store import PostgreSQLTagStore
from .query import QAWithContext
from .summarization import (
    SUMMARY_LEVELS,
    MapReduceSummarization,
    RefinementSummarization,
)
from .tagging import FCTagging
from .websearch import BingSearch, GoogleSerperNews

# Configuration constants
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_SESSION_TIMEOUT_HOURS = 2
DEFAULT_STORAGE_DAYS = 90

# Deployment configuration
VI_DEPLOY = (
    os.getenv("VI_DEPLOY", "false").lower() == "true"
)  # Set to True for VI deployment mode

# Cookie and IFRAME configuration
ALLOW_IFRAME_EMBEDDING = os.getenv("ALLOW_IFRAME_EMBEDDING", "false").lower() == "true"
IFRAME_ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("IFRAME_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")  # None, Lax, Strict
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24 hours
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", secrets.token_urlsafe(32))

# Supported LLM deployments mapping
SUPPORTED_LLM_DEPLOYMENTS = {
    "gpt-4.1": "gpt-4.1",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "deepseek-chat": "deepseek-chat",
    "qwen-max": "qwen-max",
    "qwen-plus": "qwen-plus",
    "qwen-turbo": "qwen-turbo",
}

# Default LLM configuration
DEFAULT_LLM_DEPLOYMENT = "gpt-4o"

# Language mappings and search configurations
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

# Configure logging - INFO level for debugging SSL issues
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Log VI_DEPLOY status for debugging
logger.info(f"VI_DEPLOY mode: {VI_DEPLOY} (from env: {os.getenv('VI_DEPLOY', 'not_set')})")

# Suppress noisy asyncio connection reset errors on Windows
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class ThreadSafeSessionManager:
    """Thread-safe session management with automatic cleanup."""

    def __init__(self, timeout_hours: int = DEFAULT_SESSION_TIMEOUT_HOURS):
        self._sessions = {}
        self._lock = threading.RLock()  # Re-entrant lock for nested operations
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
            return session.copy()  # Return copy to prevent external modification

    def update_session(self, session_id: str, key: str, value) -> None:
        """Update session data with thread-safe access."""
        with self._lock:
            # Ensure session exists
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


# Global thread-safe session manager
session_manager = ThreadSafeSessionManager()


# Common utility functions
def require_session(strict: bool = True):
    """Decorator to validate session requirement and cleanup expired sessions."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Cleanup expired sessions using thread-safe manager
            session_manager.cleanup_expired_sessions()

            # Extract request object from args
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


def init_llm_and_embeddings(deployment: str = "gpt-4o", model: str = "gpt-4o"):
    """Initialize LLM and embeddings with common configuration."""
    # Validate LLM deployment
    if deployment not in SUPPORTED_LLM_DEPLOYMENTS:
        raise ValueError(
            f"Unsupported LLM deployment: {deployment}. Supported deployments: {list(SUPPORTED_LLM_DEPLOYMENTS.keys())}"
        )

    # Initialize LLM based on provider
    if deployment.startswith("deepseek"):
        # DeepSeek models
        llm = ChatDeepSeek(model=deployment, temperature=0)
        # For DeepSeek, we'll still use Azure OpenAI embeddings as DeepSeek doesn't provide embeddings
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    elif deployment.startswith("qwen"):
        # Qwen (Tongyi) models - API key should be set via DASHSCOPE_API_KEY environment variable
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY environment variable is required for Qwen models"
            )
        llm = ChatTongyi(model=deployment, api_key=SecretStr(api_key))
        # For Qwen, we'll still use Azure OpenAI embeddings as Qwen doesn't provide embeddings
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    else:
        # Azure OpenAI models
        azure_deployment = SUPPORTED_LLM_DEPLOYMENTS[deployment]
        llm = AzureChatOpenAI(
            azure_deployment=azure_deployment, model=model, temperature=0
        )
        emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")

    return llm, emb


def validate_llm_deployment(llm_model: str) -> str:
    """Validate and return the correct deployment name for the given LLM model."""
    if llm_model not in SUPPORTED_LLM_DEPLOYMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported LLM model: {llm_model}. Currently supported models: {list(SUPPORTED_LLM_DEPLOYMENTS.keys())}",
        )
    return SUPPORTED_LLM_DEPLOYMENTS[llm_model]


def load_from_storage_with_fallback(
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

    # Try MongoDB for missing URLs
    if missing_urls:
        try:
            fallback_contents = mongo_store.load_contents(missing_urls, days=days)
            contents.extend(fallback_contents)

            # Update missing URLs list
            fallback_urls = {content["url"] for content in fallback_contents}
            missing_urls = [url for url in missing_urls if url not in fallback_urls]
        except Exception as e:
            logger.error(f"Error loading from MongoDB: {e}")

    return contents, missing_urls


def handle_storage_operation(operation_func, operation_name: str, *args, **kwargs):
    """Generic handler for storage operations with error handling."""
    try:
        result = operation_func(*args, **kwargs)
        return result
    except Exception as e:
        logger.error(f"Error {operation_name}: {e}")
        return None


def generate_session_id(ip: str, user_agent: str = "") -> str:
    """Generate session ID based on client info and timestamp."""
    timestamp = str(datetime.now().timestamp())
    content = f"{ip}_{user_agent}_{timestamp}"
    return hashlib.md5(content.encode()).hexdigest()


def get_session_data(session_id: str) -> dict:
    """Get session data for given session ID using thread-safe manager."""
    return session_manager.get_session(session_id)


def update_session_data(session_id: str, key: str, value):
    """Update session data for given session ID and key using thread-safe manager."""
    session_manager.update_session(session_id, key, value)


def set_session_cookie(response: Response, session_id: str, max_age: int = SESSION_MAX_AGE):
    """Set session cookie with proper SameSite and Secure policies."""
    cookie_kwargs = {
        "key": "session_id",
        "value": session_id,
        "max_age": max_age,
        "httponly": True,
        "samesite": COOKIE_SAMESITE,
        "secure": COOKIE_SECURE,
    }
    
    # Add domain if specified
    if COOKIE_DOMAIN:
        cookie_kwargs["domain"] = COOKIE_DOMAIN
    
    response.set_cookie(**cookie_kwargs)
    return response


def create_json_response_with_cookies(data: dict, session_id: str = None) -> JSONResponse:
    """Create a JSON response with proper cookie settings."""
    response = JSONResponse(content=data)
    
    if session_id:
        set_session_cookie(response, session_id)
    
    return response


# Consolidated validation and processing utilities
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


def get_contents_from_session_with_validation(
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

    if missing_urls:
        pass  # URLs not found in session

    if not contents:
        return (
            [],
            missing_urls,
            f"Content not found for {operation_name}. Please get content first.",
        )

    return contents, missing_urls, None


# Configuration utilities
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Cleanup any expired sessions
    session_manager.cleanup_expired_sessions()

    yield

    # Shutdown: Clean up resources
    try:
        _mongo_manager.close()
    except Exception as e:
        logger.error(f"Error closing MongoDB connections: {e}")


def setup_app_configuration():
    """Setup FastAPI app with middleware and static files."""
    app = FastAPI(title="News Search API", version="1.0.0", lifespan=lifespan)

    # Add session middleware with SameSite and Secure cookie settings
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET_KEY,
        max_age=SESSION_MAX_AGE,
        same_site=COOKIE_SAMESITE,
        https_only=COOKIE_SECURE,
        domain=COOKIE_DOMAIN if COOKIE_DOMAIN else None,
    )

    # CORS configuration based on IFRAME settings
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
    
    # Add IFRAME origins if embedding is enabled
    if ALLOW_IFRAME_EMBEDDING and IFRAME_ALLOWED_ORIGINS:
        if "*" in IFRAME_ALLOWED_ORIGINS:
            cors_origins = ["*"]
        else:
            cors_origins.extend(IFRAME_ALLOWED_ORIGINS)

    # Add CORS middleware with proper HTTPS support
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Security headers middleware with IFRAME and cookie support
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
                # More secure: specify allowed origins
                allowed_origins = " ".join(IFRAME_ALLOWED_ORIGINS)
                response.headers["Content-Security-Policy"] = f"frame-ancestors {allowed_origins}"
        else:
            # Default: prevent IFRAME embedding
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        
        # Additional security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # HSTS header for HTTPS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            
        return response

    # Add connection error handling middleware
    @app.middleware("http")
    async def connection_error_handler(request: Request, call_next):
        """Handle connection reset errors gracefully."""
        try:
            response = await call_next(request)
            return response
        except ConnectionResetError:
            # Return 499 status (Client Closed Request) - non-standard but commonly used
            return Response(status_code=499, content="Client closed connection")
        except Exception as e:
            # Log other unexpected errors at ERROR level
            logger.error(f"Unexpected error handling request: {str(e)}")
            raise

    return app


def get_server_config():
    """Get server configuration from environment or defaults."""

    config = {
        "host": "0.0.0.0",
        "port": 8280,
        "reload": os.getenv("RELOAD", "false").lower() == "true",
        "ssl_keyfile": os.getenv("SSL_KEYFILE"),
        "ssl_certfile": os.getenv("SSL_CERTFILE"),
        # Add connection handling configuration
        "timeout_keep_alive": int(os.getenv("TIMEOUT_KEEP_ALIVE", "5")),
        "timeout_graceful_shutdown": int(os.getenv("TIMEOUT_GRACEFUL_SHUTDOWN", "30")),
        "limit_concurrency": int(os.getenv("LIMIT_CONCURRENCY", "1000")),
        "limit_max_requests": int(os.getenv("LIMIT_MAX_REQUESTS", "10000")),
    }

    return config


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

    # If no port found in range, return a random available port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


app = setup_app_configuration()


# Request models
class SearchRequest(BaseModel):
    company_name: str = Field(..., description="Company name to search for")
    customer_id: Optional[str] = Field(None, description="Customer identifier for multi-tenant support")
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
        default="playwright:adaptive",
        description="Crawler type ('cheerio', 'playwright:chrome', 'playwright:firefox', 'playwright:adaptive')",
    )
    company_name: str = Field(..., description="Company name for storage")
    customer_id: Optional[str] = Field(None, description="Customer identifier for multi-tenant support")
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
    customer_id: Optional[str] = Field(None, description="Customer identifier for multi-tenant support")
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
    customer_id: Optional[str] = Field(None, description="Customer identifier for multi-tenant support")
    lang: str = Field(..., description="Language code for storage")
    summary_method: str = Field(
        default="map-reduce",
        description="Summary method ('map-reduce' or 'iterative-refinement')",
    )
    llm_model: str = Field(default="gpt-4o", description="LLM model to use")
    summary_level: str = Field(
        default="moderate",
        description="Summary detail level ('brief', 'moderate', 'detailed')",
    )
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
    customer_id: Optional[str] = Field(None, description="Customer identifier for multi-tenant support")
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
    else:
        return None


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve the index.html file with VI_DEPLOY configuration."""
    project_root = Path(__file__).parent.parent  # Go up from app/ to project root
    index_path = project_root / "static" / "index.html"
    if index_path.exists():
        html_content = index_path.read_text(encoding="utf-8")

        # Inject VI_DEPLOY configuration and company_name if provided
        company_name = request.query_params.get("company_name", "")
        customer_id = request.query_params.get("customer_id", "")
        
        # Debug logging for URL parameters
        logger.info(f"Root endpoint called with company_name: '{company_name}', customer_id: '{customer_id}', VI_DEPLOY: {VI_DEPLOY}")

        # Add JavaScript configuration at the end of the body
        config_script = f"""
    <script>
        // VI_DEPLOY configuration
        window.VI_DEPLOY = {str(VI_DEPLOY).lower()};
        window.URL_COMPANY_NAME = "{company_name}";
        window.URL_CUSTOMER_ID = "{customer_id}";
    </script>
</body>"""

        # Replace the closing body tag with our configuration
        html_content = html_content.replace("</body>", config_script)

        return HTMLResponse(content=html_content)
    else:
        raise HTTPException(status_code=404, detail="index.html not found")


@app.post("/api/search", response_model=SearchResponse)
@require_session(strict=False)
async def search_news(http_request: Request, request: SearchRequest):
    """
    Search for news articles based on company name and parameters.
    """
    try:
        # Generate session ID if not provided
        client_ip = http_request.client.host if http_request.client else "unknown"
        user_agent = http_request.headers.get("user-agent", "")
        session_id = request.session_id or generate_session_id(client_ip, user_agent)

        # Validate LLM model
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

        # Generate search keywords
        keywords = get_search_keywords(
            request.company_name, request.search_suffix, request.lang
        )

        # Get search engine instance
        search_engine = get_search_engine(request.search_engine, request.lang)
        if not search_engine:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported search engine: {request.search_engine}",
            )

        # Perform search
        results = search_engine.search(keywords, request.num_results)

        if results is None:
            return SearchResponse(
                success=False,
                results=[],
                total_results=0,
                message="Search failed, please check network connection or API configuration",
                session_id=session_id,
            )

        # Convert results to response format
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

        # Create response data
        response_data = {
            "success": True,
            "results": [{"url": result.url, "title": result.title} for result in search_results],
            "total_results": len(search_results),
            "message": f"Successfully found {len(search_results)} news articles",
            "session_id": session_id,
        }

        # Return response with cookies
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
async def crawl_news_content(request: CrawlerRequest):
    """Crawl content from news URLs using ApifyCrawler with storage and session support."""
    try:
        session_id = request.session_id

        # Validate session and URLs
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

        # Initialize MongoStore
        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)
        results = []
        contents_from_db = []

        # Step 1: Load from storage if enabled
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

            # Add stored contents to results
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

        # Step 2: Crawl remaining URLs
        crawled_contents = []
        if urls_to_crawl:
            crawler = ApifyCrawler()

            try:
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

        # Step 3: Save to storage and session
        if request.contents_save and crawled_contents:
            handle_storage_operation(
                mongo_store.save_contents,
                "saved contents to MongoDB",
                crawled_contents,
                days=request.contents_save_days,
            )

        # Store all contents in session
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
                url=url,
                success=False,
                error=f"System error: {e}",
                content=None,
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
async def tag_news_content(request: TaggingRequest):
    """Perform FC Tagging on news content with storage and session support."""
    try:
        session_id = request.session_id
        
        # Debug logging for customer_id
        logger.info(f"Tagging request received with customer_id: '{request.customer_id}' (type: {type(request.customer_id)}) (VI_DEPLOY: {VI_DEPLOY})")
        logger.info(f"Customer_id is None: {request.customer_id is None}")
        logger.info(f"Customer_id is empty string: {request.customer_id == ''}")
        logger.info(f"Customer_id is falsy: {not request.customer_id}")

        # Validate LLM model
        try:
            deployment = validate_llm_deployment(request.llm_model)
        except HTTPException as e:
            return TaggingResponse(
                success=False,
                results=[],
                total_results=0,
                message=str(e.detail),
            )

        # Validate session and URLs
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

        # Initialize MongoStore
        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)
        results = []

        # Step 1: Load existing tags from storage
        tags_from_db = []
        if request.tags_load:
            tags_from_db = (
                handle_storage_operation(
                    mongo_store.load_tags,
                    "loaded tags from MongoDB",
                    request.urls,
                    method=request.tagging_method,
                    llm_name=request.llm_model,  # Use the requested model
                    days=request.tags_load_days,
                )
                or []
            )

            # Add stored tags to results
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

        # Step 2: Tag remaining URLs
        if urls_to_tag:
            # Get contents with fallback
            contents_to_tag, urls_without_content = load_from_storage_with_fallback(
                mongo_store, urls_to_tag, session_id or ""
            )

            # Mark URLs without content as failed
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
                # Initialize tagging components with the validated LLM model
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

                        # Perform tagging based on method
                        if request.tagging_method == "rag":
                            tag_result = await fc_tagging.tagging_rag(docs)
                        else:  # "all" for Full-text
                            tag_result = await fc_tagging.tagging_combine(docs)

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

                # Save tagged results to MongoDB if enabled
                if tagged_results and request.tags_save:
                    handle_storage_operation(
                        mongo_store.save_tags,
                        "saved tags to MongoDB",
                        tagged_results,
                        method=request.tagging_method,
                        llm_name=request.llm_model,  # Use the actual model name
                        days=request.tags_save_days,
                    )

        # Step 3: Save ALL results to PostgreSQL when VI_DEPLOY is enabled
        if VI_DEPLOY:
            # Prepare all results for PostgreSQL saving
            all_results_for_postgres = []
            
            # Add results from MongoDB (tags_from_db)
            for tag in tags_from_db:
                all_results_for_postgres.append({
                    "url": tag["url"],
                    "crime_type": tag.get("crime_type"),
                    "probability": tag.get("probability"),
                    "method": request.tagging_method,
                })
            
            # Add newly tagged results
            if 'tagged_results' in locals():
                all_results_for_postgres.extend(tagged_results)
            
            # Save to PostgreSQL when VI_DEPLOY is enabled
            if all_results_for_postgres:
                try:
                    postgres_store = PostgreSQLTagStore()
                    # Import the manager to get connection details for logging
                    from .postgres_store import _postgres_manager
                    conn_params = _postgres_manager.get_connection_params()
                    logger.info(f"Connecting to PostgreSQL database '{conn_params['database']}' schema '{postgres_store.schema}' on {conn_params['host']}:{conn_params['port']}")
                    
                    # Debug log the customer_id being saved - handle empty strings properly
                    effective_customer_id = request.customer_id if request.customer_id else "default"
                    logger.info(f"Saving to PostgreSQL with customer_id: '{effective_customer_id}' (original: '{request.customer_id}', is_empty: {not request.customer_id})")
                    
                    postgres_store.save_tags(
                        all_results_for_postgres,
                        company_name=request.company_name,
                        lang=request.lang,
                        method=request.tagging_method,
                        llm_name=request.llm_model,
                        days=request.tags_save_days,
                        customer_id=effective_customer_id,
                    )
                    logger.info(f"Successfully saved {len(all_results_for_postgres)} tags to PostgreSQL schema '{postgres_store.schema}' table '{postgres_store.table_name}' (VI_DEPLOY enabled)")
                except Exception as postgres_error:
                    logger.error(f"Failed to save tags to PostgreSQL: {postgres_error}")
                    # Continue execution even if PostgreSQL save fails
        else:
            logger.debug("PostgreSQL saving skipped (VI_DEPLOY is disabled)")

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
async def summarize_news_content(request: SummaryRequest):
    """
    Perform summarization on news content from session.
    """
    try:
        session_id = request.session_id

        # Validate LLM model
        try:
            deployment = validate_llm_deployment(request.llm_model)
        except HTTPException as e:
            return SummaryResponse(success=False, message=str(e.detail), summary=None)

        # Validate summary level
        valid_levels = list(SUMMARY_LEVELS.keys())
        if request.summary_level not in valid_levels:
            return SummaryResponse(
                success=False,
                message=f"Invalid summary level '{request.summary_level}'. Valid options: {', '.join(valid_levels)}",
                summary=None,
            )

        # Handle missing session ID
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

        # Get contents from session and validate
        contents, missing_urls, error_msg = get_contents_from_session_with_validation(
            session_id, request.urls, "summarization"
        )

        if error_msg:
            return SummaryResponse(success=False, message=error_msg, summary=None)

        try:
            # Initialize LLM and embeddings with the validated model
            llm, emb = init_llm_and_embeddings(deployment, request.llm_model)

            # Create documents from content
            docs = [
                Document(page_content=content["text"], metadata={"url": content["url"]})
                for content in contents
                if content.get("text")
            ]

            # Determine number of clusters
            num_clusters = request.num_clusters if request.cluster_docs else 0

            # Choose summarization method and perform summarization
            if request.summary_method == "map-reduce":
                summarizer = MapReduceSummarization(llm, emb)
            else:  # iterative-refinement
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
async def qa_endpoint(request: QARequest):
    """Process QA request with context from session."""
    try:
        session_id = request.session_id

        # Validate LLM model
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

        # Validate session and URLs
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

        # Get contents from session with validation (session_id guaranteed to be valid)
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

        # Initialize LLM and embeddings using the validated model
        llm, embeddings = init_llm_and_embeddings(deployment, request.llm_model)

        # Convert contents to documents and split
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

        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
        )
        split_docs = text_splitter.split_documents(documents)

        # Initialize QA system
        qa_system = QAWithContext(llm=llm, emb=embeddings)

        # Process the query
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


# Mount static files directory for CSS, JS, and HTML
project_root = Path(__file__).parent.parent  # Go up from app/ to project root
static_dir = project_root / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if __name__ == "__main__":
    # Setup graceful shutdown handling
    def signal_handler(signum, frame):
        """Handle graceful shutdown on SIGINT/SIGTERM."""
        try:
            # Cleanup sessions and connections
            session_manager.cleanup_expired_sessions()
            _mongo_manager.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            os._exit(0)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):  # Windows doesn't have SIGTERM
        signal.signal(signal.SIGTERM, signal_handler)

    # Get server configuration
    config = get_server_config()

    # Check if preferred port is available, get fallback if not
    preferred_port = config["port"]
    if not check_port_availability(preferred_port):
        fallback_port = get_fallback_port(preferred_port)
        config["port"] = fallback_port

    # Prepare uvicorn run arguments
    run_args = {
        "app": "app.main:app",
        "host": config["host"],
        "port": config["port"],
        "reload": config["reload"],
        # Add connection handling configuration
        "timeout_keep_alive": config.get("timeout_keep_alive", 5),
        "timeout_graceful_shutdown": config.get("timeout_graceful_shutdown", 30),
        "limit_concurrency": config.get("limit_concurrency", 1000),
        "limit_max_requests": config.get("limit_max_requests", 10000),
        # Suppress access logs in production to reduce noise
        "access_log": config.get(
            "reload", False
        ),  # Only show access logs in development
    }

    # Add SSL configuration if certificates are available
    ssl_keyfile = config.get("ssl_keyfile")
    ssl_certfile = config.get("ssl_certfile")

    # Check for default certificate files if not explicitly set
    # Use absolute paths based on the project root directory
    project_root = Path(__file__).parent.parent  # Go up from app/ to project root
    default_ssl_dir = project_root / "config" / "ssl"
    
    # If ssl_keyfile is a relative path, convert it to absolute
    if ssl_keyfile and not os.path.isabs(ssl_keyfile):
        ssl_keyfile = str(default_ssl_dir / ssl_keyfile)
    elif not ssl_keyfile and (default_ssl_dir / "key.pem").exists():
        ssl_keyfile = str(default_ssl_dir / "key.pem")
        
    # If ssl_certfile is a relative path, convert it to absolute  
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

    # Run the application
    uvicorn.run(**run_args)
