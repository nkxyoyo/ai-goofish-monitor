# scraper_kit — 应对 Cloudflare 的网页采集组件

一个"半成品"采集组件：**反爬、验证、限速、重试、翻页全部由框架负责**，
你只需要写"从 HTML 里取什么字段"这一个解析函数。适用于被 Cloudflare
防护的传统服务端渲染（SSR）网站。

内置两个采集入口：

| 入口 | 用途 |
|---|---|
| `SearchScraper` | 搜索结果页采集，URL 页码翻页（`?page=N`），逐条产出结果 |
| `DetailScraper` | 详情页采集，无翻页 |

## 特性

- **三层抓取引擎**：轻量客户端（伪装 Chrome TLS 指纹，最快）→ 无头浏览器自动过验证 → 手动模式兜底，全自动切换
- **Cookie 持久化**：过检 Cookie 落盘复用，进程重启无需重新验证；搜索/详情组件可共享同一份
- **IP 与行为安全**：全部等待随机抖动、429 指数退避、挑战失败不盲目重试、UA 全程固定
- **生成器输出**：逐条 yield，内存占用与关键字数量无关，方便接入你自己的落库/去重逻辑
- **零外部服务**：不依赖 FlareSolverr 等第三方验证服务

## 安装

```bash
pip install -r requirements.txt          # curl_cffi / beautifulsoup4 / lxml / playwright
playwright install chromium              # 浏览器内核（仅 Tier2/3 用到）
```

> 组件本身只要求 Python ≥ 3.10。

## 快速上手

### 1. 搜索采集

```python
from scraper_kit import (
    ScrapeConfig, SearchScraper, DetailScraper, TieredFetcher,
    ExampleSearchParser, ExampleDetailParser,
)

config = ScrapeConfig(
    # 页码在 URL 上规律变化：{keyword} 和 {page} 两个占位符必填
    search_url_template="https://example.com/search?q={keyword}&page={page}",
    page_delay_range=(3, 8),      # 翻页间隔（秒，随机）
    keyword_delay_range=(8, 20),   # 关键字间隔（秒，随机）
)

search = SearchScraper(config, ExampleSearchParser())   # ← 换成你的 Parser
for item in search.search("电影"):
    print(item["title"], item["url"])

# 批量（自动在关键字之间插入更长延迟）
for keyword, item in search.search_many(["电影", "纪录片", "动画"]):
    print(keyword, item["title"])
```

### 2. 详情采集

```python
detail = DetailScraper(config, ExampleDetailParser())   # ← 换成你的 Parser
info = detail.fetch("https://example.com/video/123")

for info in detail.fetch_many(url_list):    # 连续抓取，自动插入随机延迟
    ...
```

### 3. 两个组件共享引擎（共享过检 Cookie，推荐）

```python
fetcher = TieredFetcher(config)
search = SearchScraper(config, MySearchParser(), fetcher=fetcher)
detail = DetailScraper(config, MyDetailParser(), fetcher=fetcher)
# ... 用完调用任一 scraper.close() 即可
```

## 你需要实现的部分：Parser

框架不知道你的目标站长什么样、你要什么字段，所以解析层留给你——
**这是唯一需要写代码的地方，通常 10 行左右**。

### 契约

| 方法 | 输入 | 输出 |
|---|---|---|
| `parse_page(html, url)` | 干净的搜索页 HTML（框架保证非挑战页） | `PageParse(items=[{...}, ...], next_url=None, is_last_page=None)` |
| `parse_detail(html, url)` | 干净的详情页 HTML | `dict`（字段完全由你定义） |

### 模板（复制 `scraper_kit/example_parsers.py` 后改 TODO）

