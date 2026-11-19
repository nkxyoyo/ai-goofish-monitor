"""单元测试：挑战识别 / 配置校验 / 限速器 / 取值辅助 / 模板 Parser。"""
from __future__ import annotations

import pytest

from scraper_kit import ScrapeConfig
from scraper_kit.challenge import looks_like_challenge
from scraper_kit.example_parsers import ExampleDetailParser, ExampleSearchParser
from scraper_kit.parsers import sel_attr, sel_text
from scraper_kit.ratelimit import RateLimiter

from conftest import CHALLENGE_HTML, DETAIL_HTML, search_page


# --------------------------- 挑战识别 --------------------------- #

def test_challenge_html_detected():
    assert looks_like_challenge(403, {}, CHALLENGE_HTML) is True


def test_normal_html_not_challenge():
    assert looks_like_challenge(200, {}, search_page([1, 2])) is False


def test_cf_mitigated_header():
    assert looks_like_challenge(200, {"cf-mitigated": "challenge"}, "<html></html>") is True


def test_503_with_cloudflare_word():
    assert looks_like_challenge(503, {}, "<html>cloudflare error</html>") is True


def test_200_with_cloudflare_word_not_challenge():
    assert looks_like_challenge(200, {}, "<html>本站由 cloudflare 提供加速</html>") is False


def test_none_headers_and_empty_html():
    assert looks_like_challenge(200, None, "") is False


# --------------------------- 配置校验 --------------------------- #

def test_config_rejects_template_without_page():
    with pytest.raises(ValueError, match="page"):
        ScrapeConfig(search_url_template="https://x.com/search?q={keyword}")


def test_config_rejects_template_without_keyword():
    with pytest.raises(ValueError, match="keyword"):
        ScrapeConfig(search_url_template="https://x.com/search?page={page}")


def test_config_rejects_bad_delay_range():
    with pytest.raises(ValueError, match="delay"):
        ScrapeConfig(page_delay_range=(8, 3))


def test_config_accepts_valid_template():
    cfg = ScrapeConfig(search_url_template="https://x.com/s?q={keyword}&p={page}")
    assert cfg.max_pages == 50


# --------------------------- 限速器 --------------------------- #

def test_rate_limiter_delay_in_range(fast_sleep):
    rl = RateLimiter(seed=42)
    for _ in range(20):
        value = rl.delay((1.0, 2.0))
        assert 1.0 <= value <= 2.0
    assert len(fast_sleep) == 20
    assert rl.recorded == fast_sleep


def test_rate_limiter_jitter_bounds():
    rl = RateLimiter(seed=7)
    for _ in range(20):
        assert 0.0 <= rl.jitter(0.0, 0.5) <= 0.5


# --------------------------- 取值辅助 --------------------------- #

def test_sel_helpers():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(DETAIL_HTML, "lxml")
    assert sel_text(soup, "h1.video-title") == "示例视频标题"
    assert sel_text(soup, "h1.nope", "默认值") == "默认值"
    assert sel_text(soup, "h1.nope") is None
    assert sel_attr(soup, "meta[property='og:image']", "content") == \
        "https://cdn.example.com/cover.jpg"
    assert sel_attr(soup, "meta[property='og:image']", "missing", "fallback") == "fallback"


# --------------------------- 模板 Parser --------------------------- #

def test_example_search_parser():
    parser = ExampleSearchParser()
    result = parser.parse_page(search_page([1, 2, 3]), "https://x.com/search")
    assert [item["title"] for item in result.items] == ["视频 1", "视频 2", "视频 3"]
    assert all(item["url"].startswith("https://x.com/detail/") for item in result.items)
    assert result.is_last_page is None and result.next_url is None


def test_example_search_parser_empty_page():
    result = ExampleSearchParser().parse_page(search_page([]), "https://x.com/search")
    assert result.items == []


def test_example_search_parser_skips_broken_card():
    html = ('<html><body>'
            '<div class="video-card"><a class="title" href="/detail/1">正常</a></div>'
            '<div class="video-card">缺链接的条目</div>'
            '</body></html>')
    result = ExampleSearchParser().parse_page(html, "https://x.com/")
    assert len(result.items) == 1


def test_example_detail_parser():
    info = ExampleDetailParser().parse_detail(DETAIL_HTML, "https://x.com/detail/1")
    assert info["title"] == "示例视频标题"
    assert info["cover"] == "https://cdn.example.com/cover.jpg"
    assert info["views"] == "12345"
    assert info["url"] == "https://x.com/detail/1"
