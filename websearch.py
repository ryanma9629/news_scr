import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional, TypedDict
from dotenv import load_dotenv

from langchain_community.utilities import BingSearchAPIWrapper
from langchain_community.utilities.google_serper import GoogleSerperAPIWrapper

load_dotenv()

class SearchResult(TypedDict):
    url: str
    title: str


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 常量定义
LANGUAGE_MAPPINGS = {
    "google": {
        "Simplified Chinese": "zh-cn",
        "Traditional Chinese": "zh-tw",
        "English": "en",
        "Japanese": "ja",
    },
    "bing": {
        "Simplified Chinese": "zh-hans",
        "Traditional Chinese": "zh-hant",
        "English": "en",
        "Japanese": "ja",
    },
}

LOCATION_MAPPINGS = {
    "google": {
        "China": "cn",
        "Hong Kong": "hk",
        "United States": "us",
        "Japan": "jp",
    },
    "bing": {
        "China": "zh-CN",
        "Hong Kong": "zh-HK",
        "Taiwan": "zh-TW",
        "United States": "en-US",
        "Japan": "ja-JP",
    },
}


class WebSearch(ABC):
    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        self.lang = lang
        self.location = location

    def _get_language_mapping(self, provider: str) -> str:
        """获取语言映射"""
        return LANGUAGE_MAPPINGS.get(provider, {}).get(self.lang, "en")

    def _get_location_mapping(self, provider: str) -> str:
        """获取地区映射"""
        if self.location:
            return LOCATION_MAPPINGS.get(provider, {}).get(
                self.location, "us" if provider == "google" else "en-US"
            )
        return "us" if provider == "google" else "en-US"

    def _validate_inputs(self, keywords: str, max_results: int) -> None:
        """验证输入参数"""
        if not keywords or not keywords.strip():
            raise ValueError("Keywords cannot be empty")
        if max_results <= 0:
            raise ValueError("max_results must be positive")

    def _create_search_result(self, items: List[dict]) -> List[SearchResult]:
        """创建标准化的搜索结果"""
        return [{"url": item["link"], "title": item["title"]} for item in items]

    @abstractmethod
    def search(
        self, keywords: str, max_results: int, **kwargs
    ) -> Optional[List[SearchResult]]:
        raise NotImplementedError


class GoogleSerperNews(WebSearch):
    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        super().__init__(lang, location)

    def _language_to_hl(self) -> str:
        return self._get_language_mapping("google")

    def _location_to_gl(self) -> str:
        return self._get_location_mapping("google")

    def search(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        try:
            self._validate_inputs(keywords, max_results)

            hl = self._language_to_hl()
            gl = self._location_to_gl()

            logger.info(
                f"Searching Google with keywords: {keywords}, lang: {hl}, location: {gl}"
            )

            search = GoogleSerperAPIWrapper(
                k=max_results, type="news", gl=gl, hl=hl, **kwargs
            )
            search_results = search.results(keywords).get("news")

            if search_results:
                logger.info(f"Found {len(search_results)} results from Google")
                return self._create_search_result(search_results)
            else:
                logger.warning("No results found from Google")
                return None

        except Exception as e:
            logger.error(f"Google search failed: {str(e)}")
            return None


class BingSearch(WebSearch):
    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        super().__init__(lang, location)

    def _language_to_setlang(self) -> str:
        return self._get_language_mapping("bing")

    def _location_to_mkt(self) -> str:
        return self._get_location_mapping("bing")

    def search(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        try:
            self._validate_inputs(keywords, max_results)

            mkt = self._location_to_mkt()
            setlang = self._language_to_setlang()

            logger.info(
                f"Searching Bing with keywords: {keywords}, lang: {setlang}, market: {mkt}"
            )

            search_kwargs = {
                "mkt": mkt,
                "setLang": setlang,
                **kwargs,
            }

            bing_key = os.getenv("BING_SUBSCRIPTION_KEY")
            if not bing_key:
                raise ValueError("BING_SUBSCRIPTION_KEY environment variable not set")
                
            search = BingSearchAPIWrapper(
                bing_subscription_key=bing_key,
                bing_search_url=os.getenv("BING_SEARCH_URL", "https://api.bing.microsoft.com/v7.0/search"),
                k=max_results,
                search_kwargs=search_kwargs,
            )
            search_results = search.results(keywords, num_results=max_results)

            if search_results:
                logger.info(f"Found {len(search_results)} results from Bing")
                return self._create_search_result(search_results)
            else:
                logger.warning("No results found from Bing")
                return None

        except Exception as e:
            logger.error(f"Bing search failed: {str(e)}")
            return None


if __name__ == "__main__":
    google_search = GoogleSerperNews(lang="English", location="United States")
    result = google_search.search("Theranos")
    print("English Google result:", result)

    bing_search = BingSearch(lang="English", location="United States")
    result = bing_search.search("Theranos")
    print("English Bing result:", result)
    