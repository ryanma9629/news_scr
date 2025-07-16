from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import logging
from pathlib import Path

from websearch import GoogleSerperNews, BingSearch
from crawler import ApifyCrawler  # Import ApifyCrawler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    num_results: int = Field(..., ge=1, le=100, description="Number of results to return")
    llm_model: str = Field(..., description="LLM model to use")

class CrawlerRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to crawl")
    crawler_type: str = Field(default="apify", description="Crawler type ('apify')")

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

class CrawlerResponse(BaseModel):
    success: bool
    results: List[CrawlerResultResponse]
    total_results: int
    message: str

# Language mapping for display
LANGUAGE_DISPLAY_MAP = {
    "zh-CN": "Simplified Chinese",
    "zh-HK": "Traditional Chinese(HK)",
    "zh-TW": "Traditional Chinese(TW)",
    "en-US": "English",
    "ja-JP": "Japanese"
}

# Search suffix mapping by language
SEARCH_SUFFIX_MAP = {
    "negative": {
        "zh-CN": "负面新闻",
        "zh-HK": "負面新聞", 
        "zh-TW": "負面新聞",
        "en-US": "negative news",
        "ja-JP": "ネガティブニュース"
    },
    "crime": {
        "zh-CN": "犯罪嫌疑",
        "zh-HK": "犯罪嫌疑",
        "zh-TW": "犯罪嫌疑", 
        "en-US": "criminal suspect",
        "ja-JP": "犯罪容疑"
    },
    "everything": {
        "zh-CN": "",
        "zh-HK": "",
        "zh-TW": "",
        "en-US": "",
        "ja-JP": ""
    }
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
async def search_news(request: SearchRequest):
    """
    Search for news articles based on company name and parameters.
    """
    try:
        logger.info(f"Searching for: {request.company_name} with engine: {request.search_engine}")
        
        # Generate search keywords
        keywords = get_search_keywords(
            request.company_name, 
            request.search_suffix, 
            request.lang
        )
        
        # Get search engine instance
        search_engine = get_search_engine(request.search_engine, request.lang)
        if not search_engine:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported search engine: {request.search_engine}"
            )
        
        # Perform search
        results = search_engine.search(keywords, request.num_results)
        
        if results is None:
            return SearchResponse(
                success=False,
                results=[],
                total_results=0,
                message="搜索失败，请检查网络连接或API配置"
            )
        
        # Convert results to response format
        search_results = [
            SearchResultResponse(url=result["url"], title=result["title"])
            for result in results
        ]
        
        return SearchResponse(
            success=True,
            results=search_results,
            total_results=len(search_results),
            message=f"成功找到 {len(search_results)} 条新闻"
        )
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return SearchResponse(
            success=False,
            results=[],
            total_results=0,
            message=f"搜索出错: {str(e)}"
        )

@app.post("/api/crawler", response_model=CrawlerResponse)
async def crawl_news_content(request: CrawlerRequest):
    """
    Crawl content from news URLs using ApifyCrawler.
    """
    try:
        logger.info(f"Starting to crawl {len(request.urls)} URLs")
        
        if not request.urls:
            return CrawlerResponse(
                success=False,
                results=[],
                total_results=0,
                message="没有提供要爬取的URL"
            )
        
        # Initialize crawler
        crawler = ApifyCrawler()
        
        # Initialize results list with all URLs
        results = []
        
        try:
            # Get documents from URLs
            documents = await crawler.get(request.urls)
            logger.info(f"Successfully crawled {len(documents)} documents")
            
            # Create a mapping of URL to document
            url_to_doc = {}
            for doc in documents:
                source_url = doc.metadata.get("source", "")
                if source_url:
                    url_to_doc[source_url] = doc
            
            # Process each URL to ensure all are included in results
            for url in request.urls:
                if url in url_to_doc:
                    doc = url_to_doc[url]
                    if doc.page_content and doc.page_content.strip():
                        results.append(CrawlerResultResponse(
                            url=url,
                            success=True,
                            content=doc.page_content,
                            error=None
                        ))
                        logger.info(f"Successfully processed URL: {url}")
                    else:
                        results.append(CrawlerResultResponse(
                            url=url,
                            success=False,
                            content=None,
                            error="内容为空"
                        ))
                        logger.warning(f"Empty content for URL: {url}")
                else:
                    results.append(CrawlerResultResponse(
                        url=url,
                        success=False,
                        content=None,
                        error="未找到该URL的内容"
                    ))
                    logger.warning(f"No content found for URL: {url}")
                    
        except Exception as crawler_error:
            logger.error(f"Crawler execution failed: {str(crawler_error)}")
            # If crawler fails completely, mark all URLs as failed
            for url in request.urls:
                results.append(CrawlerResultResponse(
                    url=url,
                    success=False,
                    content=None,
                    error=f"爬取失败: {str(crawler_error)}"
                ))
        
        success_count = sum(1 for r in results if r.success)
        
        return CrawlerResponse(
            success=True,
            results=results,
            total_results=len(results),
            message=f"爬取完成：成功 {success_count} 条，失败 {len(results) - success_count} 条"
        )
        
    except Exception as e:
        logger.error(f"Crawler error: {str(e)}")
        # Even in case of general error, try to return failed results for all URLs
        failed_results = [
            CrawlerResultResponse(
                url=url,
                success=False,
                content=None,
                error=f"系统错误: {str(e)}"
            )
            for url in request.urls
        ]
        
        return CrawlerResponse(
            success=False,
            results=failed_results,
            total_results=len(failed_results),
            message=f"爬取失败: {str(e)}"
        )

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "News Search API is running"}

# Mount root directory for direct file access (must be after all API routes)
app.mount("/", StaticFiles(directory=".", html=True), name="root")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serv_fastapi:app", host="127.0.0.1", port=8280, reload=True)
