#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t_py03_3_spider.py —— 迁移题：换一个站点复用抽取框架。

对照 west2_spider.py，我只改了三处：
  1. 目标站换成 https://quotes.toscrape.com/（DOM 结构完全不同：
     是 div.quote > span.text / small.author / a.tag，不是 article.product_pod）
  2. 解析器换成 QuotesParser（逐字段抽取逻辑重写）
  3. 翻页链接仍在 li.next > a（这个巧合一样，但我重新确认过）

没改的是框架部分：politeness（限速）、fetch 的指数退避与 403/429 处理、
save_json 的落盘方式——这些是跟站点无关的，所以直接复用。
"""
import json
import random
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

START = "https://quotes.toscrape.com/page/1/"
HOST = "https://quotes.toscrape.com"
PAGES = 2
MIN_INTERVAL = 1.0
RETRY_TIMES = 3

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) west2-learn-bot/0.1"}

session = requests.Session()
session.headers.update(HEADERS)
_last_request_at = [0.0]


def polite_wait():
    elapsed = time.time() - _last_request_at[0]
    if MIN_INTERVAL - elapsed > 0:
        time.sleep(MIN_INTERVAL - elapsed)
    time.sleep(random.uniform(0.05, 0.2))
    _last_request_at[0] = time.time()


def fetch(url, retry=RETRY_TIMES):
    for attempt in range(1, retry + 1):
        try:
            polite_wait()
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return resp
            if resp.status_code in (403, 429):
                print(f"[{resp.status_code}] 退避重试 {attempt}/{retry}")
                time.sleep(2 ** attempt)
                continue
            print(f"[HTTP {resp.status_code}] {url}")
        except requests.RequestException as exc:
            print(f"[请求异常 {type(exc).__name__}] {exc}")
        time.sleep(1.5 ** attempt)
    return None


class QuotesParser(HTMLParser):
    """抽取 div.quote 里的 名言文本 / 作者 / 标签列表。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.quotes = []
        self._in_quote = 0
        self._cur = None
        self._grab = None

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "") or ""
        if tag == "div" and "quote" in cls.split():
            self._in_quote += 1
            self._cur = {"quote": "", "author": "", "tags": []}
            return
        if not self._in_quote or self._cur is None:
            return
        if tag == "span" and "text" in cls.split():
            self._grab = "quote"
        elif tag == "small" and "author" in cls.split():
            self._grab = "author"
        elif tag == "a" and "tag" in cls.split():
            self._grab = "tag"

    def handle_data(self, data):
        if not self._in_quote or self._cur is None or not self._grab:
            return
        text = data.strip()
        if not text:
            return
        if self._grab == "tag":
            self._cur["tags"].append(text)
        else:
            self._cur[self._grab] += (" " if self._cur[self._grab] else "") + text

    def handle_endtag(self, tag):
        if not self._in_quote or self._cur is None:
            return
        if tag in ("span", "small", "a"):
            self._grab = None
        elif tag == "div":
            self._in_quote -= 1
            if self._cur["quote"]:
                self.quotes.append(self._cur)
            self._cur = None
            self._grab = None


class NextLinkParser(HTMLParser):
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


def parse_quotes(html, page_url):
    parser = QuotesParser()
    parser.feed(html)
    return parser.quotes


def next_url(html, page_url):
    parser = NextLinkParser()
    parser.feed(html)
    return urljoin(page_url, parser.href) if parser.href else None


def crawl(start=START, pages=PAGES):
    records, failed = [], 0
    url = start
    for page in range(1, pages + 1):
        if not url:
            break
        resp = fetch(url)
        if resp is None:
            failed += 1
            break
        items = parse_quotes(resp.text, url)
        records.extend(items)
        print(f"第 {page} 页 +{len(items)} 条，累计 {len(records)} 条")
        url = next_url(resp.text, url)
    return records, failed


def save_json(records, path="quotes.json"):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    print(f"已写入 {path}（{len(records)} 条）")


def main():
    records, failed = crawl()
    save_json(records)
    print(f"成功 {len(records)} 条 / 失败 {failed} 页")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
