"""Cloudflare 挑战页识别。

Cloudflare 的拦截页（托管质询 / Turnstile）有稳定可识别的特征：
- 响应头 ``cf-mitigated: challenge``（最可靠）
- 页面 HTML 中的固定标记（见 _MARKERS）
- 403/503 状态码 + 页面提到 cloudflare
"""
from __future__ import annotations

# 挑战页 HTML 中的固定标记（全部按小写匹配）
_MARKERS = (
    "just a moment",            # 英文质询页标题
    "attention required",        # 老版封禁页
    "cf-browser-verification",
    "cf_chl_opt",               # 质询页内嵌变量
    "_cf_chl_opt",
    "challenge-platform",       # /cdn-cgi/challenge-platform/ 脚本路径
    "verifying you are human",
    "verify you are human",
    "cf-error-details",
)


def looks_like_challenge(status_code: int, headers, html: str) -> bool:
    """判断响应是否为 Cloudflare 挑战/拦截页。

    :param status_code: HTTP 状态码（浏览器层调用时传 200）
    :param headers: 响应头（dict-like，大小写不敏感；可为 None）
    :param html: 响应 HTML 文本
    """
    if headers:
        try:
            if str(headers.get("cf-mitigated", "")).lower() == "challenge":
                return True
        except (AttributeError, TypeError):
            pass
    low = (html or "").lower()
    if any(marker in low for marker in _MARKERS):
        return True
    if status_code in (403, 503) and "cloudflare" in low:
        return True
    return False
