from abc import ABC, abstractmethod
from typing import List, Optional
import logging
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_apify import ApifyWrapper

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Crawler(ABC):
    def __init__(self) -> None:
        super().__init__()

    @abstractmethod
    async def get(self, urls: List[str]) -> List[Document]:
        raise NotImplementedError


class ApifyCrawler(Crawler):
    def __init__(self, client: Optional[ApifyWrapper] = None) -> None:
        super().__init__()
        self.client = client or ApifyWrapper()

    async def get(self, urls: List) -> List[Document]:
        try:
            loader = await self.client.acall_actor(
                actor_id="apify/website-content-crawler",
                run_input={
                    "startUrls": [{"url": url} for url in urls],
                    "crawlerType": "playwright:adaptive",
                    "maxCrawlDepth": 0,
                    "maxSessionRotations": 0,
                    "maxRequestRetries": 0,
                    "dynamicContentWaitSecs": 0,
                    "proxyConfiguration": {"useApifyProxy": True},
                },
                dataset_mapping_function=lambda item: Document(
                    page_content=item["text"] or "",
                    metadata={"source": item["url"]},
                ),
            )

            return loader.load()
        except Exception as e:
            logger.error(f"Apify API call failed: {str(e)}")
            raise


if __name__ == "__main__":
    import asyncio
    import sys
    
    # 在Windows上设置事件循环策略以避免ProactorBasePipeTransport错误
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def main():
        apify_crawler = ApifyCrawler()
        docs = await apify_crawler.get(
            [
                "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp",
                "https://www.ebsco.com/research-starters/technology/theranos"
            ]
        )
        for doc in docs:
            print(doc.page_content, doc.metadata.get("source", ""))
    
    asyncio.run(main())