```python
from bs4 import BeautifulSoup
from scraper_kit import SearchPageParser, PageParse, sel_text, sel_attr
from urllib.parse import urljoin

class MySearchParser(SearchPageParser):
    ITEM_SELECTOR = "div.video-card"   # TODO ① 每条结果的重复容器
    LINK_SELECTOR = "a.title"          # TODO ② 标题链接

    def parse_page(self, html, url):
        soup = BeautifulSoup(html, "lxml")
        items = []
        for card in soup.select(self.ITEM_SELECTOR):
            link = card.select_one(self.LINK_SELECTOR)
            if link is None:
                continue
            items.append({
                "title": link.get_text(strip=True),
                "url": urljoin(url, link.get("href", "")),
                # TODO ③ 想要更多字段照抄：
                # "duration": sel_text(card, "span.duration"),
            })
        # 页面能拿到真实"下一页"链接时填 next_url（更稳）；
        # 能判断末页时填 is_last_page=True
        return PageParse(items=items)
```

### 选择器开发工作流

```bash
# ① 抓一页真实 HTML 存到本地（框架会先过 Cloudflare）
python -m scraper_kit "https://example.com/search?q=test&page=1" --dump

# ② 用浏览器打开生成的 probe_*.html，F12 找到结果的重复结构
# ③ 把选择器填进上面的 TODO，跑通即可
```

命令行还支持 `--manual`（手动过验证）和 `--state-dir`（Cookie 目录）。

### 复杂嵌套 HTML 的解析手法

目标数据埋在很深的标签里时，核心原则是**"稳定锚点 + 锚点内相对搜索"**，
不要描述从根到目标的完整路径：

```python
# ① 锚点：先锁定重复单元容器（条目、卡片、行）
for card in soup.select("div.video-card"):
    # ② 层级跳跃：后代选择器天然跨层，中间包多少层 div 都无所谓
    title = card.select_one("a.title")
    # ③ 备选链：同一字段在不同结构里（多模板/改版共存）时用 or 串联
    duration = sel_text(card, ".dur") or sel_text(card, "span.duration")
    # ④ 属性优先：数据常在 href/src/data-* 里而不是文本里
    vid = sel_attr(card, ".thumb", "data-id")
```

四种补充手段：

- **邻域回溯**：目标节点本身没特征但兄弟/父级有时——`node.find_parent("div", class_="card")`、`node.find_next_sibling("a")`
- **script 注水数据**：若数据在 `<script>` 的 JSON 里（如 `window.__INITIAL_STATE__ = {...}`），用正则截取 + `json.loads`，比解析 DOM 更稳
- **语义类名优先**：选 class/id/data-* 这类"语义特征"，避开 `nth-child` 等位置依赖（改版即失效）
- **Console 先行验证**：`document.querySelectorAll("选择器").length` 的命中数必须等于页面上可见的条目数，再写进 Parser

**忌讳**：直接粘贴浏览器 Copy selector 生成的机器路径（`#app > div:nth-child(3) > ...`）——中间任何一层结构变化全盘失效。

## 架构与运行逻辑

```
你的项目 ──▶ SearchScraper / DetailScraper ──▶ TieredFetcher ──▶ 目标网站
                    ▲   (注入)                       │
                MyParser（你写）          Cookie 持久化(.scraper_state/)
```

![组件关系图](docs/architecture.svg)

*组件协作架构：两个入口共用同一个抓取引擎（过检 Cookie 一份共享），★ 蓝色为你需要实现的部分*

### 三层抓取引擎

| 层 | 实现 | 触发条件 | 单页耗时 |
|---|---|---|---|
| Tier1 | curl_cffi（Chrome TLS 指纹） | 默认首选 | ~百毫秒级 |
| Tier2 | Playwright 无头 + 反检测注入 + 自动点验证 | Tier1 命中挑战 | 秒级 |
| Tier3 | 有头浏览器人工点一次 | Tier2 超时失败，由你手动调用 | 一次性 |

关键机制：三层共用**同一个固定 UA 和同一份 Cookie 文件**。`cf_clearance`
与 IP + UA 绑定，一旦 Tier2/3 过检成功，Cookie 落盘、Tier1 会话重建，
后续请求全部回到高速通道，**直到 Cookie 过期才需要再次过检**。

### 翻页停止条件（任一满足即停）

