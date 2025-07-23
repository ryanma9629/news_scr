import logging
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from functools import wraps

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from crawler import ApifyCrawler  # Import ApifyCrawler
from docstore import MongoStore  # Import MongoStore for storage functionality
from query import QAWithContext  # Import QAWithContext for QA functionality
from summarization import MapReduceSummarization, RefinementSummarization  # Import summarization classes
from tagging import FCTagging  # Import FCTagging for tagging functionality
from websearch import BingSearch, GoogleSerperNews

# Configuration constants
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_SESSION_TIMEOUT_HOURS = 2
DEFAULT_STORAGE_DAYS = 90
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8280

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session storage
SESSION_STORE = {}
SESSION_TIMEOUT_HOURS = DEFAULT_SESSION_TIMEOUT_HOURS

# Common utility functions
def require_session(strict: bool = True):
    """Decorator to validate session requirement and cleanup expired sessions.
    
    Args:
        strict: If True, raises error when session_id is missing. 
                If False, allows missing session_id (for endpoints that can auto-generate).
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cleanup_expired_sessions()
            
            # Extract request object from args
            request = None
            for arg in args:
                if hasattr(arg, 'session_id'):
                    request = arg
                    break
            
            if strict and (not request or not request.session_id):
                raise HTTPException(status_code=400, detail="Session ID is required")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def init_llm_and_embeddings(deployment: str = "gpt-4o", model: str = "gpt-4o"):
    """Initialize LLM and embeddings with common configuration."""
    from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
    
    llm = AzureChatOpenAI(
        azure_deployment=deployment,
        model=model,
        temperature=0,
    )
    
    emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
    
    return llm, emb


def get_session_contents_safe(session_id: str) -> Dict[str, str]:
    """Safely get web contents from session."""
    session_data = get_session_data(session_id)
    return session_data.get("web_contents", {})


def load_from_storage_with_fallback(mongo_store: MongoStore, urls: List[str], 
                                  session_id: str, days: int = 0) -> Tuple[List[Dict[str, str]], List[str]]:
    """Load contents from storage with session fallback."""
    # First try session
    session_contents = get_session_contents_safe(session_id)
    
    contents = []
    missing_urls = []
    
    for url in urls:
        if url in session_contents:
            contents.append({"url": url, "text": session_contents[url]})
        else:
            missing_urls.append(url)
    
    # Then try MongoDB for missing URLs
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
        logger.info(f"Successfully {operation_name}")
        return result
    except Exception as e:
        logger.error(f"Error {operation_name}: {e}")
        # Don't fail the entire request if storage fails
        return None

def generate_session_id(ip: str, user_agent: str = "") -> str:
    """Generate session ID based on client info and timestamp."""
    timestamp = str(datetime.now().timestamp())
    content = f"{ip}_{user_agent}_{timestamp}"
    return hashlib.md5(content.encode()).hexdigest()

def get_session_data(session_id: str) -> dict:
    """Get session data for given session ID."""
    session = SESSION_STORE.get(session_id, {})
    if session:
        # Update last accessed time
        session["last_accessed"] = datetime.now()
    return session

def update_session_data(session_id: str, key: str, value):
    """Update session data for given session ID and key."""
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = {
            "created_at": datetime.now(),
            "last_accessed": datetime.now(),
            "search_results": [],
            "web_contents": {},
            "user_context": {}
        }
    
    SESSION_STORE[session_id][key] = value
    SESSION_STORE[session_id]["last_accessed"] = datetime.now()

def cleanup_expired_sessions():
    """Remove expired sessions."""
    cutoff_time = datetime.now() - timedelta(hours=SESSION_TIMEOUT_HOURS)
    expired_sessions = []
    
    for session_id, session_data in SESSION_STORE.items():
        if session_data.get("last_accessed", datetime.now()) < cutoff_time:
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        del SESSION_STORE[session_id]
        logger.info(f"Cleaned up expired session: {session_id}")

# Configuration utilities
def setup_app_configuration():
    """Setup FastAPI app with middleware and static files."""
    app = FastAPI(title="News Search API", version="1.0.0")
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Mount static files
    app.mount("/static", StaticFiles(directory="."), name="static")
    
    return app


def get_server_config():
    """Get server configuration from environment or defaults."""
    import os
    
    config = {
        "host": os.getenv("HOST", DEFAULT_HOST),
        "port": int(os.getenv("PORT", str(DEFAULT_PORT))),
        "reload": os.getenv("RELOAD", "true").lower() == "true",
        "ssl_keyfile": os.getenv("SSL_KEYFILE"),
        "ssl_certfile": os.getenv("SSL_CERTFILE"),
    }
    
    return config


def check_port_availability(port: int) -> bool:
    """Check if a port is available."""
    import socket
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def get_fallback_port(preferred_port: int) -> int:
    """Get a fallback port if the preferred one is not available."""
    for port in range(preferred_port, preferred_port + 100):
        if check_port_availability(port):
            return port
    
    # If no port found in range, return a random available port
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


app = setup_app_configuration()

# Also mount current directory for direct file access (must be last)
# This allows direct access to files like news_scr.js, index.html, etc.


# Request models
class SearchRequest(BaseModel):
    company_name: str = Field(..., description="Company name to search for")
    lang: str = Field(..., description="Language code (e.g., 'zh-CN', 'en-US')")
    search_suffix: str = Field(..., description="Search topic suffix")
    search_engine: str = Field(..., description="Search engine ('Google' or 'Bing')")
    num_results: int = Field(
        ..., ge=1, le=100, description="Number of results to return"
    )
    llm_model: str = Field(..., description="LLM model to use")
    session_id: Optional[str] = Field(None, description="Session ID for data persistence")


class CrawlerRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to crawl")
    crawler_type: str = Field(default="apify", description="Crawler type ('apify')")
    company_name: str = Field(..., description="Company name for storage")
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
    session_id: Optional[str] = Field(None, description="Session ID for data persistence")


class TaggingRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to tag")
    company_name: str = Field(..., description="Company name for storage")
    lang: str = Field(..., description="Language code for storage")
    tagging_method: str = Field(default="rag", description="Tagging method ('rag' or 'all')")
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
    session_id: Optional[str] = Field(None, description="Session ID for data persistence")


class SummaryRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to summarize")
    company_name: str = Field(..., description="Company name for storage")
    lang: str = Field(..., description="Language code for storage")
    summary_method: str = Field(default="map-reduce", description="Summary method ('map-reduce' or 'iterative-refinement')")
    max_words: int = Field(default=300, description="Maximum number of words in summary")
    cluster_docs: bool = Field(default=True, description="Whether to cluster documents before summarization")
    num_clusters: int = Field(default=2, description="Number of clusters for document clustering")
    session_id: Optional[str] = Field(None, description="Session ID for data persistence")


class QARequest(BaseModel):
    question: str = Field(..., description="Question to ask")
    company_name: str = Field(..., description="Company name for context")
    lang: str = Field(..., description="Language code")
    urls: List[str] = Field(..., description="URLs to use as context")
    session_id: Optional[str] = Field(None, description="Session ID for data persistence")


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
async def serve_index():
    """Serve the index.html file."""
    index_path = Path("index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
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
        
        logger.info(f"Search request - company: {request.company_name}, engine: {request.search_engine}, session: {session_id}")

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
                session_id=session_id
            )

        # Convert results to response format
        search_results = [
            SearchResultResponse(url=result["url"], title=result["title"])
            for result in results
        ]

        # Store search results and user context in session
        update_session_data(session_id, "search_results", [
            {"url": result["url"], "title": result["title"]} for result in results
        ])
        update_session_data(session_id, "user_context", {
            "company_name": request.company_name,
            "lang": request.lang,
            "search_params": {
                "search_suffix": request.search_suffix,
                "search_engine": request.search_engine,
                "num_results": request.num_results,
                "llm_model": request.llm_model
            }
        })

        return SearchResponse(
            success=True,
            results=search_results,
            total_results=len(search_results),
            message=f"Successfully found {len(search_results)} news articles",
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return SearchResponse(
            success=False, 
            results=[], 
            total_results=0, 
            message=f"Search error: {str(e)}",
            session_id=request.session_id
        )


@app.post("/api/crawler", response_model=CrawlerResponse)
@require_session(strict=False)
async def crawl_news_content(request: CrawlerRequest):
    """
    Crawl content from news URLs using ApifyCrawler with storage and session support.
    """
    try:
        session_id = request.session_id
        logger.info(f"Crawler request received - session_id: {session_id}, URLs: {len(request.urls)}")
        
        # Handle missing session ID
        if not session_id:
            logger.warning("No session ID provided in crawler request")
            return CrawlerResponse(
                success=False, results=[], total_results=0,
                message="Session is required. Please search for news first, then try getting content again."
            )

        if not request.urls:
            return CrawlerResponse(
                success=False, results=[], total_results=0,
                message="No URLs provided for crawling"
            )

        # Initialize MongoStore
        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)
        results = []
        contents_from_db = []

        # Step 1: Load from storage if enabled
        if request.contents_load:
            logger.info(f"Loading contents from MongoDB (within {request.contents_load_days} days)...")
            contents_from_db = handle_storage_operation(
                mongo_store.load_contents,
                "loaded contents from MongoDB",
                request.urls, days=request.contents_load_days
            ) or []

            # Add stored contents to results
            stored_urls = {content["url"] for content in contents_from_db}
            for content in contents_from_db:
                results.append(CrawlerResultResponse(
                    url=content["url"], success=True,
                    content=content["text"], error=None
                ))

            urls_to_crawl = [url for url in request.urls if url not in stored_urls]
            logger.info(f"Found {len(contents_from_db)} URLs in MongoDB, {len(urls_to_crawl)} URLs to crawl")
        else:
            urls_to_crawl = request.urls

        # Step 2: Crawl remaining URLs
        crawled_contents = []
        if urls_to_crawl:
            logger.info(f"Crawling {len(urls_to_crawl)} URLs")
            crawler = ApifyCrawler()

            try:
                documents = await crawler.get(urls_to_crawl)
                url_to_doc = {doc.metadata.get("source", ""): doc for doc in documents if doc.metadata.get("source")}

                for url in urls_to_crawl:
                    if url in url_to_doc and url_to_doc[url].page_content.strip():
                        content = url_to_doc[url].page_content
                        results.append(CrawlerResultResponse(url=url, success=True, content=content, error=None))
                        crawled_contents.append({"url": url, "text": content})
                    else:
                        error_msg = "Content is empty" if url in url_to_doc else "Content not found for this URL"
                        results.append(CrawlerResultResponse(url=url, success=False, content=None, error=error_msg))

            except Exception as crawler_error:
                logger.error(f"Crawler execution failed: {crawler_error}")
                for url in urls_to_crawl:
                    results.append(CrawlerResultResponse(
                        url=url, success=False, content=None,
                        error=f"Crawling failed: {crawler_error}"
                    ))

        # Step 3: Save to storage and session
        if request.contents_save and crawled_contents:
            handle_storage_operation(
                mongo_store.save_contents,
                "saved contents to MongoDB",
                crawled_contents, days=request.contents_save_days
            )

        # Store all contents in session
        all_contents = {content["url"]: content["text"] for content in contents_from_db}
        all_contents.update({r.url: r.content for r in results if r.success and r.content})
        
        # session_id is guaranteed to exist due to @require_session decorator
        if session_id:
            update_session_data(session_id, "web_contents", all_contents)

        success_count = sum(1 for r in results if r.success)
        return CrawlerResponse(
            success=True, results=results, total_results=len(results),
            message=f"Crawling completed: {success_count} successful, {len(results) - success_count} failed"
        )

    except Exception as e:
        logger.error(f"Crawler error: {e}")
        failed_results = [
            CrawlerResultResponse(url=url, success=False, content=None, error=f"System error: {e}")
            for url in request.urls
        ]
        return CrawlerResponse(
            success=False, results=failed_results, total_results=len(failed_results),
            message=f"System error: {e}"
        )


@app.post("/api/tagging", response_model=TaggingResponse)
@require_session(strict=False)
async def tag_news_content(request: TaggingRequest):
    """
    Perform FC Tagging on news content with storage and session support.
    """
    try:
        session_id = request.session_id
        logger.info(f"Tagging request received - session_id: {session_id}, URLs: {len(request.urls)}")
        
        # Handle missing session ID
        if not session_id:
            logger.warning("No session ID provided in tagging request")
            return TaggingResponse(
                success=False, results=[], total_results=0,
                message="Session is required. Please search for news and get content first, then try tagging again."
            )

        if not request.urls:
            return TaggingResponse(
                success=False, results=[], total_results=0,
                message="No URLs provided for tagging"
            )

        # Initialize MongoStore
        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)
        results = []

        # Step 1: Load existing tags from storage
        tags_from_db = []
        if request.tags_load:
            logger.info(f"Loading tags from MongoDB (within {request.tags_load_days} days)...")
            tags_from_db = handle_storage_operation(
                mongo_store.load_tags,
                "loaded tags from MongoDB",
                request.urls, method=request.tagging_method,
                llm_name="gpt-4o", days=request.tags_load_days
            ) or []

            # Add stored tags to results
            stored_urls = {tag["url"] for tag in tags_from_db}
            for tag in tags_from_db:
                results.append(TaggingResultResponse(
                    url=tag["url"], success=True,
                    crime_type=tag.get("crime_type"), 
                    probability=tag.get("probability"), error=None
                ))

            urls_to_tag = [url for url in request.urls if url not in stored_urls]
            logger.info(f"Found {len(tags_from_db)} URLs in MongoDB, {len(urls_to_tag)} URLs to tag")
        else:
            urls_to_tag = request.urls

        # Step 2: Tag remaining URLs
        if urls_to_tag:
            logger.info(f"Tagging {len(urls_to_tag)} URLs")
            
            # Get contents with fallback
            contents_to_tag, urls_without_content = load_from_storage_with_fallback(
                mongo_store, urls_to_tag, session_id or ""
            )

            # Mark URLs without content as failed
            for url in urls_without_content:
                results.append(TaggingResultResponse(
                    url=url, success=False, crime_type=None, 
                    probability=None, error="Content not found for this URL, please get content first"
                ))

            if contents_to_tag:
                # Initialize tagging components
                llm, emb = init_llm_and_embeddings()
                fc_tagging = FCTagging(llm, emb)
                
                from langchain_core.documents import Document
                from langchain_text_splitters import RecursiveCharacterTextSplitter
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

                tagged_results = []
                for content in contents_to_tag:
                    url, text = content["url"], content["text"]
                    
                    try:
                        docs = text_splitter.split_documents([Document(page_content=text)])
                        
                        # Perform tagging based on method
                        if request.tagging_method == "rag":
                            tag_result = await fc_tagging.tagging_rag(docs)
                        else:  # "all" for Full-text
                            tag_result = await fc_tagging.tagging_combine(docs)

                        results.append(TaggingResultResponse(
                            url=url, success=True,
                            crime_type=tag_result.get("crime_type"),
                            probability=tag_result.get("probability"), error=None
                        ))
                        
                        tagged_results.append({
                            "url": url, "crime_type": tag_result.get("crime_type"),
                            "probability": tag_result.get("probability"),
                            "method": request.tagging_method
                        })

                    except Exception as tag_error:
                        results.append(TaggingResultResponse(
                            url=url, success=False, crime_type=None,
                            probability=None, error=f"Tagging failed: {tag_error}"
                        ))

                # Step 3: Save tagged results to storage
                if request.tags_save and tagged_results:
                    handle_storage_operation(
                        mongo_store.save_tags,
                        "saved tags to storage",
                        tagged_results, method=request.tagging_method,
                        llm_name="gpt-4o", days=request.tags_save_days
                    )

        success_count = sum(1 for r in results if r.success)
        return TaggingResponse(
            success=True, results=results, total_results=len(results),
            message=f"Tagging completed: {success_count} successful, {len(results) - success_count} failed"
        )

    except Exception as e:
        logger.error(f"Tagging error: {e}")
        failed_results = [
            TaggingResultResponse(url=url, success=False, crime_type=None, 
                                probability=None, error=f"System error: {e}")
            for url in request.urls
        ]
        return TaggingResponse(
            success=False, results=failed_results, total_results=len(failed_results),
            message=f"System error: {e}"
        )


@app.post("/api/summary", response_model=SummaryResponse)
@require_session(strict=False)
async def summarize_news_content(request: SummaryRequest):
    """
    Perform summarization on news content from session.
    """
    try:
        session_id = request.session_id
        logger.info(f"Summary request received - session_id: {session_id}, URLs: {len(request.urls)}")
        
        # Handle missing session ID
        if not session_id:
            logger.warning("No session ID provided in summary request")
            return create_error_response(
                SummaryResponse,
                "Session is required. Please search for news and get content first, then try summarization again.",
                summary=None
            )

        if not request.urls:
            return create_error_response(
                SummaryResponse,
                "No URLs provided for summarization",
                summary=None
            )

        # Get contents from session and validate
        web_contents = get_session_contents_safe(session_id or "")
        contents_to_summarize = []
        missing_urls = []
        
        for url in request.urls:
            if url in web_contents:
                contents_to_summarize.append({"url": url, "text": web_contents[url]})
            else:
                missing_urls.append(url)
        
        # Validate contents
        is_valid, error_msg = validate_contents_for_processing(contents_to_summarize, missing_urls)
        if not is_valid:
            return create_error_response(
                SummaryResponse,
                error_msg or "Content validation failed",
                summary=None
            )
            
        logger.info(f"Found {len(contents_to_summarize)} contents to summarize")

        try:
            # Initialize LLM and embeddings
            llm, emb = init_llm_and_embeddings()
            
            # Create documents from content
            docs = convert_contents_to_documents(contents_to_summarize)
            
            # Determine number of clusters
            num_clusters = request.num_clusters if request.cluster_docs else 0
            
            # Choose summarization method and perform summarization
            if request.summary_method == "map-reduce":
                summarizer = MapReduceSummarization(llm, emb)
            else:  # iterative-refinement
                summarizer = RefinementSummarization(llm, emb)
            
            summary = await summarizer.summarize(
                docs=docs, lang=request.lang,
                max_words=request.max_words, num_cluster=num_clusters
            )
            
            logger.info("Summarization completed successfully")
            
            return create_success_response(
                SummaryResponse,
                f"Summary generated successfully, processed {len(contents_to_summarize)} articles",
                summary=summary
            )

        except Exception as summarization_error:
            logger.error(f"Summarization execution failed: {summarization_error}")
            return create_error_response(
                SummaryResponse,
                f"Summary generation failed: {summarization_error}",
                summary=None
            )

    except Exception as e:
        logger.error(f"Summary error: {e}")
        return create_error_response(
            SummaryResponse,
            f"System error: {e}",
            summary=None
        )


@app.post("/api/qa", response_model=QAResponse)
@require_session(strict=False)
async def qa_endpoint(request: QARequest):
    """Process QA request with context from session."""
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    try:
        session_id = request.session_id
        logger.info(f"QA request received - session_id: {session_id}, company: {request.company_name}")
        
        # Handle missing session ID
        if not session_id:
            logger.warning("No session ID provided in QA request")
            return create_error_response(
                QAResponse,
                "Session is required. Please search for news and get content first, then try Q&A again.",
                question=request.question,
                answer=None
            )
        
        # Initialize LLM and embeddings using utility function
        llm, _ = init_llm_and_embeddings("gpt-4o-mini", "gpt-4o-mini")
        
        # Initialize embeddings with QA specific configuration
        from langchain_openai import AzureOpenAIEmbeddings
        embeddings = AzureOpenAIEmbeddings(
            azure_deployment="text-embedding-3-small",
            chunk_size=1000
        )
        
        # Get contents using utility function (no MongoDB fallback for QA)
        session_contents = get_session_contents_safe(request.session_id or "")
        
        contents = []
        missing_urls = []
        
        for url in request.urls:
            if url in session_contents:
                contents.append({"url": url, "text": session_contents[url]})
            else:
                missing_urls.append(url)
        
        if missing_urls:
            logger.warning(f"URLs not found in session: {missing_urls}")
        
        if not contents:
            return create_error_response(
                QAResponse,
                "No relevant content found for answering the question",
                question=request.question,
                answer=None
            )
        
        # Convert contents to documents
        documents = convert_contents_to_documents(contents)
        
        if not documents:
            return create_error_response(
                QAResponse,
                "No valid document content found for answering the question",
                question=request.question,
                answer=None
            )
        
        # Split documents into chunks
        text_splitter = create_qa_config()
        split_docs = text_splitter.split_documents(documents)
        
        # Initialize QA system
        qa_system = QAWithContext(llm=llm, emb=embeddings)
        
        # Process the query
        result = await qa_system.query(
            query=request.question,
            lang=request.lang,
            docs=split_docs
        )
        
        return create_success_response(
            QAResponse,
            "Q&A processing successful",
            question=result.get("question", request.question),
            answer=result.get("answer")
        )
        
    except Exception as e:
        logger.error(f"Error in QA processing: {str(e)}")
        return create_error_response(
            QAResponse,
            f"Q&A processing failed: {str(e)}",
            question=request.question,
            answer=None
        )


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "News Search API is running"}


# Session management endpoints
@app.get("/api/session/{session_id}/status")
async def get_session_status(session_id: str):
    """Get session status."""
    cleanup_expired_sessions()
    
    session_data = get_session_data(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    search_results = session_data.get("search_results", [])
    web_contents = session_data.get("web_contents", {})
    user_context = session_data.get("user_context", {})
    
    created_at = session_data.get("created_at")
    last_accessed = session_data.get("last_accessed")
    
    return {
        "session_id": session_id,
        "created_at": created_at.isoformat() if created_at else None,
        "last_accessed": last_accessed.isoformat() if last_accessed else None,
        "search_results_count": len(search_results),
        "web_contents_count": len(web_contents),
        "user_context": user_context,
        "urls_with_content": list(web_contents.keys())
    }

@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    """Clear session data."""
    if session_id in SESSION_STORE:
        del SESSION_STORE[session_id]
        return {"message": f"Session {session_id} cleared successfully"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")

@app.get("/api/session/{session_id}/contents")
async def get_session_contents(session_id: str):
    """Get session contents."""
    cleanup_expired_sessions()
    
    session_data = get_session_data(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")
    
    web_contents = session_data.get("web_contents", {})
    return {
        "session_id": session_id,
        "contents": [
            {"url": url, "text_length": len(text)} 
            for url, text in web_contents.items()
        ]
    }


@app.get("/api/debug/session")
async def debug_session_info():
    """Debug endpoint to check current session information."""
    return {
        "total_sessions": len(SESSION_STORE),
        "sessions": {
            session_id: {
                "created_at": data.get("created_at").isoformat() if data.get("created_at") else None,
                "last_accessed": data.get("last_accessed").isoformat() if data.get("last_accessed") else None,
                "search_results_count": len(data.get("search_results", [])),
                "web_contents_count": len(data.get("web_contents", {})),
                "has_user_context": bool(data.get("user_context"))
            }
            for session_id, data in SESSION_STORE.items()
        }
    }


@app.post("/api/debug/test-session")
async def test_session_handling(request_data: dict):
    """Debug endpoint to test session handling."""
    session_id = request_data.get("session_id")
    logger.info(f"Test session request - session_id: {session_id}")
    
    if not session_id:
        return {
            "success": False,
            "message": "No session ID provided",
            "session_exists": False
        }
    
    session_data = get_session_data(session_id)
    session_exists = bool(session_data)
    
    return {
        "success": True,
        "message": f"Session {session_id} {'exists' if session_exists else 'does not exist'}",
        "session_exists": session_exists,
        "session_data_keys": list(session_data.keys()) if session_data else [],
        "web_contents_count": len(session_data.get("web_contents", {})) if session_data else 0
    }


# Response utility functions
def create_error_response(response_class, message: str, **kwargs):
    """Create standardized error response."""
    return response_class(success=False, message=message, **kwargs)


def create_success_response(response_class, message: str, **kwargs):
    """Create standardized success response."""
    return response_class(success=True, message=message, **kwargs)


def create_failed_result_responses(urls: List[str], result_class, error_message: str):
    """Create failed result responses for multiple URLs."""
    return [
        result_class(url=url, success=False, error=error_message, **{
            key: None for key in result_class.__fields__ 
            if key not in ['url', 'success', 'error']
        })
        for url in urls
    ]


def create_qa_config():
    """Create QA-specific configuration."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    return RecursiveCharacterTextSplitter(
        chunk_size=DEFAULT_CHUNK_SIZE, 
        chunk_overlap=DEFAULT_CHUNK_OVERLAP
    )


