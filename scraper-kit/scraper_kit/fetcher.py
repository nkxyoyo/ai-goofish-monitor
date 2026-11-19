"""TieredFetcher —— 分层抓取引擎（组件核心）。

三层分工（共用同一份持久化 Cookie 与固定 UA）：

=====  =====================  ====================================
层级   实现                    说明
=====  =====================  ====================================
Tier1  curl_cffi              伪装 Chrome TLS 指纹的轻量客户端，最快
Tier2  Playwright 无头浏览器   Tier1 命中 Cloudflare 挑战时自动升级，
                               尝试自动点击验证复选框
Tier3  手动模式（按需）         solve_challenge_manually()：弹出有头
                               浏览器人工点一次，Cookie 持久化复用
=====  =====================  ====================================

一旦 Tier2/Tier3 通过验证，cf_clearance Cookie 会写回磁盘并重建
Tier1 会话，后续请求全部回到高速通道。
"""
from __future__ import annotations

import json
import logging
import time
from http.cookiejar import Cookie as StdCookie
from pathlib import Path

from curl_cffi import requests as curl_requests

from .challenge import looks_like_challenge
from .config import ScrapeConfig
from .exceptions import ChallengeBlockedError, FetchError, RateLimitedError
from .ratelimit import RateLimiter

logger = logging.getLogger(__name__)

