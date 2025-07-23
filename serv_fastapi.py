import logging
import hashlib
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session storage
SESSION_STORE = {}
SESSION_TIMEOUT_HOURS = 2

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


# Language mapping for display
LANGUAGE_DISPLAY_MAP = {
    "zh-CN": "Simplified Chinese",
    "zh-HK": "Traditional Chinese(HK)",
    "zh-TW": "Traditional Chinese(TW)",
    "en-US": "English",
    "ja-JP": "Japanese",
}

# Search suffix mapping by language
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
async def search_news(http_request: Request, request: SearchRequest):
    """
    Search for news articles based on company name and parameters.
    """
    try:
        # Clean up expired sessions
        cleanup_expired_sessions()
        
        # Generate session ID if not provided
        client_ip = http_request.client.host if http_request.client else "unknown"
        user_agent = http_request.headers.get("user-agent", "")
        session_id = request.session_id or generate_session_id(client_ip, user_agent)
        
        logger.info(
            f"Searching for: {request.company_name} with engine: {request.search_engine}, session: {session_id}"
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
async def crawl_news_content(request: CrawlerRequest):
    """
    Crawl content from news URLs using ApifyCrawler with storage and session support.
    """
    try:
        # Clean up expired sessions
        cleanup_expired_sessions()
        
        session_id = request.session_id
        if not session_id:
            return CrawlerResponse(
                success=False,
                results=[],
                total_results=0,
                message="Session ID is required",
            )

        logger.info(f"Starting to crawl {len(request.urls)} URLs for session: {session_id}")

        if not request.urls:
            return CrawlerResponse(
                success=False,
                results=[],
                total_results=0,
                message="No URLs provided for crawling",
            )

        # Initialize MongoStore for storage operations
        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)

        # Initialize results list
        results = []
        urls_to_crawl = []
        contents_from_db = []

        # Step 1: If contents_load is enabled, try to load from MongoDB first
        if request.contents_load:
            try:
                logger.info(
                    f"Loading contents from MongoDB (within {request.contents_load_days} days)..."
                )
                contents_from_db = mongo_store.load_contents(
                    request.urls, days=request.contents_load_days
                )

                # Create mapping of stored content
                stored_urls = {content["url"] for content in contents_from_db}

                # Add stored contents to results
                for content in contents_from_db:
                    results.append(
                        CrawlerResultResponse(
                            url=content["url"],
                            success=True,
                            content=content["text"],
                            error=None,
                        )
                    )
                    logger.info(f"Loaded from MongoDB: {content['url']}")

                # Only crawl URLs that are not in storage
                urls_to_crawl = [url for url in request.urls if url not in stored_urls]
                logger.info(
                    f"Found {len(contents_from_db)} URLs in MongoDB, {len(urls_to_crawl)} URLs to crawl"
                )

            except Exception as e:
                logger.error(f"Error loading from MongoDB: {str(e)}")
                # If storage loading fails, crawl all URLs
                urls_to_crawl = request.urls
        else:
            # If contents_load is disabled, crawl all URLs
            urls_to_crawl = request.urls

        # Step 2: Crawl remaining URLs
        if urls_to_crawl:
            logger.info(f"Crawling {len(urls_to_crawl)} URLs")

            # Initialize crawler
            crawler = ApifyCrawler()

            try:
                # Get documents from URLs
                documents = await crawler.get(urls_to_crawl)
                logger.info(f"Successfully crawled {len(documents)} documents")

                # Create a mapping of URL to document
                url_to_doc = {}
                for doc in documents:
                    source_url = doc.metadata.get("source", "")
                    if source_url:
                        url_to_doc[source_url] = doc

                # Process crawled URLs
                crawled_contents = []
                for url in urls_to_crawl:
                    if url in url_to_doc:
                        doc = url_to_doc[url]
                        if doc.page_content and doc.page_content.strip():
                            results.append(
                                CrawlerResultResponse(
                                    url=url,
                                    success=True,
                                    content=doc.page_content,
                                    error=None,
                                )
                            )

                            # Prepare for storage
                            crawled_contents.append(
                                {"url": url, "text": doc.page_content}
                            )
                            logger.info(f"Successfully processed URL: {url}")
                        else:
                            results.append(
                                CrawlerResultResponse(
                                    url=url,
                                    success=False,
                                    content=None,
                                    error="Content is empty",
                                )
                            )
                            logger.warning(f"Empty content for URL: {url}")
                    else:
                        results.append(
                            CrawlerResultResponse(
                                url=url,
                                success=False,
                                content=None,
                                error="Content not found for this URL",
                            )
                        )
                        logger.warning(f"No content found for URL: {url}")

                # Step 3: Save crawled contents to MongoDB if enabled
                if request.contents_save and crawled_contents:
                    try:
                        logger.info(
                            f"Saving {len(crawled_contents)} contents to MongoDB (only update if older than {request.contents_save_days} days)..."
                        )
                        mongo_store.save_contents(
                            crawled_contents, days=request.contents_save_days
                        )
                        logger.info("Successfully saved contents to MongoDB")
                    except Exception as e:
                        logger.error(f"Error saving to MongoDB: {str(e)}")
                        # Don't fail the entire request if storage fails

            except Exception as crawler_error:
                logger.error(f"Crawler execution failed: {str(crawler_error)}")
                # If crawler fails completely, mark all URLs as failed
                for url in urls_to_crawl:
                    results.append(
                        CrawlerResultResponse(
                            url=url,
                            success=False,
                            content=None,
                            error=f"Crawling failed: {str(crawler_error)}",
                        )
                    )

        # Step 4: Merge all contents (from MongoDB + crawled) and store in session
        all_contents = {}
        for content in contents_from_db:
            all_contents[content["url"]] = content["text"]
        
        for result in results:
            if result.success and result.content:
                all_contents[result.url] = result.content

        # Store merged contents in session
        update_session_data(session_id, "web_contents", all_contents)
        logger.info(f"Stored {len(all_contents)} contents in session {session_id}")

        success_count = sum(1 for r in results if r.success)

        return CrawlerResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"Crawling completed: {success_count} successful, {len(results) - success_count} failed",
        )

    except Exception as e:
        logger.error(f"Crawler error: {str(e)}")
        # Even in case of general error, try to return failed results for all URLs
        failed_results = [
            CrawlerResultResponse(
                url=url, success=False, content=None, error=f"System error: {str(e)}"
            )
            for url in request.urls
        ]

        return CrawlerResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"System error: {str(e)}",
        )


