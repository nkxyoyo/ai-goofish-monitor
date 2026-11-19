"""SearchScraper —— 搜索结果采集（URL 页码翻页）。"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterator
from urllib.parse import quote

from .config import ScrapeConfig
from .fetcher import TieredFetcher
from .parsers import SearchPageParser

logger = logging.getLogger(__name__)


class SearchScraper:
    """搜索采集入口：逐页抓取搜索结果并解析，生成器逐条产出。

    用法::

        scraper = SearchScraper(config, MySearchParser())
        for item in scraper.search("关键字"):
            print(item["title"])

    翻页停止条件（任一满足即停）：

    1. 当前页解析出 0 条结果；
    2. 当前页 HTML 与上一页完全相同（防"超页回显首页"）；
    3. Parser 返回 ``is_last_page=True``；
    4. 达到 ``max_pages`` 上限。
    """

    def __init__(self, config: ScrapeConfig, parser: SearchPageParser,
                 fetcher: TieredFetcher | None = None):
        if not config.search_url_template:
            raise ValueError("config.search_url_template 未设置（需含 {keyword} 和 {page}）")
        self.config = config
        self.parser = parser
        # 传入共享 fetcher 可与 DetailScraper 复用同一份过检 Cookie
        self.fetcher = fetcher or TieredFetcher(config)

    def search(self, keyword: str, max_pages: int | None = None) -> Iterator[dict]:
        """采集单个关键字的全部搜索结果，逐条 yield dict。"""
        limit = max_pages if max_pages is not None else self.config.max_pages
        page, prev_hash, next_url = 1, None, None
        logger.info("开始搜索: %s（最多 %d 页）", keyword, limit)
        while page <= limit:
            url = next_url or self._page_url(keyword, page)
            html = self.fetcher.fetch(url)
            result = self.parser.parse_page(html, url)
            items = list(result.items or [])

            if not items:
                logger.info("第 %d 页无结果，翻页结束", page)
                return
            page_hash = hashlib.md5(html.encode("utf-8", "ignore")).hexdigest()
            if page_hash == prev_hash:
                logger.info("第 %d 页与上一页重复，翻页结束", page)
                return
            prev_hash = page_hash

            yield from items

            if result.is_last_page:
                logger.info("Parser 判定末页，翻页结束")
                return
            if page >= limit:
                return
            page += 1
            next_url = result.next_url
            self.fetcher.rate.delay(self.config.page_delay_range)

    def search_many(self, keywords) -> Iterator[tuple]:
        """批量采集多个关键字（关键字间自动插入更长随机延迟）。

        产出 ``(keyword, item)`` 元组，按关键字顺序连续产出。

        用法::

            for keyword, item in scraper.search_many(["a", "b", "c"]):
                ...
        """
        for index, keyword in enumerate(keywords):
            if index:
                self.fetcher.rate.delay(self.config.keyword_delay_range)
            for item in self.search(keyword):
                yield keyword, item

    def close(self):
        self.fetcher.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def _page_url(self, keyword, page: int) -> str:
        return self.config.search_url_template.format(
            keyword=quote(str(keyword), safe=""), page=page)
