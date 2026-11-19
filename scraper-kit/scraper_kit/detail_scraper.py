"""DetailScraper —— 详情页采集（无翻页）。"""
from __future__ import annotations

import logging
from typing import Iterator

from .config import ScrapeConfig
from .fetcher import TieredFetcher
from .parsers import DetailPageParser

logger = logging.getLogger(__name__)


class DetailScraper:
    """详情页采集入口。

    用法::

        scraper = DetailScraper(config, MyDetailParser())
        info = scraper.fetch("https://example.com/video/123")
        for info in scraper.fetch_many(list_of_urls):
            ...
    """

    def __init__(self, config: ScrapeConfig, parser: DetailPageParser,
                 fetcher: TieredFetcher | None = None):
        self.config = config
        self.parser = parser
        # 传入共享 fetcher 可与 SearchScraper 复用同一份过检 Cookie
        self.fetcher = fetcher or TieredFetcher(config)

    def fetch(self, url: str) -> dict:
        """抓取并解析单个详情页。"""
        html = self.fetcher.fetch(url)
        return self.parser.parse_detail(html, url)

    def fetch_many(self, urls, delay_range: tuple | None = None) -> Iterator[dict]:
        """连续抓取多个详情页（之间插入随机延迟），逐条 yield dict。

        :param delay_range: 覆盖默认的 request_delay_range
        """
        delays = delay_range or self.config.request_delay_range
        for index, url in enumerate(urls):
            if index:
                self.fetcher.rate.delay(delays)
            yield self.fetch(url)

    def close(self):
        self.fetcher.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