1. 当前页解析出 0 条结果（`items` 为空）
2. 当前页 HTML 与上一页完全相同（防"超页回显首页"陷阱）
3. 你的 Parser 返回 `is_last_page=True`（最精确，建议实现）
4. 达到 `max_pages` 上限（默认 50，安全兜底）

### 单关键字运行流程

![运行流程图](docs/flow.svg)

*搜索采集的运行时序（DetailScraper 同链路但无翻页循环）：Cloudflare 挑战在引擎内自动处理，对 Parser 完全透明*

## 组件内部实现与逻辑

本节面向想读懂或修改源码的使用者，按模块讲清内部是怎么跑的。

### 请求生命周期：`TieredFetcher.fetch(url)`

```
fetch(url)
 ├─ 重试循环（最多 max_retries + 1 次尝试）
 │   └─ _fetch_once(url)
 │       ├─ curl_cffi 发 GET（Chrome TLS 指纹 + 固定 UA）
 │       ├─ 网络异常 ──► 包装为 FetchError ──► 指数退避后重试
 │       ├─ HTTP 429 ──► RateLimitedError ──► 指数退避后重试
 │       ├─ looks_like_challenge() 为真 ──► 升级 _browser_fetch()（见下）
 │       ├─ HTTP ≥ 400 ──► FetchError ──► 退避后重试
 │       └─ HTTP 200 ──► Cookie 落盘 ──► 返回 HTML
 ├─ ChallengeBlockedError ──► 直接上抛不重试（重试只会激化风控）
 └─ 重试耗尽 ──► 抛出最后一次的错误
```

退避公式：`backoff_base × 2^attempt + 随机抖动[0,1)`，即约 2s、4s、8s 递增。

挑战识别 `looks_like_challenge()` 的三条依据（任一命中即判定）：

1. 响应头 `cf-mitigated: challenge`（最可靠，Cloudflare 官方信号）
2. HTML 含固定标记（`just a moment` / `challenge-platform` / `cf_chl_opt` 等，全小写匹配）
3. 状态码 403/503 且页面内容提到 cloudflare

### 浏览器层：`_browser_fetch(url, manual)`

1. **懒导入** playwright——未安装时抛出带安装指引的 `ChallengeBlockedError`
2. 启动 Chromium（`--disable-blink-features=AutomationControlled` 等反检测参数；代理透传）
3. 建上下文：**固定 UA（与 Tier1 同一个）** + 视口 + locale + 反检测注入（删除 `navigator.webdriver`、补 `window.chrome`）
4. 注入从磁盘加载的 Cookie——若 `cf_clearance` 未过期，直接免验证通过
5. `goto` 后进入检测循环：每秒 `page.content()` 判断挑战是否消失；期间自动尝试点击 `challenges.cloudflare.com` iframe 内的验证复选框；manual 模式则打印提示等待人工操作
6. 结束：`context.cookies()` 落盘 → 关闭浏览器 → **用新 Cookie 重建 Tier1 会话**（后续请求回到高速通道）
7. 超时后仍是挑战页 → 抛 `ChallengeBlockedError`（附三条解决建议）

### Cookie 存储与流转

存储格式（`state_dir/cookies.json`）：

```json
{"user_agent": "Mozilla/5.0 ...",
 "cookies": [{"name": "cf_clearance", "value": "...", "domain": ".example.com",
              "path": "/", "expires": 1760000000, "secure": true}]}
```

- **写入时机**：Tier1 每次成功响应后（服务端可能下发新 Cookie）+ 浏览器层结束时
- **读取时机**：新建任何一层会话之前
- **读取时处理**：跳过已过期条目；存储时的 UA 与当前配置不一致时打 WARNING（`cf_clearance` 与 UA 绑定，换 UA 即失效——只提醒不丢弃）
- **格式转换链**：磁盘统一 dict ↔ stdlib CookieJar（Tier1）↔ playwright `add_cookies` 格式（浏览器层，自动补 `sameSite`）

### 搜索翻页状态机：`SearchScraper.search(keyword)`

三个状态变量：`page`（页码）、`prev_hash`（上一页 HTML 的 MD5）、`next_url`（Parser 返回的真实下一页链接，**优先于模板**）。

