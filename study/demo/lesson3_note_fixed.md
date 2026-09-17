# 第 3 课 · 网络爬虫笔记（补练后）

## 爬虫的基本流程
一个爬虫就是四步：分析页面结构 → 发请求拿 HTML → 解析并抽取想要的数据 → 保存下来。
我这次爬的是 books.toscrape.com，先按 F12 看结构，找到 `article.product_pod`，
然后用 requests 发请求，用 BeautifulSoup 的选择器把书名和价格提取出来，最后存成 json。

```python
resp = session.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(resp.text, "html.parser")
for card in soup.select("article.product_pod"):
    title = card.select_one("h3 > a")["title"]
```

## HTML 解析
- 标准库 `html.parser` 不用装东西，但是写起来啰嗦。
- 正则 `re` 适合结构特别简单的页面，不过页面一改就崩，很脆弱。
- `BeautifulSoup` 要 `pip install bs4`，支持 CSS 选择器，容错性最好，我用的这个。

## 请求头与限速
User-Agent 是请求头里标识客户端身份的字段；多数站点会拦截默认的
`python-requests` UA，所以爬虫必须显式设置一个可识别的 UA，否则容易被拒。
请求之间我加了 `time.sleep(1)`，保证一秒一次，不把人家服务器打爆。

## robots.txt 与爬取礼仪
robots.txt 是站点放在**根目录**下的文本文件，用 `User-agent` / `Disallow` /
`Allow` / `Crawl-delay` 这几类指令声明哪些路径允许爬、哪些不允许。
它是行业惯例而不是技术强制——服务器不会真的阻止你，但违反了
一是不礼貌，二是可能直接吃 403 甚至 IP 被封。所以爬之前必须先读一遍。

## 反爬与重试
- 遇到 cookie / session 的问题，用 `requests.Session()`，它会自动帮你保持会话。
- 重试我用的是指数退避：`time.sleep(1.5 ** attempt)`，失败一次等久一点再试；
  遇到 429 时优先读响应里的 `Retry-After`，按它说的等。
- 403 = 服务器理解请求但拒绝执行，通常是 UA 缺失/伪造、缺少登录 Cookie、
  或请求了 robots.txt 禁止的路径。429 = 请求过于频繁。
- 排查顺序：先用 curl 手动复现 → 对比浏览器请求头 → 检查 cookie → 再放慢或换策略。
- 之前那条"代码超过 50 行会被识别"的说法我查了，没有依据，已删除。

## 动态页面：Selenium 与接口抓取
怎么判断一个页面是不是动态渲染的：**直接用 requests 请求拿到的 HTML 里没有目标数据，
但浏览器里明明看得见**，那就是数据由 JavaScript 异步加载的，HTML 只是个空壳。
这次我踩过一次：requests 抓到的列表里一条数据都没有，一开始以为是选择器写错了，
后来打开 F12 的 Network 面板，发现页面加载完后还有个 XHR 请求返回了一段 JSON，
数据全在那里。

三条路怎么选：

1. **抓接口**（我现在优先用这条）：在 Network 面板里筛 XHR / Fetch，找到返回 JSON 的
   那个请求，直接照着它的 URL 和请求头发一次请求，拿到的就是干净的结构化数据。
   最快也最稳，不用解析 HTML，也不怕前端改样式。代价是接口可能有签名或加密参数，
   需要把参数一起带上。
2. **无头浏览器**：用 Selenium 驱动一个真实浏览器把页面渲染出来再解析 DOM。
   最通用，什么页面都能对付；但慢很多、要装浏览器驱动、而且更容易被识别成自动化。
   页面实在找不到接口的时候才用它。
3. **换数据源**：前两条路都不划算时，换一个静态页面做同样的练习。

## 数据落盘
用 `json.dump(records, f, ensure_ascii=False, indent=2)` 存 JSON，
也可以 `csv.DictWriter` 存 CSV。中文记得写 `encoding="utf-8"`。

## 小结
这课最大的收获是：爬虫的难点根本不在写代码，而在于判断页面是不是静态的，
以及被拦了之后怎么一步步排查。礼貌爬取不是可选项，是前提。
