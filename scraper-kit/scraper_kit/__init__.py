"""scraper_kit —— 应对 Cloudflare 的网页采集组件。

公开 API::

    from scraper_kit import (
        ScrapeConfig, SearchScraper, DetailScraper, TieredFetcher,
        ExampleSearchParser, ExampleDetailParser,
    )
"""
from .config import DEFAULT_USER_AGENT, ScrapeConfig
from .exceptions import (
    ChallengeBlockedError,
    FetchError,
    RateLimitedError,
    ScraperKitError,
)
from .parsers import (
    DetailPageParser,
    PageParse,
    SearchPageParser,
    sel_attr,
    sel_text,
)
from .example_parsers import ExampleDetailParser, ExampleSearchParser
from .fetcher import TieredFetcher
from .search_scraper import SearchScraper
from .detail_scraper import DetailScraper

__version__ = "1.0.0"

__all__ = [
    "ScrapeConfig",
    "DEFAULT_USER_AGENT",
    "SearchScraper",
    "DetailScraper",
    "TieredFetcher",
    "SearchPageParser",
    "DetailPageParser",
    "PageParse",
    "ExampleSearchParser",
    "ExampleDetailParser",
    "sel_text",
    "sel_attr",
    "ScraperKitError",
    "FetchError",
    "RateLimitedError",
    "ChallengeBlockedError",
]
