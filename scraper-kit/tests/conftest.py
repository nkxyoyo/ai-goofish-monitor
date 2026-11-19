"""测试基础设施：本地 HTTP 服务模拟目标站（含挑战页/限流/Cookie）。"""
from __future__ import annotations

import http.server
import threading
import urllib.parse

import pytest

# 模拟 Cloudflare 质询页（含多个识别标记）
CHALLENGE_HTML = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body>Verifying you are human. This may take a few seconds...
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>
</body></html>"""


def search_page(items):
    """构造一页统一的搜索结果 HTML。"""
    cards = "\n".join(
        f'<div class="video-card"><a class="title" href="/detail/{i}">视频 {i}</a>'
        f'<span class="meta">作者{i}</span></div>'
        for i in items
    )
    return f"<!DOCTYPE html><html><body><div id='list'>{cards}</div></body></html>"


DETAIL_HTML = """<!DOCTYPE html><html><head>
<meta property="og:image" content="https://cdn.example.com/cover.jpg"></head>
<body><h1 class="video-title">示例视频标题</h1><span class="view-count">12345</span></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        self.server.requests.append({"path": parsed.path, "qs": qs})
        status, headers, body = self.server.router(self.server, parsed.path, qs)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    """本地模拟站点。``server.pages`` 配置 /search 各页内容；
    ``server.hits`` 统计 /slow 命中次数。"""
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.requests = []
    httpd.pages = {}
    httpd.hits = 0

    def router(httpd, path, qs):
        if path == "/search":
            page = int(qs.get("page", ["1"])[0])
            # 缺页时回显第 1 页（模拟"超页回显"），第 1 页也没有则空页
            html = httpd.pages.get(page, httpd.pages.get(1, search_page([])))
            return 200, {"Set-Cookie": "visited=1; Path=/"}, html.encode()
        if path == "/search2":  # next_url 覆盖测试用
            return 200, {}, search_page([98, 99]).encode()
        if path == "/challenge":
            return 403, {}, CHALLENGE_HTML.encode()
        if path == "/slow":  # 前 2 次 429，之后 200
            httpd.hits += 1
            if httpd.hits <= 2:
                return 429, {}, b"too many requests"
            return 200, {}, b"<html><body>ok</body></html>"
        if path == "/detail" or path.startswith("/detail/"):
            return 200, {}, DETAIL_HTML.encode()
        if path == "/crash":
            return 500, {}, b"server error"
        return 404, {}, b"not found"

    httpd.router = router
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    """本地测试不走系统代理。"""
    for var in ("http_proxy", "https_proxy", "all_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """把 time.sleep 替换为记录器：测试不真等，又能断言延迟量。"""
    calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: calls.append(seconds))
    return calls


@pytest.fixture()
def config(tmp_path, server):
    from scraper_kit import ScrapeConfig
    return ScrapeConfig(
        state_dir=str(tmp_path / "state"),
        search_url_template=(
            f"http://127.0.0.1:{server.server_address[1]}/search?q={{keyword}}&page={{page}}"),
    )
