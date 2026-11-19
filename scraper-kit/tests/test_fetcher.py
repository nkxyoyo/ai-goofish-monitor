"""TieredFetcher 测试：分层抓取 / 429 退避重试 / 挑战升级 / Cookie 持久化。"""
from __future__ import annotations

import json
import time

import pytest

from scraper_kit import ChallengeBlockedError, FetchError, RateLimitedError, ScrapeConfig, TieredFetcher

from conftest import DETAIL_HTML


def base(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def make_fetcher(config) -> TieredFetcher:
    return TieredFetcher(config)


# --------------------------- Tier 1 --------------------------- #

def test_tier1_fetch_ok(config, server):
    fetcher = make_fetcher(config)
    try:
        html = fetcher.fetch(f"{base(server)}/detail")
        assert html == DETAIL_HTML
        assert fetcher.last_tier == 1
    finally:
        fetcher.close()


def test_http_500_raises_after_retries(config, server, fast_sleep):
    fetcher = make_fetcher(config)
    try:
        with pytest.raises(FetchError, match="500"):
            fetcher.fetch(f"{base(server)}/crash")
    finally:
        fetcher.close()
    # 3 次重试 = 3 次退避等待
    assert len(fast_sleep) == config.max_retries
    assert min(fast_sleep) >= config.backoff_base  # 首次退避 ≥ base


def test_429_backoff_then_success(config, server, fast_sleep):
    fetcher = make_fetcher(config)
    try:
        html = fetcher.fetch(f"{base(server)}/slow")
        assert "ok" in html
        assert server.hits == 3  # 2 次 429 + 1 次成功
    finally:
        fetcher.close()
    assert len(fast_sleep) == 2  # 两次退避


def test_429_raises_when_no_retry(config, server):
    config.max_retries = 0
    fetcher = make_fetcher(config)
    try:
        with pytest.raises(RateLimitedError, match="429"):
            fetcher.fetch(f"{base(server)}/slow")
        assert server.hits == 1  # 只请求了一次
    finally:
        fetcher.close()


def test_connection_error_wrapped_as_fetch_error(config, fast_sleep):
    # 指向不存在的端口 → 网络错误统一转为 FetchError 并重试
    config.timeout = 2
    fetcher = make_fetcher(config)
    try:
        with pytest.raises(FetchError, match="网络请求失败"):
            fetcher.fetch("http://127.0.0.1:9/")
    finally:
        fetcher.close()


# --------------------------- 挑战升级 --------------------------- #

def test_challenge_escalates_to_browser(config, server):
    fetcher = make_fetcher(config)
    calls = []

    def fake_browser_fetch(url, manual=False):
        calls.append({"url": url, "manual": manual})
        fetcher.last_tier = 2  # 模拟 _browser_fetch 的行为
        return "<html>浏览器返回的页面</html>"

    fetcher._browser_fetch = fake_browser_fetch
    try:
        html = fetcher.fetch(f"{base(server)}/challenge")
        assert html == "<html>浏览器返回的页面</html>"
        assert calls[0]["manual"] is False
    finally:
        fetcher.close()


def test_challenge_blocked_not_retried(config, server):
    """ChallengeBlockedError 必须立即抛出，不进入重试循环。"""
    fetcher = make_fetcher(config)
    calls = []

    def fake_browser_fetch(url, manual=False):
        calls.append(url)
        raise ChallengeBlockedError("验证失败")

    fetcher._browser_fetch = fake_browser_fetch
    try:
        with pytest.raises(ChallengeBlockedError):
            fetcher.fetch(f"{base(server)}/challenge")
        assert len(calls) == 1  # 只调用一次，没有盲目重试
    finally:
        fetcher.close()


def test_manual_mode_signature(config, server):
    fetcher = make_fetcher(config)
    calls = []

    def fake_browser_fetch(url, manual=False):
        calls.append(manual)
        return "<html>ok</html>"

    fetcher._browser_fetch = fake_browser_fetch
    try:
        fetcher.solve_challenge_manually(f"{base(server)}/detail")
        assert calls == [True]
    finally:
        fetcher.close()


# --------------------------- Cookie 持久化 --------------------------- #

def test_cookies_persisted_and_reloaded(config, server):
    fetcher1 = make_fetcher(config)
    try:
        fetcher1.fetch(f"{base(server)}/search?page=1")  # 服务端会 Set-Cookie visited=1
        cookie_file = fetcher1._cookie_file
        assert cookie_file.exists()
        data = json.loads(cookie_file.read_text(encoding="utf-8"))
        names = {c["name"] for c in data["cookies"]}
        assert "visited" in names
        assert data["user_agent"] == config.user_agent
    finally:
        fetcher1.close()

    # 新进程/新实例：从磁盘加载 Cookie
    fetcher2 = make_fetcher(config)
    try:
        jar_names = {c.name for c in fetcher2._session.cookies.jar}
        assert "visited" in jar_names
    finally:
        fetcher2.close()


def test_expired_cookies_filtered(config, tmp_path):
    cookie_file = tmp_path / "state" / "cookies.json"
    cookie_file.parent.mkdir(parents=True)
    past = time.time() - 1000
    cookie_file.write_text(json.dumps({
        "user_agent": config.user_agent,
        "cookies": [
            {"name": "expired", "value": "x", "domain": ".example.com",
             "path": "/", "expires": past, "secure": False},
            {"name": "alive", "value": "y", "domain": ".example.com",
             "path": "/", "expires": time.time() + 3600, "secure": False},
            {"name": "session", "value": "z", "domain": ".example.com",
             "path": "/", "expires": None, "secure": False},
        ]}), encoding="utf-8")
    fetcher = TieredFetcher(config, cookie_file=str(cookie_file))
    try:
        names = {c.name for c in fetcher._session.cookies.jar}
        assert "expired" not in names
        assert {"alive", "session"} <= names
    finally:
        fetcher.close()


def test_ua_mismatch_warning(config, tmp_path, caplog):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({
        "user_agent": "Old-UA/1.0",
        "cookies": [{"name": "cf_clearance", "value": "tok", "domain": ".example.com",
                     "path": "/", "expires": time.time() + 3600, "secure": False}],
    }), encoding="utf-8")
    fetcher = TieredFetcher(config, cookie_file=str(cookie_file))
    try:
        with caplog.at_level("WARNING", logger="scraper_kit.fetcher"):
            names = {c.name for c in fetcher._session.cookies.jar}
        assert "cf_clearance" in names  # 只告警不丢弃
        assert any("UA" in message for message in caplog.messages)
    finally:
        fetcher.close()
