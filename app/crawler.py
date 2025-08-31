"""
Web crawling implementations for content extraction.

This module provides abstract and concrete implementations for web crawling
functionality using various crawlers like Apify for document retrieval.
"""

import asyncio
import logging
import os
import sys
from abc import ABC, abstractmethod
from typing import List, Optional, Literal

import aiohttp
from dotenv import load_dotenv
from langchain_apify import ApifyWrapper
from langchain_core.documents import Document

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize logger
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Type alias for crawler types
CrawlerType = Literal["cheerio", "playwright:chrome", "playwright:firefox", "playwright:adaptive"]


class Crawler(ABC):
    """
    Abstract base class for web crawlers that retrieve documents from URLs.

    This class provides a common interface for different web crawling implementations,
    defining the basic structure and required methods for document retrieval.
    """

    def __init__(self) -> None:
        """Initialize the crawler instance."""
        super().__init__()

    @abstractmethod
    async def get(self, urls: List[str]) -> List[Document]:
        """Retrieve documents from the given URLs.

        Args:
            urls: List of URLs to crawl

        Returns:
            List of Document objects containing the crawled content

        Raises:
            NotImplementedError: This method must be implemented by subclasses
        """
        raise NotImplementedError


class ApifyCrawler(Crawler):
    """
    Crawler implementation using the Apify platform for web scraping.

    This class provides document retrieval functionality using Apify's
    website content crawler with configurable scraping parameters.
    """

    def __init__(self, client: Optional[ApifyWrapper] = None) -> None:
        """Initialize the Apify crawler with optional client.

        Args:
            client: Optional ApifyWrapper client instance. If None, a new client is created.
        """
        super().__init__()
        self.client = client or ApifyWrapper()

    async def get(self, urls: List[str], crawler_type: CrawlerType = "cheerio") -> List[Document]:
        """Retrieve documents from URLs using the Apify website content crawler.

        Args:
            urls: List of URLs to crawl
            crawler_type: Type of crawler to use. Options:
                - "cheerio": Fast, lightweight server-side DOM manipulation (default)
                - "playwright:chrome": Chrome browser automation with JavaScript support
                - "playwright:firefox": Firefox browser automation with JavaScript support  
                - "playwright:adaptive": Automatically chooses between Cheerio and Playwright

        Returns:
            List of Document objects containing the crawled content

        Raises:
            ValueError: If an invalid crawler_type is provided
            Exception: If the Apify API call fails
        """
        # Validate crawler_type
        valid_types = ["cheerio", "playwright:chrome", "playwright:firefox", "playwright:adaptive"]
        if crawler_type not in valid_types:
            raise ValueError(f"Invalid crawler_type '{crawler_type}'. Must be one of: {valid_types}")

        try:
            logger.info(f"Starting crawl with crawler type: {crawler_type}")
            
            loader = await self.client.acall_actor(
                actor_id="apify/website-content-crawler",
                run_input={
                    "startUrls": [{"url": url} for url in urls],
                    "crawlerType": crawler_type,
                    "maxCrawlDepth": 0,
                    "useSitemaps": False,
                    "respectRobotsTxtFile": True,
                    "maxConcurrency": 10,
                    "maxSessionRotations": 10,
                    "maxRequestRetries": 1,
                    "requestTimeoutSecs": 30,
                    "dynamicContentWaitSecs": 2,
                    "proxyConfiguration": {
                        "useApifyProxy": True,
                    },
                    "keepElementsCssSelector": "article, main, .content, .article, .post, .entry",
                    "removeElementsCssSelector": """nav, footer, script, style, noscript, svg, 
                        img[src^='data:'], iframe, embed, object,
                        .advertisement, .ads, .social-share, .comments,
                        [role="alert"], [role="banner"], [role="dialog"], 
                        [role="alertdialog"], [role="region"][aria-label*="skip" i],
                        [aria-modal="true"], .cookie-banner, .newsletter""",
                    "blockMedia": True,
                    "clickElementsCssSelector": '[aria-expanded="false"]',
                },
                dataset_mapping_function=lambda item: Document(
                    page_content=item["text"] or "",
                    metadata={"source": item["url"]},
                ),
            )

            documents = loader.load()
            logger.info(f"Successfully crawled {len(documents)} documents using {crawler_type}")
            return documents
            
        except Exception as e:
            logger.error(f"Apify API call failed with crawler type '{crawler_type}': {str(e)}")
            raise