@app.post("/api/tagging", response_model=TaggingResponse)
async def tag_news_content(request: TaggingRequest):
    """
    Perform FC Tagging on news content with storage and session support.
    """
    try:
        # Clean up expired sessions
        cleanup_expired_sessions()
        
        session_id = request.session_id
        if not session_id:
            return TaggingResponse(
                success=False,
                results=[],
                total_results=0,
                message="Session ID is required",
            )

        logger.info(f"Starting FC Tagging for {len(request.urls)} URLs, session: {session_id}")

        if not request.urls:
            return TaggingResponse(
                success=False,
                results=[],
                total_results=0,
                message="No URLs provided for tagging",
            )

        # Initialize MongoStore for storage operations
        mongo_store = MongoStore(company_name=request.company_name, lang=request.lang)

        # Initialize results list
        results = []
        urls_to_tag = []
        tags_from_db = []

        # Step 1: If tags_load is enabled, try to load from MongoDB first
        if request.tags_load:
            try:
                logger.info(
                    f"Loading tags from MongoDB (within {request.tags_load_days} days)..."
                )
                tags_from_db = mongo_store.load_tags(
                    request.urls, 
                    method=request.tagging_method,
                    llm_name="gpt-4o",
                    days=request.tags_load_days
                )

                # Create mapping of stored tags
                stored_urls = {tag["url"] for tag in tags_from_db}

                # Add stored tags to results
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
                    logger.info(f"Loaded tags from MongoDB: {tag['url']}")

                # Only tag URLs that are not in storage
                urls_to_tag = [url for url in request.urls if url not in stored_urls]
                logger.info(
                    f"Found {len(tags_from_db)} URLs in MongoDB, {len(urls_to_tag)} URLs to tag"
                )

            except Exception as e:
                logger.error(f"Error loading tags from MongoDB: {str(e)}")
                # If storage loading fails, tag all URLs
                urls_to_tag = request.urls
        else:
            # If tags_load is disabled, tag all URLs
            urls_to_tag = request.urls

        # Step 2: Tag remaining URLs
        if urls_to_tag:
            logger.info(f"Tagging {len(urls_to_tag)} URLs")

            try:
                # Get contents from session first
                session_data = get_session_data(session_id)
                web_contents = session_data.get("web_contents", {})
                
                contents_to_tag = []
                urls_without_content = []
                
                # Check which URLs have content in session
                for url in urls_to_tag:
                    if url in web_contents:
                        contents_to_tag.append({"url": url, "text": web_contents[url]})
                    else:
                        urls_without_content.append(url)
                
                # If some URLs don't have content in session, try MongoDB as fallback
                if urls_without_content:
                    logger.info(f"Trying to load {len(urls_without_content)} URLs from MongoDB as fallback")
                    fallback_contents = mongo_store.load_contents(urls_without_content, days=0)
                    contents_to_tag.extend(fallback_contents)
                    
                    # Update URLs without content
                    fallback_urls = {content["url"] for content in fallback_contents}
                    urls_without_content = [url for url in urls_without_content if url not in fallback_urls]
                
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
                
                if not contents_to_tag:
                    logger.warning("No content found for tagging")
                else:
                    # Initialize FCTagging
                    from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
                    from langchain_core.documents import Document
                    from langchain_text_splitters import RecursiveCharacterTextSplitter
                    
                    llm = AzureChatOpenAI(
                        azure_deployment="gpt-4o",
                        model="gpt-4o", 
                        temperature=0,
                    )
                    emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
                    
                    fc_tagging = FCTagging(llm, emb)
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
                    
                    # Process each URL
                    tagged_results = []
                    for content in contents_to_tag:
                        url = content["url"]
                        text = content["text"]
                        
                        try:
                            # Create documents from text
                            docs = text_splitter.split_documents([Document(page_content=text)])
                            
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
                            
                            # Prepare for storage
                            tagged_results.append({
                                "url": url,
                                "crime_type": tag_result.get("crime_type"),
                                "probability": tag_result.get("probability"),
                                "method": request.tagging_method
                            })
                            logger.info(f"Successfully tagged URL: {url}")
                            

                        except Exception as tag_error:
                            results.append(
                                TaggingResultResponse(
                                    url=url,
                                    success=False,
                                    crime_type=None,
                                    probability=None,
                                    error=f"Tagging failed: {str(tag_error)}",
                                )
                            )
                            logger.error(f"Error tagging URL {url}: {str(tag_error)}")
                    
                    # Handle URLs that were not found in contents
                    content_urls = {content["url"] for content in contents_to_tag}
                    for url in urls_to_tag:
                        if url not in content_urls:
                            results.append(
                                TaggingResultResponse(
                                    url=url,
                                    success=False,
                                    crime_type=None,
                                    probability=None,
                                    error="Content not found for this URL, please get content first",
                                )
                            )
                    
                    # Step 3: Save tagged results to storage if enabled
                    if request.tags_save and tagged_results:
                        try:
                            logger.info(
                                f"Saving {len(tagged_results)} tags to storage (only update if older than {request.tags_save_days} days)..."
                            )
                            mongo_store.save_tags(
                                tagged_results, 
                                method=request.tagging_method,
                                llm_name="gpt-4o",
                                days=request.tags_save_days
                            )
                            logger.info("Successfully saved tags to storage")
                        except Exception as e:
                            logger.error(f"Error saving tags to storage: {str(e)}")
                            # Don't fail the entire request if storage fails

            except Exception as tagging_error:
                logger.error(f"Tagging execution failed: {str(tagging_error)}")
                # If tagging fails completely, mark all URLs as failed
                for url in urls_to_tag:
                    results.append(
                        TaggingResultResponse(
                            url=url,
                            success=False,
                            crime_type=None,
                            probability=None,
                            error=f"Tagging failed: {str(tagging_error)}",
                        )
                    )

        success_count = sum(1 for r in results if r.success)

        return TaggingResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"Tagging completed: {success_count} successful, {len(results) - success_count} failed",
        )

    except Exception as e:
        logger.error(f"Tagging error: {str(e)}")
        # Even in case of general error, try to return failed results for all URLs
        failed_results = [
            TaggingResultResponse(
                url=url, success=False, crime_type=None, probability=None, error=f"System error: {str(e)}"
            )
            for url in request.urls
        ]

        return TaggingResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"System error: {str(e)}",
        )


