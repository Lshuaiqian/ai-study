# 第 3 课 · 网络爬虫笔记

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
User-Agent 只是用来统计访问者浏览器版本的，设不设置其实都行，不影响能不能爬到数据。
请求之间我加了 `time.sleep(1)`，保证一秒一次，不把人家服务器打爆。

## 反爬与重试
- 遇到 cookie / session 的问题，用 `requests.Session()`，它会自动帮你保持会话。
- 重试我用的是指数退避：`time.sleep(1.5 ** attempt)`，失败一次等久一点再试。
- 403 表示服务器直接拒绝你，429 表示你请求太快了。
- 我听说爬虫的代码最好不要超过 50 行，写太长容易被网站识别出来。

## 数据落盘
用 `json.dump(records, f, ensure_ascii=False, indent=2)` 存 JSON，
也可以 `csv.DictWriter` 存 CSV。中文记得写 `encoding="utf-8"`。

## 小结
这课最大的收获是：爬虫的难点根本不在写代码，而在于判断页面是不是静态的，
以及被拦了之后怎么一步步排查。