class Crawl4aiCrawler(Crawler):
    """
    Crawler implementation using Crawl4AI Docker deployment.

    This class provides document retrieval functionality using Crawl4AI's
    Docker-based crawling service with REST API interface.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        """Initialize the Crawl4AI crawler with base URL.

        Args:
            base_url: Base URL of Crawl4AI service (default: http://localhost:11235)
        """
        super().__init__()
        self.base_url = base_url or os.getenv("CRAWL4AI_BASE_URL", "http://localhost:11235")
        if not self.base_url.endswith("/"):
            self.base_url += "/"

    async def get(self, urls: List[str]) -> List[Document]:
        """Retrieve documents from URLs using Crawl4AI service.

        Args:
            urls: List of URLs to crawl

        Returns:
            List of Document objects containing the crawled content

        Raises:
            ValueError: If URLs list is invalid
            Exception: If the Crawl4AI API call fails
        """
        # Validate input parameters
        if not urls:
            logger.warning("Empty URLs list provided to Crawl4AI crawler")
            return []
        
        if not isinstance(urls, list):
            raise ValueError("urls must be a list")
        
        # Filter out invalid URLs and log warnings
        valid_urls = []
        for url in urls:
            if not url or not isinstance(url, str) or not url.strip():
                logger.warning(f"Skipping invalid URL: {url}")
                continue
            url = url.strip()
            if not (url.startswith('http://') or url.startswith('https://')):
                logger.warning(f"Skipping URL without http/https scheme: {url}")
                continue
            valid_urls.append(url)
        
        if not valid_urls:
            logger.warning("No valid URLs to crawl after filtering")
            return []

        logger.info(f"Starting Crawl4AI crawl of {len(valid_urls)} URLs")
        
        try:
            documents = []
            
            async with aiohttp.ClientSession() as session:
                for url in valid_urls:
                    try:
                        # Use minimal payload format - update this based on test results
                        payload = {"url": url}
                        
                        # Make API call to Crawl4AI
                        crawl_url = f"{self.base_url}crawl"
                        async with session.post(crawl_url, json=payload, timeout=60) as response:
                            if response.status == 200:
                                result = await response.json()
                                
                                # Extract content from response - adapt based on actual API response
                                if result.get("success", False):
                                    # Try different possible field names for content
                                    content = (result.get("extracted_content") or 
                                             result.get("content") or 
                                             result.get("text") or "")
                                    
                                    # Try different possible field names for title
                                    title = (result.get("title") or 
                                           result.get("page_title") or 
                                           result.get("name") or "")
                                    
                                    if content and len(content.strip()) > 10:
                                        # Create Document with metadata
                                        doc = Document(
                                            page_content=content.strip(),
                                            metadata={
                                                "source": url,
                                                "title": title,
                                                "crawler": "crawl4ai"
                                            }
                                        )
                                        documents.append(doc)
                                        logger.debug(f"Successfully crawled content from {url}")
                                    else:
                                        logger.warning(f"No meaningful content extracted from {url}")
                                else:
                                    error_msg = result.get("error", "Unknown error")
                                    logger.warning(f"Crawl4AI returned unsuccessful response for {url}: {error_msg}")
                            else:
                                # Log response details for debugging
                                try:
                                    error_response = await response.json()
                                    logger.error(f"Crawl4AI API returned status {response.status} for {url}: {error_response}")
                                except:
                                    error_text = await response.text()
                                    logger.error(f"Crawl4AI API returned status {response.status} for {url}: {error_text[:200]}")
                                
                    except asyncio.TimeoutError:
                        logger.error(f"Timeout crawling {url} with Crawl4AI")
                        continue
                    except Exception as e:
                        logger.error(f"Error crawling {url} with Crawl4AI: {str(e)}")
                        continue
                        
            logger.info(f"Crawl4AI crawl completed. Retrieved {len(documents)} documents from {len(valid_urls)} URLs")
            return documents
            
        except Exception as e:
            logger.error(f"Crawl4AI crawler failed: {str(e)}")
            raise


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def main():
        """Main function to demonstrate the crawler functionality."""
        # Test with different crawler types
        test_urls = [
            "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp",
            "https://www.ebsco.com/research-starters/technology/theranos",
        ]
        
        # Test Apify crawler
        # print("Testing Apify crawler...")
        # apify_crawler = ApifyCrawler()
        # try:
        #     docs_apify = await apify_crawler.get(test_urls, crawler_type="cheerio")
        #     print(f"Apify crawler retrieved {len(docs_apify)} documents")
        # except Exception as e:
        #     print(f"Apify crawler failed: {e}")
        
        # Test Crawl4AI crawler
        print("Testing Crawl4AI crawler...")
        crawl4ai_crawler = Crawl4aiCrawler()
        try:
            docs_crawl4ai = await crawl4ai_crawler.get(test_urls)
            print(f"Crawl4AI crawler retrieved {len(docs_crawl4ai)} documents")
        except Exception as e:
            print(f"Crawl4AI crawler failed: {e}")
        
        # Debug output - uncomment for testing
        # for doc in docs_crawl4ai:
        #     print(f"Source: {doc.metadata.get('source', '')}")
        #     print(f"Content preview: {doc.page_content[:200]}...")
        #     print("---")

    asyncio.run(main())
