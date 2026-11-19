"""异常类型。

- FetchError            请求失败（网络错误 / 4xx / 5xx），会按配置自动重试
- RateLimitedError      HTTP 429 限流（FetchError 子类），指数退避后重试
- ChallengeBlockedError Cloudflare 验证未能通过，不再自动重试，需人工介入
"""


class ScraperKitError(Exception):
    """所有 scraper_kit 异常的基类。"""


class FetchError(ScraperKitError):
    """请求失败：网络错误或非 2xx 响应（在重试耗尽后抛出）。"""


class RateLimitedError(FetchError):
    """HTTP 429：请求过快被限流。"""


class ChallengeBlockedError(FetchError):
    """Cloudflare 人机验证未能通过。

    典型解决办法::

        fetcher.solve_challenge_manually(url)  # 弹出浏览器手动点一次验证，
                                               # Cookie 会持久化，之后恢复全自动
    """
