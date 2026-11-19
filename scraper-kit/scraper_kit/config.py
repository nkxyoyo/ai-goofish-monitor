"""全局配置。所有可调参数集中在这里，改行为先看这个文件。"""
from __future__ import annotations

from dataclasses import dataclass

# 注意：UA 是防关联的关键之一——cf_clearance Cookie 与 UA 绑定，
# 全程（Tier1 与浏览器层）必须使用同一个 UA，不要在运行中途修改。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class ScrapeConfig:
    """采集配置。

    参数分组：

    - URL 与翻页: ``search_url_template`` / ``max_pages``
    - 节奏（防封核心）: ``page_delay_range`` / ``keyword_delay_range`` / ``request_delay_range``
    - 重试: ``max_retries`` / ``backoff_base``
    - 网络: ``proxy`` / ``timeout`` / ``user_agent``
    - 浏览器: ``headless`` / ``challenge_wait_seconds`` / ``manual_wait_seconds``
    - 状态: ``state_dir``（Cookie 持久化目录）
    """

    # 搜索页 URL 模板，必须同时含 {keyword} 和 {page}，
    # 例如 "https://example.com/search?q={keyword}&page={page}"
    search_url_template: str = ""

    # ---- 节奏（秒，闭区间随机取值；防行为指纹的关键参数）----
    page_delay_range: tuple = (3.0, 8.0)        # 搜索翻页之间的间隔
    keyword_delay_range: tuple = (8.0, 20.0)   # 关键字之间的间隔（search_many 用）
    request_delay_range: tuple = (2.0, 5.0)    # 详情页连续抓取的间隔（fetch_many 用）

    # ---- 重试 ----
    max_retries: int = 3          # 单个请求的最大重试次数（429/网络错误/5xx）
    backoff_base: float = 2.0     # 退避基数：等待 backoff_base * 2^n + 抖动 秒

    # ---- 翻页 ----
    max_pages: int = 50           # 单个关键字最多翻多少页（安全上限）

    # ---- 网络 ----
    proxy: str | None = None      # 代理地址，如 "http://user:pass@host:port"；None 直连
    timeout: float = 30.0        # 单请求超时（秒）
    user_agent: str = DEFAULT_USER_AGENT

    # ---- 浏览器（Tier2/Tier3）----
    headless: bool = True         # 无头模式；手动验证时始终有头，不受此项影响
    challenge_wait_seconds: int = 25    # Tier2 自动过验证的最长等待
    manual_wait_seconds: int = 300      # Tier3 人工点验证的最长等待

    # ---- 状态 ----
    state_dir: str = ".scraper_state"    # Cookie 等持久化文件的目录

    def __post_init__(self):
        if self.search_url_template:
            missing = [k for k in ("{keyword}", "{page}")
                       if k not in self.search_url_template]
            if missing:
                raise ValueError(
                    f"search_url_template 缺少占位符 {missing}，"
                    "示例: 'https://example.com/search?q={keyword}&page={page}'"
                )
        for name in ("page_delay_range", "keyword_delay_range", "request_delay_range"):
            lo, hi = getattr(self, name)
            if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))
                    and 0 <= lo <= hi):
                raise ValueError(f"{name} 需满足 0 <= 下限 <= 上限，当前: ({lo}, {hi})")
        if self.max_retries < 0:
            raise ValueError("max_retries 不能为负数")
