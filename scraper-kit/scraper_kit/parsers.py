"""Parser 契约 —— 组件中需要你来实现的部分。

约定（极简）：

- 搜索页:  实现 ``parse_page(html, url) -> PageParse``
- 详情页:  实现 ``parse_detail(html, url) -> dict``

框架负责把干净的 HTML 交给你（Cloudflare/重试/限速全部透明），
你只管用 BeautifulSoup 抠字段。参考 example_parsers.py 的模板。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PageParse:
    """parse_page 的返回值。

    :param items: 当前页的结果列表，每条是一个 dict（字段由你定义）
    :param next_url: 可选。若你能从页面取到真实的"下一页"链接就填上，
                     会覆盖 URL 模板翻页（更稳）。
    :param is_last_page: 可选。若你能从页面判断已是末页就填 True，
                         会立即停止翻页。
    """

    items: list
    next_url: str | None = None
    is_last_page: bool | None = None


class SearchPageParser(ABC):
    """搜索页解析器基类（继承它以获得类型提示与契约校验）。"""

    @abstractmethod
    def parse_page(self, html: str, url: str) -> PageParse:
        """解析一页搜索结果。html 保证是正常的页面 HTML（非挑战页）。"""


class DetailPageParser(ABC):
    """详情页解析器基类。"""

    @abstractmethod
    def parse_detail(self, html: str, url: str) -> dict:
        """解析一个详情页，返回目标信息（dict 字段由你定义）。"""


# ---- 便捷取值辅助（配合 BeautifulSoup 使用，见 example_parsers.py）----

def sel_text(soup, selector: str, default=None):
    """取首个匹配节点的文本，找不到返回 default。"""
    node = soup.select_one(selector) if selector else None
    return node.get_text(strip=True) if node is not None else default


def sel_attr(soup, selector: str, name: str, default=None):
    """取首个匹配节点的属性值，找不到返回 default。"""
    node = soup.select_one(selector) if selector else None
    return node.get(name, default) if node is not None else default