def convert_contents_to_documents(contents: List[Dict[str, str]]):
    """Convert content dictionaries to Document objects."""
    from langchain_core.documents import Document
    
    documents = []
    for content in contents:
        if content.get("text"):
            doc = Document(
                page_content=content["text"],
                metadata={"url": content["url"]}
            )
            documents.append(doc)
    return documents


def validate_contents_for_processing(contents: List[Dict[str, str]], missing_urls: List[str]):
    """Validate that we have content for processing."""
    if missing_urls:
        logger.warning(f"URLs not found: {missing_urls}")
    
    if not contents:
        return False, "Content not found, please get content first"
    
    return True, None
    

# Logging utilities
def log_endpoint_start(endpoint_name: str, params: dict):
    """Log the start of an endpoint execution."""
    logger.info(f"Starting {endpoint_name} with params: {params}")


def log_endpoint_success(endpoint_name: str, message: str):
    """Log successful endpoint completion."""
    logger.info(f"{endpoint_name} completed successfully: {message}")


def log_endpoint_error(endpoint_name: str, error: Exception):
    """Log endpoint error."""
    logger.error(f"{endpoint_name} error: {str(error)}")


def log_storage_operation(operation: str, success: bool, details: str = ""):
    """Log storage operations with standardized format."""
    status = "successful" if success else "failed"
    logger.info(f"Storage {operation} {status}: {details}")


# Mount root directory for direct file access (must be after all API routes)
app.mount("/", StaticFiles(directory=".", html=True), name="root")

if __name__ == "__main__":
    import uvicorn

    # Get server configuration
    config = get_server_config()
    
    # Check if preferred port is available, get fallback if not
    preferred_port = config["port"]
    if not check_port_availability(preferred_port):
        fallback_port = get_fallback_port(preferred_port)
        logger.warning(f"Preferred port {preferred_port} not available, using fallback port {fallback_port}")
        config["port"] = fallback_port
    
    # Run the application
    uvicorn.run("serv_fastapi:app", host=config["host"], port=config["port"], reload=config["reload"])