@app.post("/api/summary", response_model=SummaryResponse)
async def summarize_news_content(request: SummaryRequest):
    """
    Perform summarization on news content from session.
    """
    try:
        # Clean up expired sessions
        cleanup_expired_sessions()
        
        session_id = request.session_id
        if not session_id:
            return SummaryResponse(
                success=False,
                summary=None,
                message="Session ID is required",
            )

        logger.info(f"Starting summarization for {len(request.urls)} URLs, session: {session_id}")

        if not request.urls:
            return SummaryResponse(
                success=False,
                summary=None,
                message="No URLs provided for summarization",
            )

        # Get contents from session
        session_data = get_session_data(session_id)
        web_contents = session_data.get("web_contents", {})
        
        contents_to_summarize = []
        missing_urls = []
        
        for url in request.urls:
            if url in web_contents:
                contents_to_summarize.append({"url": url, "text": web_contents[url]})
            else:
                missing_urls.append(url)
        
        if missing_urls:
            logger.warning(f"URLs not found in session: {missing_urls}")
        
        if not contents_to_summarize:
            return SummaryResponse(
                success=False,
                summary=None,
                message="Content not found for summarization, please get content first",
            )
            
        logger.info(f"Found {len(contents_to_summarize)} contents to summarize")

        try:
            # Initialize LLM and embeddings
            from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
            from langchain_core.documents import Document
            
            llm = AzureChatOpenAI(
                azure_deployment="gpt-4o",
                model="gpt-4o",
                temperature=0,
            )
            emb = AzureOpenAIEmbeddings(model="text-embedding-3-small")
            
            # Create documents from content
            docs = [Document(page_content=content["text"]) for content in contents_to_summarize]
            
            # Determine number of clusters
            num_clusters = request.num_clusters if request.cluster_docs else 0
            
            # Choose summarization method and perform summarization
            if request.summary_method == "map-reduce":
                summarizer = MapReduceSummarization(llm, emb)
                summary = await summarizer.summarize(
                    docs=docs,
                    lang=request.lang,
                    max_words=request.max_words,
                    num_cluster=num_clusters
                )
            else:  # iterative-refinement
                summarizer = RefinementSummarization(llm, emb)
                summary = await summarizer.summarize(
                    docs=docs,
                    lang=request.lang,
                    max_words=request.max_words,
                    num_cluster=num_clusters
                )
            
            logger.info("Summarization completed successfully")
            
            return SummaryResponse(
                success=True,
                summary=summary,
                message=f"Summary generated successfully, processed {len(contents_to_summarize)} articles",
            )

        except Exception as summarization_error:
            logger.error(f"Summarization execution failed: {str(summarization_error)}")
            return SummaryResponse(
                success=False,
                summary=None,
                message=f"Summary generation failed: {str(summarization_error)}",
            )

    except Exception as e:
        logger.error(f"Summary error: {str(e)}")
        return SummaryResponse(
            success=False,
            summary=None,
            message=f"System error: {str(e)}",
        )