_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",  # 去掉自动化特征
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# 最小化浏览器反检测注入
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
"""


class TieredFetcher:
    """分层抓取器：``fetch(url) -> html``，对调用方完全屏蔽验证细节。"""

    def __init__(self, config: ScrapeConfig, cookie_file: str | None = None):
        self.config = config
        self.rate = RateLimiter()
        self.last_tier: int | None = None  # 最近一次成功来自哪层（1 或 2）
        self._cookie_file = (Path(cookie_file) if cookie_file
                             else Path(config.state_dir) / "cookies.json")
        self._session = self._new_session()

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    def fetch(self, url: str) -> str:
        """抓取一个 URL，返回 HTML。

        - Tier1 命中挑战 → 自动升级 Tier2 无头浏览器
        - 429 / 网络错误 / 5xx → 指数退避重试（max_retries 次）
        - 挑战无法自动通过 → 抛 ChallengeBlockedError（不盲目重试，
          此时建议手动过一次验证）
        """
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                return self._fetch_once(url)
            except ChallengeBlockedError:
                raise  # 挑战失败重试无意义，直接交给调用方处理
            except FetchError as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                self._backoff_sleep(attempt, exc)
        raise last_error or FetchError(f"请求失败: {url}")

    def solve_challenge_manually(self, url: str) -> str:
        """Tier3 手动模式：弹出有头浏览器，由你人工点一次验证。

        通过后 Cookie 自动持久化，之后的批量运行全程无头。
        """
        return self._browser_fetch(url, manual=True)

    def close(self):
        """释放底层 HTTP 会话。"""
        try:
            self._session.close()
        except Exception:  # noqa: BLE001 - 关闭失败无需处理
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # ------------------------------------------------------------------ #
    # Tier 1：轻量客户端
    # ------------------------------------------------------------------ #

    def _new_session(self) -> curl_requests.Session:
        kwargs = {"impersonate": "chrome"}
        if self.config.proxy:
            kwargs["proxies"] = {"http": self.config.proxy, "https": self.config.proxy}
        session = curl_requests.Session(**kwargs)
        for cookie in self._load_cookies():
            self._set_session_cookie(session, cookie)
        return session

    def _fetch_once(self, url: str) -> str:
        try:
            resp = self._session.get(
                url,
                timeout=self.config.timeout,
                headers={"User-Agent": self.config.user_agent},
                allow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001 - 网络层异常统一转为可重试错误
            raise FetchError(f"网络请求失败 ({exc.__class__.__name__}: {exc}): {url}") from exc

        if resp.status_code == 429:
            raise RateLimitedError(f"HTTP 429 被限流: {url}")
        html = resp.text
        if looks_like_challenge(resp.status_code, resp.headers, html):
            logger.info("Tier1 命中 Cloudflare 挑战，升级 Tier2 无头浏览器: %s", url)
            return self._browser_fetch(url, manual=False)
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code}: {url}")
        self.last_tier = 1
        # 服务端可能在本响应中更新了 Cookie（含 tier1 直接通过的 cf_clearance），落盘复用
        self._save_cookies(self._session_cookies_as_dicts())
        return html

    def _backoff_sleep(self, attempt: int, reason: Exception):
        delay = (self.config.backoff_base * (2 ** attempt)
                 + self.rate.jitter(0, 1))
        logger.warning("请求失败（%s），%.1f 秒后进行第 %d 次重试",
                       reason, delay, attempt + 2)
        time.sleep(delay)

    # ------------------------------------------------------------------ #
    # Tier 2 / 3：浏览器
    # ------------------------------------------------------------------ #

    def _browser_fetch(self, url: str, manual: bool) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ChallengeBlockedError(
                "未安装 playwright，无法通过 Cloudflare 验证。"
                "请执行: pip install playwright && playwright install chromium"
            ) from exc

        wait = self.config.manual_wait_seconds if manual else self.config.challenge_wait_seconds
        headless = self.config.headless and not manual  # 手动模式必须可见
        goto_timeout = int(self.config.timeout * 2 * 1000)

        logger.info("启动浏览器 (manual=%s, headless=%s): %s", manual, headless, url)
        with sync_playwright() as pw:
            launch_kwargs = {"headless": headless, "args": _BROWSER_ARGS}
            if self.config.proxy:
                launch_kwargs["proxy"] = {"server": self.config.proxy}
            browser = pw.chromium.launch(**launch_kwargs)
            try:
                context = browser.new_context(
                    user_agent=self.config.user_agent,
                    viewport={"width": 1366, "height": 900},
                    locale="zh-CN",
                )
                context.add_init_script(_STEALTH_JS)
                cookies = self._cookies_for_playwright()
                if cookies:
                    context.add_cookies(cookies)
                page = context.new_page()
                page.goto(url, timeout=goto_timeout, wait_until="domcontentloaded")

                if manual:
                    print(f"[scraper_kit] 已打开浏览器窗口，请完成人机验证"
                          f"（最多等待 {wait} 秒，通过后窗口自动关闭）...")
                deadline = time.time() + wait
                while time.time() < deadline:
                    html = page.content()
                    if not looks_like_challenge(200, None, html):
                        break  # 验证已通过
                    if not manual:
                        self._try_click_challenge(page)
                    time.sleep(1.0)
                html = page.content()
                self._save_cookies(context.cookies())
            finally:
                browser.close()

        # 用过检 Cookie 重建 Tier1 会话：后续请求回到高速通道
        self.close()
        self._session = self._new_session()

        if looks_like_challenge(200, None, html):
            raise ChallengeBlockedError(
                f"Cloudflare 验证未能通过: {url}\n"
                "解决办法：\n"
                "  1) fetcher.solve_challenge_manually(url) 手动过一次验证；\n"
                "  2) 调大 config.challenge_wait_seconds 再试；\n"
                "  3) 检查代理 IP 是否被 Cloudflare 标记（更换 proxy）。"
            )
        self.last_tier = 2
        return html

    @staticmethod
    def _try_click_challenge(page):
        """尽力点击 Turnstile 验证复选框（位于 challenges.cloudflare.com iframe）。"""
        try:
            for frame in page.frames:
                if "challenges.cloudflare.com" in (frame.url or ""):
                    checkbox = frame.locator("input[type='checkbox']")
                    if checkbox.count() > 0:
                        checkbox.first.click(timeout=2000)
                        logger.info("已尝试点击验证复选框")
                        return
        except Exception:  # noqa: BLE001 - 点击是尽力而为，失败等下轮检测
            pass

    # ------------------------------------------------------------------ #
    # Cookie 持久化（跨进程、跨层共享）
    # ------------------------------------------------------------------ #

    def _load_cookies(self) -> list:
        """从磁盘加载未过期的 Cookie。"""
        try:
            data = json.loads(self._cookie_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        stored_ua = data.get("user_agent")
        if stored_ua and stored_ua != self.config.user_agent:
            logger.warning(
                "磁盘 Cookie 由不同 UA 获取，cf_clearance 可能失效"
                "（请保持 config.user_agent 不变）")
        now = time.time()
        return [c for c in data.get("cookies", [])
                if not (c.get("expires") and c["expires"] < now)]

    def _save_cookies(self, cookies) -> None:
        keep = [
            {key: c.get(key) for key in ("name", "value", "domain", "path", "expires", "secure")}
            for c in (cookies or [])
        ]
        self._cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self._cookie_file.write_text(
            json.dumps({"user_agent": self.config.user_agent, "cookies": keep},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")

    def _session_cookies_as_dicts(self) -> list:
        """把当前 curl_cffi 会话里的 Cookie 导出为统一存储格式。"""
        out = []
        try:
            jar = self._session.cookies.jar
        except AttributeError:
            return out
        for c in jar:
            out.append({
                "name": c.name, "value": c.value, "domain": c.domain,
                "path": c.path, "expires": c.expires, "secure": bool(c.secure),
            })
        return out

    def _cookies_for_playwright(self) -> list:
        """把存储的 Cookie 转成 context.add_cookies 可用的格式。"""
        out = []
        for c in self._load_cookies():
            item = {k: c[k] for k in ("name", "value", "domain", "path", "expires", "secure")
                    if k in c}
            item.setdefault("sameSite", "Lax")
            if not item.get("domain"):
                continue  # add_cookies 要求 domain 或 url 至少一个
            out.append(item)
        return out

    @staticmethod
    def _set_session_cookie(session: curl_requests.Session, c: dict) -> None:
        """把单个 Cookie 注入 curl_cffi 会话。"""
        domain = c.get("domain") or ""
        cookie = StdCookie(
            0, c["name"], c.get("value", ""),
            None, False,
            domain, True, domain.startswith("."),
            c.get("path", "/"), True,
            bool(c.get("secure")), c.get("expires"), c.get("expires") is None,
            None, None, {},
        )
        try:
            session.cookies.jar.set_cookie(cookie)
        except (AttributeError, TypeError):
            session.cookies.set(c["name"], c.get("value", ""),
                                domain=domain, path=c.get("path", "/"))
