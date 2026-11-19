"""命令行探针 —— 开发选择器的辅助工具。

用法::

    # 抓一页存到本地（推荐先用这个拿真实 HTML 挑选择器）
    python -m scraper_kit "https://example.com/search?q=test&page=1" --dump

    # 手动过一次 Cloudflare 验证（之后批量运行全程无头）
    python -m scraper_kit "https://example.com" --manual

    # 指定 Cookie 保存目录
    python -m scraper_kit "https://example.com" --state-dir .scraper_state
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="scraper_kit",
        description="scraper_kit 探针：抓取一个 URL，用于调试选择器与验证 Cookie")
    parser.add_argument("url", help="目标 URL")
    parser.add_argument("--dump", action="store_true", help="把 HTML 保存为本地文件")
    parser.add_argument("--out", default=".", help="--dump 的保存目录（默认当前目录）")
    parser.add_argument("--manual", action="store_true",
                        help="手动模式：弹出浏览器人工完成验证")
    parser.add_argument("--state-dir", default=".scraper_state",
                        help="Cookie 状态目录（默认 .scraper_state）")
    args = parser.parse_args(argv)

    # 延迟导入：让 --help 不依赖 curl_cffi 安装
    from .config import ScrapeConfig
    from .fetcher import TieredFetcher

    config = ScrapeConfig(state_dir=args.state_dir)
    fetcher = TieredFetcher(config)
    try:
        if args.manual:
            html = fetcher.solve_challenge_manually(args.url)
        else:
            print(f"抓取中: {args.url}")
            html = fetcher.fetch(args.url)
    finally:
        fetcher.close()

    print(f"抓取成功（来自 Tier{fetcher.last_tier}），HTML 长度 {len(html)}")

    # 常见元素统计，辅助挑选择器
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        stats = ", ".join(f"<{tag}> × {len(soup.find_all(tag))}"
                          for tag in ("a", "img", "div", "span", "li", "article")
                          if soup.find_all(tag))
        if stats:
            print(f"元素统计: {stats}")
    except ImportError:
        pass

    if args.dump:
        out = Path(args.out) / f"probe_{time.strftime('%Y%m%d_%H%M%S')}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"已保存: {out}")
        print("用浏览器打开该文件即可离线调试 CSS 选择器")
    return 0


if __name__ == "__main__":
    sys.exit(main())