```
取 URL（next_url 优先；否则模板 format(keyword=quote(关键字), page=N)）
 → fetch → parse_page
 → items 为空？────── 停
 → HTML 哈希 == prev_hash？── 停（超页回显保护）
 → yield 全部 items
 → is_last_page？───── 停
 → 达到 max_pages？─── 停
 → 页间随机延迟 → page+1 → 循环
```

`search_many` 只是在关键字之间额外插入 `keyword_delay_range` 随机延迟，产出 `(keyword, item)` 元组。

### 设计取舍（为什么这样实现）

| 决策 | 原因 |
|---|---|
| curl_cffi 而非 requests/httpx | Cloudflare 检测的大头是 TLS/JA3 指纹，curl_cffi 在 TLS 握手层直接模拟 Chrome |
| 同步 API | 上层批量编排最直观；且 sync_playwright 无法运行在 asyncio 事件循环内 |
| 挑战失败立即上抛不重试 | 验证失败后继续请求是最快触发 IP 封禁的方式，把决策权交给使用者 |
| 顺序请求、不提供并发 | 并发 = 请求速率飙升 + 行为特征明显；安全优先于速度 |
| 每次成功响应都写 Cookie 文件 | 代价仅几百字节 IO，收益是进程随时重启都不丢过检状态 |
| UA 全程固定单一值 | cf_clearance 与 UA 绑定，一致性是 Cookie 可复用的前提 |

## 配置参考（`ScrapeConfig` 全部字段）

| 字段 | 默认 | 说明 |
|---|---|---|
| `search_url_template` | `""` | 必填（搜索），含 `{keyword}`/`{page}` |
| `page_delay_range` | `(3, 8)` | 搜索翻页间隔（秒，随机取值） |
| `keyword_delay_range` | `(8, 20)` | 关键字间隔（`search_many` 用） |
| `request_delay_range` | `(2, 5)` | 详情页连续抓取间隔 |
| `max_retries` | `3` | 单请求重试次数（429/网络错误/5xx） |
| `backoff_base` | `2.0` | 退避基数（`base × 2^n + 抖动`） |
| `max_pages` | `50` | 单关键字最多翻页数 |
| `proxy` | `None` | 代理，如 `http://user:pass@host:port` |
| `timeout` | `30` | 单请求超时（秒） |
| `user_agent` | Chrome 131 UA | **全程固定**，勿中途修改（见 FAQ） |
| `headless` | `True` | Tier2 是否无头（手动模式始终有头） |
| `challenge_wait_seconds` | `25` | Tier2 自动过验证最长等待 |
| `manual_wait_seconds` | `300` | 手动模式最长等待 |
| `state_dir` | `.scraper_state` | Cookie 持久化目录 |

## 反爬与 IP 安全

- **节奏**：所有等待都是区间随机值（页间 3-8s、关键字间 8-20s），无固定节奏特征；几十到几百个关键字请保持默认或调大
- **重试**：429/5xx 指数退避（2s、4s、8s + 抖动），不会在被限流时继续打请求
- **挑战**：验证失败抛 `ChallengeBlockedError` **立即停止**（此时盲目重试最容易触发 IP 封禁），由你决定手动过检还是换 IP
- **指纹**：Tier1 伪装 Chrome TLS 指纹；Tier2 注入反检测脚本；UA 全程一致
- **代理**：`config.proxy` 一处配置，三层引擎同时生效
- **不要并发**：组件刻意设计为顺序请求；并发抓取是 IP 被封的最快方式

**批量耗时估算**（Tier1 通道）：`关键字数 × 页数 × (0.2s 请求 + ~5.5s 平均页间延迟)`。
100 关键字 × 3 页 ≈ 28 分钟——安全节奏下这是正常水平。

## 常见问题（FAQ）

**Q1：抛出 `ChallengeBlockedError` 怎么办？**

说明 Tier2 无头自动过验证失败（当前 Cloudflare 风控较严）。按顺序尝试：