@app.post("/api/qa", response_model=QAResponse)
async def qa_endpoint(request: QARequest):
    """Process QA request with context from session."""
    from langchain_core.documents import Document
    from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    try:
        # Clean up expired sessions
        cleanup_expired_sessions()
        
        session_id = request.session_id
        if not session_id:
            return QAResponse(
                success=False,
                question=request.question,
                answer=None,
                message="Session ID is required"
            )

        logger.info(f"Processing QA request for company: {request.company_name}, session: {session_id}")
        
        # Initialize LLM and embeddings
        llm = AzureChatOpenAI(
            azure_deployment="gpt-4o-mini",
            model_version="2024-07-18",
            temperature=0.0
        )
        
        embeddings = AzureOpenAIEmbeddings(
            azure_deployment="text-embedding-3-small",
            chunk_size=1000
        )
        
        # Get contents from session
        session_data = get_session_data(session_id)
        web_contents = session_data.get("web_contents", {})
        
        contents = []
        missing_urls = []
        
        for url in request.urls:
            if url in web_contents:
                contents.append({"url": url, "text": web_contents[url]})
            else:
                missing_urls.append(url)
        
        if missing_urls:
            logger.warning(f"URLs not found in session: {missing_urls}")
        
        if not contents:
            return QAResponse(
                success=False,
                question=request.question,
                answer=None,
                message="No relevant content found for answering the question"
            )
        
        # Convert contents to documents
        documents = []
        for content in contents:
            if content.get("text"):
                doc = Document(
                    page_content=content["text"],
                    metadata={"url": content["url"]}
                )
                documents.append(doc)
        
        if not documents:
            return QAResponse(
                success=False,
                question=request.question,
                answer=None,
                message="No valid document content found for answering the question"
            )
        
        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100
        )
        
        split_docs = text_splitter.split_documents(documents)
        
        # Initialize QA system
        qa_system = QAWithContext(llm=llm, emb=embeddings)
        
        # Process the query
        result = await qa_system.query(
            query=request.question,
            lang=request.lang,
            docs=split_docs
        )
        
        return QAResponse(
            success=True,
            question=result.get("question", request.question),
            answer=result.get("answer"),
            message="Q&A processing successful"
        )
        
    except Exception as e:
        logger.error(f"Error in QA processing: {str(e)}")
        return QAResponse(
            success=False,
            question=request.question,
            answer=None,
            message=f"Q&A processing failed: {str(e)}"
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


# Mount root directory for direct file access (must be after all API routes)
app.mount("/", StaticFiles(directory=".", html=True), name="root")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("serv_fastapi:app", host="127.0.0.1", port=8280, reload=True)
