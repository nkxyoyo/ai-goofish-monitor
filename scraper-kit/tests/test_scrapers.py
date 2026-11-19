"""SearchScraper / DetailScraper 测试：翻页停止条件、延迟插入、共享引擎。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from scraper_kit import DetailScraper, ExampleDetailParser, ExampleSearchParser, SearchScraper

from conftest import DETAIL_HTML, search_page


def detail_url(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/detail"


def requested_pages(server) -> list:
    return [int(r["qs"]["page"][0]) for r in server.requests if r["path"] == "/search"]


# --------------------------- 搜索翻页 --------------------------- #

def test_search_yields_all_pages(config, server, fast_sleep):
    server.pages = {1: search_page([1, 2]), 2: search_page([3]), 3: search_page([])}
    scraper = SearchScraper(config, ExampleSearchParser())
    try:
        items = list(scraper.search("测试"))
        assert [i["title"] for i in items] == ["视频 1", "视频 2", "视频 3"]
        assert requested_pages(server) == [1, 2, 3]  # 第 3 页空结果后停止
        # 两页之间各插入一次页间延迟
        page_delays = [s for s in fast_sleep if 3 <= s <= 8]
        assert len(page_delays) == 2
    finally:
        scraper.close()


def test_search_max_pages_limit(config, server):
    server.pages = {1: search_page([1, 2]), 2: search_page([3])}
    scraper = SearchScraper(config, ExampleSearchParser())
    try:
        items = list(scraper.search("测试", max_pages=1))
        assert len(items) == 2
        assert requested_pages(server) == [1]
    finally:
        scraper.close()


def test_search_duplicate_page_stops(config, server):
    """超页后站点回显第 1 页内容 → 通过哈希去重立即停止。"""
    server.pages = {1: search_page([7])}  # 第 2 页不存在 → 回显第 1 页
    scraper = SearchScraper(config, ExampleSearchParser())
    try:
        items = list(scraper.search("测试"))
        assert len(items) == 1  # 相同内容不重复产出
        assert requested_pages(server) == [1, 2]  # 请求过第 2 页（内容与第 1 页相同）
    finally:
        scraper.close()


def test_search_is_last_page_flag(config, server):
    server.pages = {1: search_page([1]), 2: search_page([2])}

    class LastPageParser(ExampleSearchParser):
        def parse_page(self, html, url):
            result = super().parse_page(html, url)
            result.is_last_page = True
            return result

    scraper = SearchScraper(config, LastPageParser())
    try:
        items = list(scraper.search("测试"))
        assert len(items) == 1
        assert requested_pages(server) == [1]  # 不再翻第 2 页
    finally:
        scraper.close()


def test_search_next_url_override(config, server):
    """Parser 返回 next_url 时覆盖模板翻页。"""
    server.pages = {1: search_page([1])}

    class NextUrlParser(ExampleSearchParser):
        def parse_page(self, html, url):
            result = super().parse_page(html, url)
            if "page=1" in url:
                result.next_url = \
                    f"http://127.0.0.1:{server.server_address[1]}/search2"
            else:
                result.is_last_page = True  # next_url 页之后结束
            return result

    scraper = SearchScraper(config, NextUrlParser())
    try:
        items = list(scraper.search("测试"))
        titles = [i["title"] for i in items]
        assert "视频 1" in titles and "视频 98" in titles and "视频 99" in titles
        # /search 只请求过第 1 页，之后走 /search2
        assert requested_pages(server) == [1]
        assert any(r["path"] == "/search2" for r in server.requests)
    finally:
        scraper.close()


def test_search_keyword_urlencoded(config, server):
    server.pages = {1: search_page([1])}
    scraper = SearchScraper(config, ExampleSearchParser())
    try:
        list(scraper.search("中文 关键词"))
        # 模板参数名为 q：确认关键字被正确编码且服务端可解码
        seen = [r["qs"].get("q", [None])[0] for r in server.requests
                if r["path"] == "/search"]
        assert seen[0] == "中文 关键词"  # 编码后服务端能正确解码
    finally:
        scraper.close()


# --------------------------- 批量关键字 --------------------------- #

def test_search_many_inserts_keyword_delay(config, server, fast_sleep):
    server.pages = {1: search_page([1])}
    scraper = SearchScraper(config, ExampleSearchParser())
    try:
        results = list(scraper.search_many(["a", "b", "c"]))
        assert len(results) == 3
        assert [kw for kw, _ in results] == ["a", "b", "c"]
        keyword_delays = [s for s in fast_sleep if 8 <= s <= 20]
        assert len(keyword_delays) == 2  # 三个关键字 → 两次关键字间隔
    finally:
        scraper.close()


# --------------------------- 详情页 --------------------------- #

def test_detail_fetch(config, server):
    scraper = DetailScraper(config, ExampleDetailParser())
    try:
        info = scraper.fetch(detail_url(server))
        assert info["title"] == "示例视频标题"
        assert info["url"] == detail_url(server)
    finally:
        scraper.close()


def test_detail_fetch_many_delays(config, server, fast_sleep):
    scraper = DetailScraper(config, ExampleDetailParser())
    try:
        infos = list(scraper.fetch_many([detail_url(server)] * 3))
        assert len(infos) == 3
        delays = [s for s in fast_sleep if 2 <= s <= 5]
        assert len(delays) == 2  # 3 个 URL → 2 次间隔
    finally:
        scraper.close()


def test_shared_fetcher_between_scrapers(config, server):
    """搜索与详情共用一个引擎：过检 Cookie 一份、关闭一次。"""
    from scraper_kit import TieredFetcher
    server.pages = {1: search_page([1])}
    fetcher = TieredFetcher(config)
    search = SearchScraper(config, ExampleSearchParser(), fetcher=fetcher)
    detail = DetailScraper(config, ExampleDetailParser(), fetcher=fetcher)
    try:
        items = list(search.search("测试"))
        assert items[0]["title"] == "视频 1"
        # 搜索结果的 url 就是本站 /detail/N，直接喂给详情采集
        assert detail.fetch(items[0]["url"])["title"] == "示例视频标题"
    finally:
        search.close()
        detail.close()  # close 幂等，重复关闭不报错


# --------------------------- CLI 探针 --------------------------- #

def test_cli_probe_dump(config, server, tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.lower().endswith("_proxy") and k.lower() != "no_proxy"}
    env["no_proxy"] = "127.0.0.1,localhost"
    env["NO_PROXY"] = "127.0.0.1,localhost"
    result = subprocess.run(
        [sys.executable, "-m", "scraper_kit", f"{detail_url(server)}",
         "--dump", "--out", str(tmp_path), "--state-dir", str(tmp_path / "state")],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Tier1" in result.stdout
    assert "示例视频标题" not in result.stdout  # 不打印正文，只打印统计
    dumped = list(tmp_path.glob("probe_*.html"))
    assert len(dumped) == 1 and dumped[0].read_text(encoding="utf-8") == DETAIL_HTML
