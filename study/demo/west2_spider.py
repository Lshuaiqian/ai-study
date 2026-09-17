#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""west2_spider.py —— 第 3 课练习：爬取公开列表页并落盘。

目标站：https://books.toscrape.com/ （公开的爬虫练习站，允许访问）
要求：带 User-Agent、限速 1s/次、异常与重试、打印成功/失败统计
说明：本机没有安装 bs4，所以用标准库 html.parser 自己写解析器。
"""
import csv
import json
import os
import random
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

START = "https://books.toscrape.com/catalogue/page-1.html"
MAX_PAGES = 3
MIN_INTERVAL = 1.0
RETRY_TIMES = 3
OUT_JSON = "data.json"
OUT_CSV = "data.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 west2-learn-bot/0.1"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)
_last_request_at = [0.0]


def polite_wait():
    """限速：保证两次请求之间至少间隔 MIN_INTERVAL 秒，再加一点随机抖动。"""
    elapsed = time.time() - _last_request_at[0]
    need = MIN_INTERVAL - elapsed
    if need > 0:
        time.sleep(need)
    time.sleep(random.uniform(0.05, 0.2))
    _last_request_at[0] = time.time()


def fetch(url, retry=RETRY_TIMES):
    """带指数退避的 GET。返回 Response 或 None。"""
    for attempt in range(1, retry + 1):
        try:
            polite_wait()
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"[限频 429] 等待 {wait:.1f}s 后重试 ({attempt}/{retry})")
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                print(f"[403] 被拒绝，检查 User-Agent / Cookie：{url}")
                return None
            print(f"[HTTP {resp.status_code}] {url}")
        except requests.RequestException as exc:
            print(f"[请求异常 {type(exc).__name__}] {exc} ({attempt}/{retry})")
        time.sleep(1.5 ** attempt)
    return None


class BookListParser(HTMLParser):
    """从列表页的 article.product_pod 里抽取 书名 / 价格 / 星级 / 详情链接。

    注意：pod 里第一个 <a> 是封面图的链接（没有文字），书名链接在 <h3> 里。
    所以必须区分这两个 <a>，否则 title 会永远是空字符串。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.books = []
        self._in_pod = 0
        self._in_h3 = 0
        self._cur = None
        self._grab = None

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "") or ""
        if tag == "article" and "product_pod" in cls:
            self._in_pod += 1
            self._cur = {"title": "", "title_attr": "", "price": "",
                         "rating": "", "url": ""}
            return
        if not self._in_pod or self._cur is None:
            return
        if tag == "h3":
            self._in_h3 += 1
        elif tag == "a" and self._in_h3:
            self._cur["url"] = attr.get("href", "")
            self._cur["title_attr"] = attr.get("title", "")
            self._grab = "title"
        elif tag == "p" and "price_color" in cls:
            self._grab = "price"
        elif tag == "p" and "star-rating" in cls:
            for token in cls.split():
                if token != "star-rating":
                    self._cur["rating"] = token

    def handle_data(self, data):
        if self._in_pod and self._grab and self._cur is not None:
            self._cur[self._grab] += data.strip()

    def handle_endtag(self, tag):
        if not self._in_pod or self._cur is None:
            return
        if tag == "h3":
            self._in_h3 = max(0, self._in_h3 - 1)
            self._grab = None
        elif tag in ("a", "p"):
            self._grab = None
        elif tag == "article":
            self._in_pod -= 1
            title = self._cur.get("title_attr") or self._cur.get("title") or ""
            self._cur["title"] = title.strip()
            self._cur.pop("title_attr", None)
            if self._cur["title"] and self._cur["url"]:
                self.books.append(self._cur)
            self._cur = None
            self._grab = None
            self._in_h3 = 0


class NextLinkParser(HTMLParser):
    """找 <li class="next"><a href="..."> 里的翻页链接。"""

    def __init__(self):
        super().__init__()
        self.href = None
        self._in_next = False

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "") or ""
        if tag == "li" and "next" in cls.split():
            self._in_next = True
        elif tag == "a" and self._in_next and not self.href:
            self.href = attr.get("href", "")

    def handle_endtag(self, tag):
        if tag == "li":
            self._in_next = False


def parse_list_page(html, page_url):
    parser = BookListParser()
    parser.feed(html)
    for book in parser.books:
        book["url"] = urljoin(page_url, book["url"])
    return parser.books


def next_page_url(html, page_url):
    parser = NextLinkParser()
    parser.feed(html)
    return urljoin(page_url, parser.href) if parser.href else None


def crawl(start=START, max_pages=MAX_PAGES):
    """按页爬取，返回 (成功条数, 失败页数, 数据列表)。"""
    records, ok, failed = [], 0, 0
    url = start
    for page in range(1, max_pages + 1):
        if not url:
            break
        print(f"--- 第 {page} 页 {url}")
        resp = fetch(url)
        if resp is None:
            failed += 1
            break
        items = parse_list_page(resp.text, url)
        if not items:
            print("    未抽取到数据：可能页面是 JS 动态渲染，需找后端接口或改用无头浏览器")
            failed += 1
            break
        ok += len(items)
        records.extend(items)
        print(f"    抽取 {len(items)} 条，累计 {len(records)} 条")
        url = next_page_url(resp.text, url)
    return ok, failed, records


def save_json(records, path=OUT_JSON):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    print(f"已写入 {path}（{len(records)} 条）")


def save_csv(records, path=OUT_CSV):
    if not records:
        return
    fields = list(records[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    print(f"已写入 {path}（{len(records)} 条）")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else START
    t0 = time.time()
    ok, failed, records = crawl(start)
    save_json(records)
    save_csv(records)
    print("=" * 50)
    print(f"成功 {ok} 条 / 失败 {failed} 页 / 耗时 {time.time() - t0:.1f}s")
    print(f"输出文件：{os.path.abspath(OUT_JSON)}")
    if not records:
        print("结果为空，请先确认目标页是静态 HTML，并检查选择器")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
