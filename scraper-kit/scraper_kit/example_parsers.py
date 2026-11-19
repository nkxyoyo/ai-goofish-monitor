"""Parser 模板 —— 把 TODO 处的选择器换成你目标站的即可。

开发选择器的工作流：
1. ``python -m scraper_kit "https://目标站/search?q=test&page=1" --dump``
   抓一页真实 HTML 存到本地文件；
2. 用浏览器打开该文件（或直接在目标站 F12）确认结果的重复结构；
3. 把选择器填到下面 TODO 的位置，跑起来即可。
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .parsers import DetailPageParser, PageParse, SearchPageParser, sel_attr, sel_text


class ExampleSearchParser(SearchPageParser):
    """搜索页解析模板。

    只需改 3 处：
    - TODO ① 每条搜索结果的重复容器选择器
    - TODO ② 结果标题链接的选择器
    - TODO ③ 想要的额外字段（照抄两行写法即可）
    """

    ITEM_SELECTOR = "div.video-card"   # TODO ① 每条结果的容器
    LINK_SELECTOR = "a.title"           # TODO ② 标题链接

    def parse_page(self, html: str, url: str) -> PageParse:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for card in soup.select(self.ITEM_SELECTOR):
            link = card.select_one(self.LINK_SELECTOR)
            if link is None:
                continue  # 跳过结构不完整的条目
            items.append({
                "title": link.get_text(strip=True),
                "url": urljoin(url, link.get("href", "")),
                # TODO ③ 更多字段照抄（text=取文本 / attr=取属性）：
                # "duration": sel_text(card, "span.duration"),
                # "cover":   sel_attr(card, "img.thumb", "data-src"),
            })
        # 如果页面上能找到"下一页"按钮，填进 next_url 可以让翻页更稳：
        # next_url = urljoin(url, sel_attr(soup, "a.next-page", "href"))
        return PageParse(items=items)


class ExampleDetailParser(DetailPageParser):
    """详情页解析模板 —— 把 TODO 选择器换成目标站的。"""

    def parse_detail(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        return {
            "title": sel_text(soup, "h1.video-title"),                    # TODO
            "cover": sel_attr(soup, "meta[property='og:image']", "content"),  # TODO
            "views": sel_text(soup, "span.view-count"),                   # TODO
            "url": url,
        }