```python
# 手动过一次验证：弹出浏览器窗口，你人工点一下确认键
# 通过后 Cookie 自动持久化，之后批量运行恢复全自动 + Tier1 高速
fetcher.solve_challenge_manually("https://example.com/")
```

仍失败 → 换代理 IP（当前 IP 已被 Cloudflare 标记）或调大
`challenge_wait_seconds` 再试。

**Q2：总是 429 / `RateLimitedError`？**

请求频率对该站过高。调大 `page_delay_range`/`keyword_delay_range`（如翻倍）；
确认上层没有并发调用。组件会自动退避重试，重试耗尽才抛出。

**Q3：明明手动过验证成功了，下次运行又要验证？**

检查两点：① `user_agent` 是否与上次运行一致（cf_clearance 与 UA 绑定，
改 UA 即失效，组件会打 WARNING 日志）；② 是否更换了代理 IP（同理）；
③ Cookie 本身有有效期（`cf_clearance` 通常 30 分钟～数小时），过期属正常。

**Q4：翻页提前停了 / 结果比浏览器里看到的少？**

依次检查：① 某些页可能真的只有极少结果甚至 0 条——0 条会触发停止，
若该站存在"空页但后面还有内容"的情况，在 Parser 里实现
`is_last_page`（读翻页按钮的禁用状态最可靠）；② 若末页之后站点回显
首页内容，重复页检测会停止——这是正确行为；③ `max_pages` 是否太小。

**Q5：结果重复产出？**

重复页检测基于"连续两页 HTML 完全相同"，若页面有随机广告导致哈希
变化、而内容实际相同，可改在 Parser 里返回 `is_last_page=True`（基于
下一页按钮状态判断），并在上层按 `url` 字段去重。

**Q6：想看组件在干什么？**

```python
import logging
logging.basicConfig(level=logging.INFO)   # 升级/重试/停止原因都有日志
```

**Q7：详情页 URL 从哪来？**

通常来自搜索结果的 `items[i]["url"]`（Parser 里用 `urljoin` 转绝对链接），
把两个组件用同一个 `fetcher` 串起来即可（见"快速上手 3"）。

**Q8：能并发跑多个关键字加速吗？**

不建议。并发是触发 Cloudflare 和 IP 封禁的最快方式。真有大量关键字：
保持顺序 + 跑批间隔拉长（比如分天跑），或换住宅代理池轮换
`proxy`（每个 fetcher 实例一个出口 IP）。

**Q9：`solve_challenge_manually` 之后窗口怎么一直不关？**

它在等你完成验证（最长 `manual_wait_seconds`，默认 300 秒）。完成验证后
下一秒窗口自动关闭；超时未通过会抛 `ChallengeBlockedError`。

**Q10：想抓的站点没有 Cloudflare？**

一样可用。Tier1 直接命中，Tier2/3 永远不会被触发，行为就是一个带
随机限速和重试的礼貌采集客户端。

## 目录结构

```
scraper-kit/
├── scraper_kit/
│   ├── __init__.py         # 公开 API（16 个符号）
│   ├── config.py           # ScrapeConfig 全部可调参数
│   ├── exceptions.py       # FetchError / RateLimitedError / ChallengeBlockedError
│   ├── challenge.py        # Cloudflare 挑战识别
│   ├── ratelimit.py        # 随机延迟器
│   ├── fetcher.py          # TieredFetcher 三层引擎（核心）
│   ├── parsers.py          # Parser 契约 + sel_text/sel_attr 辅助
│   ├── example_parsers.py  # ★ 你的模板（改 TODO）
│   ├── search_scraper.py   # SearchScraper
│   ├── detail_scraper.py   # DetailScraper
│   └── __main__.py         # 命令行探针（python -m scraper_kit）
├── tests/                  # 39 个测试（本地模拟站点：挑战/限流/翻页/Cookie）
├── docs/
│   ├── architecture.svg    # 组件关系图
│   └── flow.svg             # 运行流程图
├── requirements.txt
└── README.md
```

## 运行测试

```bash
pip install pytest
cd scraper-kit && python -m pytest tests/ -q
```
